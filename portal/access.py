"""Who is signed in, and who may use the portal.

The portal is an entry point: approved people see every app and open it from here, and each
app runs its own access requests and approvals. Getting into the portal needs an approval too:

  status   none -> pending (requested) -> approved | denied;  approved -> revoked
  role     user | admin  (admins approve portal requests and edit the app catalog)

Identity comes from Identity-Aware Proxy: portal/iap.py verifies IAP's signed header and puts
the Google account's email on request.state.user. Any Google account can sign in, but until an
admin approves it, all it can do is ask for access.

Admins in PORTAL_ADMINS (separated by ";" or ",") are always approved admins and can't be
changed from the app, so the portal can't lock itself out.

Locally (IAP_AUDIENCE unset) there is no sign-in: requests act as PORTAL_DEV_USER (default
dev@localhost), an approved admin unless PORTAL_DEV_ROLE=user.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from . import iap
from .store import Store

STATUSES = ("pending", "approved", "denied", "revoked")
ROLES = ("user", "admin")
# Which decisions an admin may make from each status (None = never asked).
DECISIONS = {
    "approved": {None, "pending", "denied", "revoked"},
    "denied": {"pending"},
    "revoked": {"approved"},
}
EMAIL = re.compile(r"^[^@\s/]+@[^@\s/]+\.[^@\s/]+$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enabled() -> bool:
    return iap.audience() is not None


def env_admins() -> set[str]:
    # ";" also separates, because gcloud's --set-env-vars splits values on commas
    return {e.strip().lower() for e in re.split(r"[,;\s]+", os.getenv("PORTAL_ADMINS", "")) if e.strip()}


def clean_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL.match(e):
        raise HTTPException(422, f"not an email address: {email!r}")
    return e


def builtin_admin(email: str) -> bool:
    """PORTAL_ADMINS, plus the local dev user when it runs as an admin (no sign-in)."""
    if email in env_admins():
        return True
    return (not enabled() and os.getenv("PORTAL_DEV_ROLE", "admin") == "admin"
            and email == os.getenv("PORTAL_DEV_USER", "dev@localhost").lower())


# ------------------------------------------------------------------ identity
def identity(request: Request) -> str | None:
    if not enabled():
        return os.getenv("PORTAL_DEV_USER", "dev@localhost").lower()
    email = getattr(request.state, "user", None)
    # IAP's plain headers say "accounts.google.com:me@gmail.com"; the JWT has the bare email.
    return email.split(":", 1)[-1].lower() if email else None


def current_user(request: Request, store: Store, touch: bool = False) -> dict:
    """The signed-in person: {email, name, status, role, permanent, ...}. With touch=True, also
    records the visit (first and last seen)."""
    email = identity(request)
    if not email:
        raise HTTPException(401, "not signed in")
    u = store.get_user(email)
    if touch:
        t = now()
        u = {"email": email, "name": "", "status": None, "role": "user", **(u or {}), "last_seen": t}
        u["first_seen"] = u.get("first_seen") or t
        store.put_user(u)
    u = u or {}
    permanent = builtin_admin(email)
    admin = permanent or (u.get("role") == "admin" and u.get("status") == "approved")
    return {"email": email, "name": u.get("name", ""), "reason": u.get("reason", ""),
            "status": "approved" if permanent else u.get("status"),
            "role": "admin" if admin else "user", "permanent": permanent,
            "requested_at": u.get("requested_at"), "decided_at": u.get("decided_at")}


def require_approved(user: dict) -> None:
    if user["status"] != "approved":
        raise HTTPException(403, "your access to the portal hasn't been approved")


def require_admin(user: dict) -> None:
    require_approved(user)
    if user["role"] != "admin":
        raise HTTPException(403, "admins only")


# ------------------------------------------------------------------ portal access
def request_access(store: Store, user: dict, name: str, reason: str) -> dict:
    if user["status"] == "approved":
        raise HTTPException(409, "you already have access")
    t = now()
    u = store.get_user(user["email"]) or {"email": user["email"], "role": "user", "first_seen": t, "last_seen": t}
    u = {**u, "name": name.strip() or u.get("name", ""), "reason": reason.strip(), "status": "pending",
         "requested_at": t, "decided_at": None, "decided_by": None}
    store.put_user(u)
    return u


def decide(store: Store, admin: dict, email: str, status: str) -> dict:
    """Approve, deny or revoke someone's access to the portal. Approving someone who never
    asked lets them in the first time they sign in."""
    email = clean_email(email)
    if status not in DECISIONS:
        raise HTTPException(422, f"status must be one of {', '.join(DECISIONS)}")
    if builtin_admin(email):
        raise HTTPException(400, "permanent admins (PORTAL_ADMINS) can't be changed here")
    if email == admin["email"]:
        raise HTTPException(400, "you can't change your own access")
    u = store.get_user(email)
    current = (u or {}).get("status")
    if current not in DECISIONS[status]:
        raise HTTPException(409, f"can't change {current or 'no request'} to {status}")
    u = {"email": email, "name": "", "reason": "", "role": "user", "requested_at": None,
         "first_seen": None, "last_seen": None, **(u or {}),
         "status": status, "decided_at": now(), "decided_by": admin["email"]}
    if status != "approved":
        u["role"] = "user"  # losing access also ends admin rights
    store.put_user(u)
    return u


def set_role(store: Store, admin: dict, email: str, role: str) -> dict:
    email = clean_email(email)
    if role not in ROLES:
        raise HTTPException(422, "role must be user or admin")
    if builtin_admin(email):
        raise HTTPException(400, "permanent admins (PORTAL_ADMINS) can't be changed here")
    if email == admin["email"]:
        raise HTTPException(400, "you can't change your own role")
    u = store.get_user(email)
    if u is None:
        raise HTTPException(404, "no such user")
    if role == "admin" and u.get("status") != "approved":
        raise HTTPException(409, "approve their access before making them an admin")
    u = {**u, "role": role}
    store.put_user(u)
    return u


def people(store: Store) -> list[dict]:
    """Everyone known to the portal, waiting requests first, then the most recently seen."""
    rows = {u["email"]: u for u in store.list_users()}
    for e in env_admins():
        rows.setdefault(e, {"email": e, "name": "", "first_seen": None, "last_seen": None})
    out = []
    for e, u in rows.items():
        permanent = builtin_admin(e)
        out.append({"email": e, "name": u.get("name", ""), "reason": u.get("reason", ""),
                    "status": "approved" if permanent else u.get("status"),
                    "role": "admin" if permanent or (u.get("role") == "admin" and u.get("status") == "approved") else "user",
                    "permanent": permanent, **{k: u.get(k) for k in
                    ("requested_at", "decided_at", "decided_by", "first_seen", "last_seen")}})
    out.sort(key=lambda p: p.get("last_seen") or p.get("requested_at") or "", reverse=True)
    out.sort(key=lambda p: p["status"] != "pending")  # stable: pending first
    return out


# ------------------------------------------------------------------ catalog
def sort_apps(apps: list[dict]) -> list[dict]:
    return sorted(apps, key=lambda a: (a.get("order", 999), a.get("name", "").lower()))

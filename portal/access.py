"""Who is signed in, and the rules for requesting and approving access to apps.

Identity comes from Identity-Aware Proxy: portal/iap.py verifies IAP's signed header and puts
the Google account's email on request.state.user. Any Google account may sign in and browse
the catalog; an app's link is only shown once an admin approves that person for that app.

Admins are the emails in PORTAL_ADMINS (separated by ";" or ","; permanent, can't be
demoted) plus anyone an admin promotes. Admins see and open every app.

Locally (IAP_AUDIENCE unset) there is no sign-in: requests act as PORTAL_DEV_USER
(default dev@localhost), an admin unless PORTAL_DEV_ROLE=user.
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
# Which decisions an admin may make from each status (None = no record yet).
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


# ------------------------------------------------------------------ identity
def identity(request: Request) -> str | None:
    if not enabled():
        return os.getenv("PORTAL_DEV_USER", "dev@localhost").lower()
    email = getattr(request.state, "user", None)
    # IAP sends "accounts.google.com:me@gmail.com" in its plain headers; the JWT has the bare email.
    return email.split(":", 1)[-1].lower() if email else None


def role_of(store: Store, email: str) -> str:
    if email in env_admins():
        return "admin"
    if not enabled() and os.getenv("PORTAL_DEV_ROLE", "admin") == "admin":
        return "admin"
    u = store.get_user(email)
    return u.get("role", "user") if u else "user"


def current_user(request: Request, store: Store, touch: bool = False) -> dict:
    """The signed-in person: {email, name, role}. With touch=True, also records the visit."""
    email = identity(request)
    if not email:
        raise HTTPException(401, "not signed in")
    u = store.get_user(email)
    if touch:
        t = now()
        u = {"email": email, "name": "", "role": "user", "first_seen": t, **(u or {}), "last_seen": t}
        store.put_user(u)
    return {"email": email, "name": (u or {}).get("name", ""), "role": role_of(store, email),
            "permanent": email in env_admins()}


def require_admin(user: dict) -> None:
    if user["role"] != "admin":
        raise HTTPException(403, "admins only")


# ------------------------------------------------------------------ catalog view
def sort_apps(apps: list[dict]) -> list[dict]:
    return sorted(apps, key=lambda a: (a.get("order", 999), a.get("name", "").lower()))


def catalog_for(store: Store, user: dict) -> list[dict]:
    """Every app with this person's access to it. The link is only included when they may use it."""
    mine = {r["app_id"]: r for r in store.list_access(email=user["email"])}
    out = []
    for app in sort_apps(store.list_apps()):
        rec = mine.get(app["id"])
        admin = user["role"] == "admin"
        status = "approved" if admin else (rec or {}).get("status")
        item = {k: app.get(k) for k in ("id", "name", "description", "project", "order")}
        item["status"] = status
        item["access"] = {k: rec.get(k) for k in ("status", "note", "requested_at", "decided_at")} if rec else None
        item["url"] = app.get("url") if status == "approved" else None
        out.append(item)
    return out


# ------------------------------------------------------------------ requests
def request_access(store: Store, user: dict, app_id: str, note: str, name: str) -> dict:
    if store.get_app(app_id) is None:
        raise HTTPException(404, "no such app")
    if user["role"] == "admin":
        raise HTTPException(400, "admins already have access to every app")
    rec = store.get_access(app_id, user["email"])
    if rec and rec["status"] == "approved":
        raise HTTPException(409, "you already have access to this app")
    t = now()
    rec = {"email": user["email"], "app_id": app_id, "status": "pending", "note": note.strip(),
           "name": name.strip() or (rec or {}).get("name", ""),
           "requested_at": t, "decided_at": None, "decided_by": None}
    store.put_access(rec)
    if rec["name"]:
        u = store.get_user(user["email"]) or {"email": user["email"], "role": "user", "first_seen": t}
        store.put_user({**u, "name": rec["name"]})
    return rec


def withdraw(store: Store, user: dict, app_id: str) -> None:
    rec = store.get_access(app_id, user["email"])
    if not rec or rec["status"] != "pending":
        raise HTTPException(409, "there's no pending request to withdraw")
    store.delete_access(app_id, user["email"])


def decide(store: Store, admin: dict, app_id: str, email: str, status: str) -> dict:
    """Approve, deny or revoke one person's access to one app. Approving with no request on
    file grants access directly."""
    email = clean_email(email)
    if status not in DECISIONS:
        raise HTTPException(422, f"status must be one of {', '.join(DECISIONS)}")
    if store.get_app(app_id) is None:
        raise HTTPException(404, "no such app")
    rec = store.get_access(app_id, email)
    current = rec["status"] if rec else None
    if current not in DECISIONS[status]:
        raise HTTPException(409, f"can't change {current or 'no request'} to {status}")
    t = now()
    rec = {"email": email, "app_id": app_id, "note": "", "name": "", "requested_at": None,
           **(rec or {}), "status": status, "decided_at": t, "decided_by": admin["email"]}
    store.put_access(rec)
    if store.get_user(email) is None:  # granted before they ever signed in
        store.put_user({"email": email, "name": rec.get("name", ""), "role": "user",
                        "first_seen": None, "last_seen": None})
    return rec


def set_role(store: Store, admin: dict, email: str, role: str) -> dict:
    email = clean_email(email)
    if role not in ROLES:
        raise HTTPException(422, "role must be user or admin")
    if email in env_admins():
        raise HTTPException(400, "permanent admins (PORTAL_ADMINS) can't be changed here")
    if email == admin["email"] and role != "admin":
        raise HTTPException(400, "you can't remove your own admin role")
    u = store.get_user(email)
    if u is None:
        raise HTTPException(404, "no such user")
    u = {**u, "role": role}
    store.put_user(u)
    return u


def users_view(store: Store) -> list[dict]:
    """Every known person with their role and how many apps they can use or have asked for."""
    counts: dict[str, dict] = {}
    for r in store.list_access():
        c = counts.setdefault(r["email"], {"approved": 0, "pending": 0})
        if r["status"] in c:
            c[r["status"]] += 1
    people = {u["email"]: u for u in store.list_users()}
    for e in env_admins():
        people.setdefault(e, {"email": e, "name": "", "first_seen": None, "last_seen": None})
    out = []
    for e, u in people.items():
        out.append({**u, "role": "admin" if e in env_admins() else u.get("role", "user"),
                    "permanent": e in env_admins(), **counts.get(e, {"approved": 0, "pending": 0})})
    return sorted(out, key=lambda u: (u.get("last_seen") or "", u["email"]), reverse=True)

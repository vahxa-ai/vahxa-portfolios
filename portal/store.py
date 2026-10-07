"""Persistence: the app catalog, people who signed in, and their access to each app.

Three kinds of record, keyed by lowercase email and app id:

  users   {email, name, role: user|admin, first_seen, last_seen}
  apps    {id, name, description, url, project, order}
  access  {email, app_id, status, note, name, requested_at, decided_at, decided_by}
          status: pending -> approved | denied;  approved -> revoked

Two backends with the same interface:
  JsonStore       one JSON file (local use and tests), data/portal.json by default
  FirestoreStore  Firestore in Native mode (Cloud Run), selected with PORTAL_STORE=firestore
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def access_id(app_id: str, email: str) -> str:
    return f"{app_id}__{email}"


class Store:
    """Interface shared by both backends."""

    # users
    def get_user(self, email: str) -> dict | None: raise NotImplementedError
    def put_user(self, user: dict) -> None: raise NotImplementedError
    def list_users(self) -> list[dict]: raise NotImplementedError
    # apps
    def get_app(self, app_id: str) -> dict | None: raise NotImplementedError
    def put_app(self, app: dict) -> None: raise NotImplementedError
    def delete_app(self, app_id: str) -> None: raise NotImplementedError
    def list_apps(self) -> list[dict]: raise NotImplementedError
    # access
    def get_access(self, app_id: str, email: str) -> dict | None: raise NotImplementedError
    def put_access(self, rec: dict) -> None: raise NotImplementedError
    def delete_access(self, app_id: str, email: str) -> None: raise NotImplementedError
    def list_access(self, email: str | None = None, app_id: str | None = None,
                    status: str | None = None) -> list[dict]: raise NotImplementedError
    # one-off flags (e.g. "the catalog was seeded")
    def get_meta(self, key: str) -> Any: raise NotImplementedError
    def set_meta(self, key: str, value: Any) -> None: raise NotImplementedError


def _match(rec: dict, **want) -> bool:
    return all(v is None or rec.get(k) == v for k, v in want.items())


class JsonStore(Store):
    """Everything in one JSON file, rewritten atomically on every change."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("PORTAL_DATA", ROOT / "data" / "portal.json"))
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        for k in ("users", "apps", "access", "meta"):
            data.setdefault(k, {})
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        for _ in range(20):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:  # a reader has it open on Windows
                time.sleep(0.05)
        os.replace(tmp, self.path)

    def _get(self, kind: str, key: str) -> dict | None:
        with self._lock:
            return self._load()[kind].get(key)

    def _put(self, kind: str, key: str, value: Any) -> None:
        with self._lock:
            data = self._load()
            data[kind][key] = value
            self._save(data)

    def _delete(self, kind: str, key: str) -> None:
        with self._lock:
            data = self._load()
            if data[kind].pop(key, None) is not None:
                self._save(data)

    def get_user(self, email): return self._get("users", email)
    def put_user(self, user): self._put("users", user["email"], user)
    def list_users(self):
        with self._lock:
            return list(self._load()["users"].values())

    def get_app(self, app_id): return self._get("apps", app_id)
    def put_app(self, app): self._put("apps", app["id"], app)
    def list_apps(self):
        with self._lock:
            return list(self._load()["apps"].values())

    def delete_app(self, app_id):
        with self._lock:
            data = self._load()
            data["apps"].pop(app_id, None)
            data["access"] = {k: v for k, v in data["access"].items() if v["app_id"] != app_id}
            self._save(data)

    def get_access(self, app_id, email): return self._get("access", access_id(app_id, email))
    def put_access(self, rec): self._put("access", access_id(rec["app_id"], rec["email"]), rec)
    def delete_access(self, app_id, email): self._delete("access", access_id(app_id, email))

    def list_access(self, email=None, app_id=None, status=None):
        with self._lock:
            return [r for r in self._load()["access"].values()
                    if _match(r, email=email, app_id=app_id, status=status)]

    def get_meta(self, key):
        with self._lock:
            return self._load()["meta"].get(key)

    def set_meta(self, key, value): self._put("meta", key, value)


class FirestoreStore(Store):
    """Firestore (Native mode) collections portal_users, portal_apps, portal_access, portal_meta."""

    def __init__(self, client=None):
        if client is None:
            from google.cloud import firestore
            client = firestore.Client(database=os.getenv("PORTAL_FIRESTORE_DB", "(default)"))
        self.db = client
        self.users = client.collection("portal_users")
        self.apps = client.collection("portal_apps")
        self.access = client.collection("portal_access")
        self.meta = client.collection("portal_meta")

    @staticmethod
    def _doc(ref) -> dict | None:
        snap = ref.get()
        return snap.to_dict() if snap.exists else None

    def get_user(self, email): return self._doc(self.users.document(email))
    def put_user(self, user): self.users.document(user["email"]).set(user)
    def list_users(self): return [d.to_dict() for d in self.users.stream()]

    def get_app(self, app_id): return self._doc(self.apps.document(app_id))
    def put_app(self, app): self.apps.document(app["id"]).set(app)
    def list_apps(self): return [d.to_dict() for d in self.apps.stream()]

    @staticmethod
    def _eq(query, field: str, value):
        from google.cloud.firestore_v1.base_query import FieldFilter
        return query.where(filter=FieldFilter(field, "==", value))

    def delete_app(self, app_id):
        for d in self._eq(self.access, "app_id", app_id).stream():
            d.reference.delete()
        self.apps.document(app_id).delete()

    def get_access(self, app_id, email): return self._doc(self.access.document(access_id(app_id, email)))
    def put_access(self, rec): self.access.document(access_id(rec["app_id"], rec["email"])).set(rec)
    def delete_access(self, app_id, email): self.access.document(access_id(app_id, email)).delete()

    def list_access(self, email=None, app_id=None, status=None):
        q = self.access
        for field, value in (("email", email), ("app_id", app_id), ("status", status)):
            if value is not None:
                q = self._eq(q, field, value)
        # Filtered again in Python, so equality filters on several fields need no composite index.
        return [r for r in (d.to_dict() for d in q.stream()) if _match(r, email=email, app_id=app_id, status=status)]

    def get_meta(self, key):
        d = self._doc(self.meta.document(key))
        return d.get("value") if d else None

    def set_meta(self, key, value): self.meta.document(key).set({"value": value})


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = FirestoreStore() if os.getenv("PORTAL_STORE") == "firestore" else JsonStore()
    return _store


def set_store(store: Store | None) -> None:
    """Swap the backend (tests)."""
    global _store
    _store = store

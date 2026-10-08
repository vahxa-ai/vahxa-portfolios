"""Persistence: the people who use the portal and the app catalog.

Two kinds of record:

  users  {email, name, reason, status, role, requested_at, decided_at, decided_by,
          first_seen, last_seen}                                  keyed by lowercase email
         status: pending -> approved | denied;  approved -> revoked
  apps   {id, name, description, url, project, order}             keyed by app id

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
    # one-off flags (e.g. "the catalog was seeded")
    def get_meta(self, key: str) -> Any: raise NotImplementedError
    def set_meta(self, key: str, value: Any) -> None: raise NotImplementedError


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
        for k in ("users", "apps", "meta"):
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

    def _get(self, kind: str, key: str):
        with self._lock:
            return self._load()[kind].get(key)

    def _all(self, kind: str) -> list:
        with self._lock:
            return list(self._load()[kind].values())

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
    def list_users(self): return self._all("users")

    def get_app(self, app_id): return self._get("apps", app_id)
    def put_app(self, app): self._put("apps", app["id"], app)
    def delete_app(self, app_id): self._delete("apps", app_id)
    def list_apps(self): return self._all("apps")

    def get_meta(self, key): return self._get("meta", key)
    def set_meta(self, key, value): self._put("meta", key, value)


class FirestoreStore(Store):
    """Firestore (Native mode) collections portal_users, portal_apps and portal_meta."""

    def __init__(self, client=None):
        if client is None:
            from google.cloud import firestore
            client = firestore.Client(database=os.getenv("PORTAL_FIRESTORE_DB", "(default)"))
        self.users = client.collection("portal_users")
        self.apps = client.collection("portal_apps")
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
    def delete_app(self, app_id): self.apps.document(app_id).delete()
    def list_apps(self): return [d.to_dict() for d in self.apps.stream()]

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

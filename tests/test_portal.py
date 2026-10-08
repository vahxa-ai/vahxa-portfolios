"""Offline tests. Run from vahxa-portfolios/:  python -m pytest -q"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portal import iap, main, store as store_mod  # noqa: E402
from portal.catalog import SEED_APPS  # noqa: E402
from portal.store import FirestoreStore, JsonStore  # noqa: E402

ADMIN = "boss@gmail.com"


# ------------------------------------------------------------------ fake Firestore
class _Snap:
    def __init__(self, data):
        self._d = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._d)


class _Doc:
    def __init__(self, coll, key):
        self.coll, self.key = coll, key
        self.reference = self

    def get(self): return _Snap(self.coll.docs.get(self.key))
    def set(self, data): self.coll.docs[self.key] = dict(data)
    def delete(self): self.coll.docs.pop(self.key, None)
    def to_dict(self): return dict(self.coll.docs[self.key])


class _Query:
    def __init__(self, coll, filters=()):
        self.coll, self.filters = coll, filters

    def where(self, filter):
        assert filter.op_string == "=="
        return _Query(self.coll, (*self.filters, (filter.field_path, filter.value)))

    def stream(self):
        return [_Doc(self.coll, k) for k, v in list(self.coll.docs.items())
                if all(v.get(f) == val for f, val in self.filters)]


class _Coll(_Query):
    def __init__(self):
        self.docs = {}
        super().__init__(self)

    def document(self, key): return _Doc(self, key)


class FakeFirestore:
    def __init__(self):
        self.colls = {}

    def collection(self, name): return self.colls.setdefault(name, _Coll())


# ------------------------------------------------------------------ fixtures
@pytest.fixture(params=["json", "firestore"])
def st(request, tmp_path):
    s = JsonStore(tmp_path / "portal.json") if request.param == "json" else FirestoreStore(FakeFirestore())
    store_mod.set_store(s)
    yield s
    store_mod.set_store(None)


@pytest.fixture
def client(st, monkeypatch):
    """Signed-in requests: send `as_=email`; IAP is on and verify() trusts the token as the email."""
    monkeypatch.setenv("IAP_AUDIENCE", "/projects/1/locations/r/services/s")
    monkeypatch.setenv("PORTAL_ADMINS", f"{ADMIN};other-boss@gmail.com")
    monkeypatch.setattr(iap, "verify", lambda token, aud: {"email": token})
    with TestClient(main.app) as c:
        yield c


def call(c, method, path, as_, **kw):
    return c.request(method, path, headers={iap.HEADER: as_}, **kw)


# ------------------------------------------------------------------ sign-in
def test_requests_without_iap_header_are_rejected(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/healthz").status_code == 200


def test_me_records_the_visit(client, st):
    me = call(client, "GET", "/api/me", "alice@gmail.com").json()
    assert me["email"] == "alice@gmail.com" and me["role"] == "user" and me["status"] is None
    assert me["auth_enabled"] and st.get_user("alice@gmail.com")["first_seen"]
    boss = call(client, "GET", "/api/me", ADMIN).json()
    assert boss["role"] == "admin" and boss["status"] == "approved" and boss["permanent"]


# ------------------------------------------------------------------ portal approval
def test_nothing_without_approval(client):
    eve = "eve@gmail.com"
    call(client, "GET", "/api/me", eve)
    for method, path in (("GET", "/api/apps"), ("GET", "/api/admin/people"), ("GET", "/api/admin/apps"),
                         ("POST", "/api/admin/people"), ("DELETE", "/api/admin/apps/sepa")):
        assert call(client, method, path, eve, json={}).status_code == 403, path


def test_request_approve_revoke(client):
    alice = "alice@gmail.com"
    r = call(client, "POST", "/api/access/request", alice, json={"name": "Alice", "reason": "I trade"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert call(client, "GET", "/api/apps", alice).status_code == 403
    assert call(client, "GET", "/api/me", ADMIN).json()["pending_requests"] == 1

    people = call(client, "GET", "/api/admin/people", ADMIN).json()
    assert people[0]["email"] == alice and people[0]["status"] == "pending" and people[0]["reason"] == "I trade"
    r = call(client, "POST", f"/api/admin/people/{alice}/decision", ADMIN, json={"status": "approved"})
    assert r.status_code == 200 and r.json()["decided_by"] == ADMIN

    apps = call(client, "GET", "/api/apps", alice).json()
    assert [a["id"] for a in apps] == [a["id"] for a in SEED_APPS] and all(a["url"] for a in apps)
    assert call(client, "POST", "/api/access/request", alice, json={}).status_code == 409

    assert call(client, "POST", f"/api/admin/people/{alice}/decision", ADMIN, json={"status": "revoked"}).status_code == 200
    assert call(client, "GET", "/api/apps", alice).status_code == 403
    assert call(client, "POST", "/api/access/request", alice, json={}).json()["status"] == "pending"  # may ask again


def test_deny_and_invalid_transitions(client):
    bob = "bob@gmail.com"
    assert call(client, "POST", f"/api/admin/people/{bob}/decision", ADMIN, json={"status": "revoked"}).status_code == 409
    call(client, "POST", "/api/access/request", bob, json={})
    assert call(client, "POST", f"/api/admin/people/{bob}/decision", ADMIN, json={"status": "denied"}).status_code == 200
    assert call(client, "POST", f"/api/admin/people/{bob}/decision", ADMIN, json={"status": "revoked"}).status_code == 409
    assert call(client, "GET", "/api/me", bob).json()["status"] == "denied"
    for target in (ADMIN, "other-boss@gmail.com"):  # permanent admins and yourself are off limits
        assert call(client, "POST", f"/api/admin/people/{target}/decision", ADMIN, json={"status": "revoked"}).status_code == 400


def test_invite_before_first_sign_in(client, st):
    r = call(client, "POST", "/api/admin/people", ADMIN, json={"email": " Carol@Gmail.com "})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["email"] == "carol@gmail.com"
    assert st.get_user("carol@gmail.com")["first_seen"] is None
    assert call(client, "GET", "/api/me", "carol@gmail.com").json()["status"] == "approved"
    assert st.get_user("carol@gmail.com")["first_seen"]  # set by that first visit
    assert call(client, "GET", "/api/apps", "carol@gmail.com").status_code == 200
    assert call(client, "POST", "/api/admin/people", ADMIN, json={"email": "not-an-email"}).status_code == 422


def test_roles(client):
    dan = "dan@gmail.com"
    call(client, "POST", "/api/access/request", dan, json={})
    assert call(client, "PUT", f"/api/admin/people/{dan}/role", ADMIN, json={"role": "admin"}).status_code == 409  # not approved yet
    call(client, "POST", f"/api/admin/people/{dan}/decision", ADMIN, json={"status": "approved"})
    assert call(client, "PUT", f"/api/admin/people/{dan}/role", ADMIN, json={"role": "admin"}).status_code == 200
    assert call(client, "GET", "/api/me", dan).json()["role"] == "admin"
    assert call(client, "GET", "/api/admin/people", dan).status_code == 200
    assert call(client, "PUT", f"/api/admin/people/{dan}/role", dan, json={"role": "user"}).status_code == 400
    assert call(client, "PUT", f"/api/admin/people/{ADMIN}/role", dan, json={"role": "user"}).status_code == 400
    assert call(client, "PUT", "/api/admin/people/ghost@gmail.com/role", ADMIN, json={"role": "admin"}).status_code == 404
    # revoking access also ends admin rights
    call(client, "POST", f"/api/admin/people/{dan}/decision", ADMIN, json={"status": "revoked"})
    assert call(client, "GET", "/api/me", dan).json()["role"] == "user"
    people = {p["email"]: p for p in call(client, "GET", "/api/admin/people", ADMIN).json()}
    assert people["other-boss@gmail.com"]["permanent"] and people[dan]["role"] == "user"


# ------------------------------------------------------------------ catalog
def test_catalog_is_seeded_once(client, st):
    apps = call(client, "GET", "/api/apps", ADMIN).json()
    assert [a["id"] for a in apps] == [a["id"] for a in SEED_APPS]
    st.delete_app("sepa")
    from portal.catalog import seed
    seed(st)
    assert st.get_app("sepa") is None


def test_app_catalog_crud(client):
    body = {"id": "new-app", "name": "New", "description": "d", "url": "https://new.example.com", "order": 9}
    assert call(client, "POST", "/api/admin/apps", ADMIN, json=body).status_code == 201
    assert call(client, "POST", "/api/admin/apps", ADMIN, json=body).status_code == 409
    assert call(client, "POST", "/api/admin/apps", ADMIN, json={**body, "id": "x2", "url": "http://insecure"}).status_code == 422
    assert call(client, "POST", "/api/admin/apps", ADMIN, json={**body, "id": "Bad Id"}).status_code == 422
    assert call(client, "PUT", "/api/admin/apps/new-app", ADMIN, json={**body, "name": "Renamed"}).json()["name"] == "Renamed"
    assert call(client, "PUT", "/api/admin/apps/new-app", ADMIN, json={**body, "id": "other"}).status_code == 422
    assert "new-app" in [a["id"] for a in call(client, "GET", "/api/apps", ADMIN).json()]
    assert call(client, "DELETE", "/api/admin/apps/new-app", ADMIN).status_code == 200
    assert call(client, "DELETE", "/api/admin/apps/new-app", ADMIN).status_code == 404


# ------------------------------------------------------------------ local mode
def test_local_mode_has_no_sign_in(st, monkeypatch):
    monkeypatch.delenv("IAP_AUDIENCE", raising=False)
    monkeypatch.setenv("PORTAL_DEV_USER", "me@localhost")
    with TestClient(main.app) as c:
        assert c.get("/api/me").json()["role"] == "admin" and c.get("/api/apps").status_code == 200
        monkeypatch.setenv("PORTAL_DEV_ROLE", "user")
        me = c.get("/api/me").json()
        assert me["role"] == "user" and me["status"] is None and c.get("/api/apps").status_code == 403

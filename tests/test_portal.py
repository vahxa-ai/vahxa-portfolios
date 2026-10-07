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


def test_me_records_the_visit_and_roles(client, st):
    me = call(client, "GET", "/api/me", "alice@gmail.com").json()
    assert me["email"] == "alice@gmail.com" and me["role"] == "user" and me["auth_enabled"]
    assert st.get_user("alice@gmail.com")["first_seen"]
    boss = call(client, "GET", "/api/me", ADMIN).json()
    assert boss["role"] == "admin" and boss["permanent"]


def test_catalog_is_seeded_once(client, st):
    apps = call(client, "GET", "/api/apps", "alice@gmail.com").json()
    assert [a["id"] for a in apps] == [a["id"] for a in SEED_APPS]
    st.delete_app("sepa")
    from portal.catalog import seed
    seed(st)
    assert st.get_app("sepa") is None


# ------------------------------------------------------------------ request -> approve
def test_link_only_after_approval(client):
    alice = "alice@gmail.com"
    apps = {a["id"]: a for a in call(client, "GET", "/api/apps", alice).json()}
    assert apps["sepa"]["url"] is None and apps["sepa"]["status"] is None

    r = call(client, "POST", "/api/apps/sepa/request", alice, json={"note": "for trading", "name": "Alice"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    apps = {a["id"]: a for a in call(client, "GET", "/api/apps", alice).json()}
    assert apps["sepa"]["status"] == "pending" and apps["sepa"]["url"] is None
    assert call(client, "GET", "/api/me", ADMIN).json()["pending_requests"] == 1

    pending = call(client, "GET", "/api/admin/access?status=pending", ADMIN).json()
    assert pending[0]["email"] == alice and pending[0]["app_name"] == "SEPA Strategy" and pending[0]["name"] == "Alice"
    r = call(client, "POST", f"/api/admin/access/sepa/{alice}", ADMIN, json={"status": "approved"})
    assert r.status_code == 200 and r.json()["decided_by"] == ADMIN

    apps = {a["id"]: a for a in call(client, "GET", "/api/apps", alice).json()}
    assert apps["sepa"]["url"].startswith("https://") and apps["student"]["url"] is None
    assert call(client, "POST", "/api/apps/sepa/request", alice, json={}).status_code == 409

    assert call(client, "POST", f"/api/admin/access/sepa/{alice}", ADMIN, json={"status": "revoked"}).status_code == 200
    apps = {a["id"]: a for a in call(client, "GET", "/api/apps", alice).json()}
    assert apps["sepa"]["status"] == "revoked" and apps["sepa"]["url"] is None
    # after a revoke they may ask again
    assert call(client, "POST", "/api/apps/sepa/request", alice, json={}).json()["status"] == "pending"


def test_deny_withdraw_and_invalid_transitions(client):
    bob = "bob@gmail.com"
    assert call(client, "POST", f"/api/admin/access/sepa/{bob}", ADMIN, json={"status": "revoked"}).status_code == 409
    call(client, "POST", "/api/apps/student/request", bob, json={})
    assert call(client, "POST", f"/api/admin/access/student/{bob}", ADMIN, json={"status": "denied"}).status_code == 200
    assert call(client, "POST", f"/api/admin/access/student/{bob}", ADMIN, json={"status": "revoked"}).status_code == 409
    assert call(client, "DELETE", "/api/apps/student/request", bob).status_code == 409   # not pending
    call(client, "POST", "/api/apps/family-aid/request", bob, json={})
    assert call(client, "DELETE", "/api/apps/family-aid/request", bob).status_code == 200
    assert call(client, "GET", "/api/apps", bob).json()[2]["status"] is None
    assert call(client, "POST", "/api/apps/nope/request", bob, json={}).status_code == 404


def test_direct_grant_before_first_sign_in(client, st):
    r = call(client, "POST", "/api/admin/grants", ADMIN, json={"email": " Carol@Gmail.com ", "app_id": "student"})
    assert r.status_code == 200 and r.json()["email"] == "carol@gmail.com"
    assert st.get_user("carol@gmail.com")["role"] == "user"
    apps = {a["id"]: a for a in call(client, "GET", "/api/apps", "carol@gmail.com").json()}
    assert apps["student"]["url"]
    assert call(client, "POST", "/api/admin/grants", ADMIN, json={"email": "not-an-email", "app_id": "student"}).status_code == 422


# ------------------------------------------------------------------ admin rules
def test_admin_routes_need_admin(client):
    for method, path in (("GET", "/api/admin/access"), ("GET", "/api/admin/users"), ("GET", "/api/admin/apps"),
                         ("POST", "/api/admin/grants"), ("DELETE", "/api/admin/apps/sepa")):
        assert call(client, method, path, "eve@gmail.com", json={}).status_code == 403


def test_admins_see_every_link_and_cant_request(client):
    apps = call(client, "GET", "/api/apps", ADMIN).json()
    assert all(a["url"] and a["status"] == "approved" for a in apps)
    assert call(client, "POST", "/api/apps/sepa/request", ADMIN, json={}).status_code == 400


def test_roles(client):
    call(client, "GET", "/api/me", "dan@gmail.com")
    assert call(client, "PUT", "/api/admin/users/dan@gmail.com/role", ADMIN, json={"role": "admin"}).status_code == 200
    assert call(client, "GET", "/api/me", "dan@gmail.com").json()["role"] == "admin"
    assert call(client, "PUT", "/api/admin/users/dan@gmail.com/role", "dan@gmail.com", json={"role": "user"}).status_code == 400
    assert call(client, "PUT", f"/api/admin/users/{ADMIN}/role", "dan@gmail.com", json={"role": "user"}).status_code == 400
    assert call(client, "PUT", "/api/admin/users/ghost@gmail.com/role", ADMIN, json={"role": "admin"}).status_code == 404
    users = {u["email"]: u for u in call(client, "GET", "/api/admin/users", ADMIN).json()}
    assert users["other-boss@gmail.com"]["permanent"] and users["dan@gmail.com"]["role"] == "admin"


def test_app_catalog_crud(client):
    body = {"id": "new-app", "name": "New", "description": "d", "url": "https://new.example.com", "order": 9}
    assert call(client, "POST", "/api/admin/apps", ADMIN, json=body).status_code == 201
    assert call(client, "POST", "/api/admin/apps", ADMIN, json=body).status_code == 409
    assert call(client, "POST", "/api/admin/apps", ADMIN, json={**body, "id": "x2", "url": "http://insecure"}).status_code == 422
    assert call(client, "POST", "/api/admin/apps", ADMIN, json={**body, "id": "Bad Id"}).status_code == 422
    assert call(client, "PUT", "/api/admin/apps/new-app", ADMIN, json={**body, "name": "Renamed"}).json()["name"] == "Renamed"
    assert call(client, "PUT", "/api/admin/apps/new-app", ADMIN, json={**body, "id": "other"}).status_code == 422
    call(client, "POST", "/api/apps/new-app/request", "fay@gmail.com", json={})
    assert call(client, "DELETE", "/api/admin/apps/new-app", ADMIN).status_code == 200
    assert not [r for r in call(client, "GET", "/api/admin/access", ADMIN).json() if r["app_id"] == "new-app"]


# ------------------------------------------------------------------ local mode
def test_local_mode_has_no_sign_in(st, monkeypatch):
    monkeypatch.delenv("IAP_AUDIENCE", raising=False)
    monkeypatch.setenv("PORTAL_DEV_USER", "me@localhost")
    with TestClient(main.app) as c:
        assert c.get("/api/me").json()["role"] == "admin"
        monkeypatch.setenv("PORTAL_DEV_ROLE", "user")
        assert c.get("/api/me").json()["role"] == "user"

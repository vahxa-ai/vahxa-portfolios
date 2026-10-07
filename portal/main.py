"""Vahxa Portfolios API and web app.

  uvicorn portal.main:app --port 8080

Everything under /api is JSON. If frontend/dist exists (npm run build), the React app is served
from / as well, so production is a single process.
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import access, catalog, iap
from .store import Store, get_store

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
APP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    catalog.seed(get_store())
    yield


app = FastAPI(title="Vahxa Portfolios", version="1.0.0", lifespan=lifespan)
app.add_middleware(iap.IAPMiddleware)
api = APIRouter(prefix="/api")


def store() -> Store:
    return get_store()


def user(request: Request, st: Store = Depends(store)) -> dict:
    return access.current_user(request, st)


def admin(u: dict = Depends(user)) -> dict:
    access.require_admin(u)
    return u


# ------------------------------------------------------------------ models
class AccessRequest(BaseModel):
    note: str = Field(default="", max_length=1000)
    name: str = Field(default="", max_length=100)


class Decision(BaseModel):
    status: Literal["approved", "denied", "revoked"]


class Grant(BaseModel):
    email: str = Field(max_length=254)
    app_id: str


class RoleChange(BaseModel):
    role: Literal["user", "admin"]


class AppIn(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    url: str = Field(max_length=500)
    project: str = Field(default="", max_length=100)
    order: int = Field(default=100, ge=0, le=10_000)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not APP_ID.match(v):
            raise ValueError("id: 2-40 lowercase letters, digits and dashes")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^https://[^\s/]+\.[^\s]+$", v):
            raise ValueError("url must start with https://")
        return v


# ------------------------------------------------------------------ everyone
@api.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@api.get("/me")
def me(request: Request, st: Store = Depends(store)):
    u = access.current_user(request, st, touch=True)
    pending = len(st.list_access(status="pending")) if u["role"] == "admin" else 0
    return {**u, "auth_enabled": access.enabled(), "pending_requests": pending}


@api.get("/apps")
def apps(u: dict = Depends(user), st: Store = Depends(store)):
    return access.catalog_for(st, u)


@api.post("/apps/{app_id}/request")
def request_app(app_id: str, body: AccessRequest, u: dict = Depends(user), st: Store = Depends(store)):
    return access.request_access(st, u, app_id, body.note, body.name)


@api.delete("/apps/{app_id}/request")
def withdraw_request(app_id: str, u: dict = Depends(user), st: Store = Depends(store)):
    access.withdraw(st, u, app_id)
    return {"ok": True}


# ------------------------------------------------------------------ admin: access
@api.get("/admin/access")
def list_access(status: str | None = None, _a: dict = Depends(admin), st: Store = Depends(store)):
    if status and status not in access.STATUSES:
        raise HTTPException(422, "unknown status")
    names = {a["id"]: a["name"] for a in st.list_apps()}
    rows = [{**r, "app_name": names.get(r["app_id"], r["app_id"])} for r in st.list_access(status=status)]
    return sorted(rows, key=lambda r: r.get("decided_at") or r.get("requested_at") or "", reverse=True)


@api.post("/admin/access/{app_id}/{email}")
def decide(app_id: str, email: str, body: Decision, a: dict = Depends(admin), st: Store = Depends(store)):
    return access.decide(st, a, app_id, email, body.status)


@api.post("/admin/grants")
def grant(body: Grant, a: dict = Depends(admin), st: Store = Depends(store)):
    return access.decide(st, a, body.app_id, body.email, "approved")


# ------------------------------------------------------------------ admin: users
@api.get("/admin/users")
def users(_a: dict = Depends(admin), st: Store = Depends(store)):
    return access.users_view(st)


@api.put("/admin/users/{email}/role")
def set_role(email: str, body: RoleChange, a: dict = Depends(admin), st: Store = Depends(store)):
    return access.set_role(st, a, email, body.role)


# ------------------------------------------------------------------ admin: apps
@api.get("/admin/apps")
def admin_apps(_a: dict = Depends(admin), st: Store = Depends(store)):
    return access.sort_apps(st.list_apps())


@api.post("/admin/apps", status_code=201)
def create_app(body: AppIn, _a: dict = Depends(admin), st: Store = Depends(store)):
    if st.get_app(body.id):
        raise HTTPException(409, "an app with this id already exists")
    st.put_app(body.model_dump())
    return body.model_dump()


@api.put("/admin/apps/{app_id}")
def update_app(app_id: str, body: AppIn, _a: dict = Depends(admin), st: Store = Depends(store)):
    if body.id != app_id:
        raise HTTPException(422, "the id can't be changed")
    if not st.get_app(app_id):
        raise HTTPException(404, "no such app")
    st.put_app(body.model_dump())
    return body.model_dump()


@api.delete("/admin/apps/{app_id}")
def delete_app(app_id: str, _a: dict = Depends(admin), st: Store = Depends(store)):
    if not st.get_app(app_id):
        raise HTTPException(404, "no such app")
    st.delete_app(app_id)  # also removes everyone's access records for it
    return {"ok": True}


app.include_router(api)


# ------------------------------------------------------------------ React app
# Built JS/CSS in /assets have a content hash in their names, so browsers may keep them forever;
# index.html must be revalidated on every load, or a browser keeps running an old build.
NO_CACHE = {"Cache-Control": "no-cache"}


class ImmutableAssets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if FRONTEND_DIST.is_dir():
    app.mount("/assets", ImmutableAssets(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and f.is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(f, headers=NO_CACHE)
        return FileResponse(FRONTEND_DIST / "index.html", headers=NO_CACHE)

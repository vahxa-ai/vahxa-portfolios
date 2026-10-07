"""Identity-Aware Proxy (IAP) header verification.

Behind Google Cloud IAP every request carries a signed JWT in `x-goog-iap-jwt-assertion`.
When IAP_AUDIENCE is set (deploy/setup.sh sets it to
/projects/<project-number>/locations/<region>/services/<service>), every request except the
health check must carry a valid assertion for that audience. Requests that
somehow bypass IAP are rejected with 401.

When IAP_AUDIENCE is not set (local use), nothing is checked.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("portal.iap")

HEADER = "x-goog-iap-jwt-assertion"
JWKS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk"
ISSUER = "https://cloud.google.com/iap"
OPEN_PATHS = {"/api/healthz"}  # health checks carry no IAP header


def audience() -> str | None:
    return os.getenv("IAP_AUDIENCE") or None


@lru_cache(maxsize=1)
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)


def verify(token: str, aud: str) -> dict:
    """Decoded claims of a valid IAP assertion; raises jwt.PyJWTError otherwise."""
    key = _jwks().get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["ES256"], audience=aud, issuer=ISSUER)


class IAPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        aud = audience()
        if aud is None or request.url.path in OPEN_PATHS:
            return await call_next(request)
        token = request.headers.get(HEADER)
        if not token:
            return JSONResponse({"detail": "missing IAP assertion"}, status_code=401)
        try:
            claims = verify(token, aud)
        except Exception as e:  # invalid signature, audience, expiry or key fetch failure
            try:  # unverified, only to make a misconfigured IAP_AUDIENCE easy to spot in the logs
                got = jwt.decode(token, options={"verify_signature": False}).get("aud")
            except Exception:
                got = None
            log.warning("rejected request to %s: %s (token audience %s, expected %s)",
                        request.url.path, e, got, aud)
            return JSONResponse({"detail": "invalid IAP assertion"}, status_code=401)
        request.state.user = claims.get("email")
        return await call_next(request)

"""Static bearer-token auth for the run endpoints.

When ``API_AUTH_TOKEN`` is set, the run endpoints require
``Authorization: Bearer <token>`` and the authenticated principal becomes the
recorded actor — so a forged ``ApprovalDecision.by`` can't claim an identity.
When unset (local/dev), auth is open.
"""

from __future__ import annotations

import secrets

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import Settings, get_settings
from .exceptions import AuthError

# auto_error=False: we decide whether a missing credential is an error (only when
# a token is configured), so dev stays open.
_bearer = HTTPBearer(auto_error=False)

# Identity recorded for an authenticated caller (single shared token → one principal).
API_PRINCIPAL = "api"


def require_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Authenticated identity for a request, or ``None`` when auth is disabled.

    Raises 401 when a token is configured but the bearer is missing or wrong.
    Callers that record an actor (approve/reject) should prefer this principal
    over any client-supplied value.
    """
    token = settings.api_auth_token
    if not token:
        return None  # auth disabled (dev) — caller may fall back to a client-supplied identity
    if (
        creds is None
        or creds.scheme.lower() != "bearer"
        or not secrets.compare_digest(creds.credentials, token)
    ):
        raise AuthError("Invalid or missing bearer token")
    return API_PRINCIPAL

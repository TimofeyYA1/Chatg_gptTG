from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from common.config import settings


INTERNAL_AUTH_HEADER = "X-Internal-Token"


def has_valid_internal_token(x_internal_token: str | None) -> bool:
    """
    Returns True when provided internal token is valid.
    In non-production without configured token, allow by default.
    """
    expected = (settings.INTERNAL_API_TOKEN or "").strip()
    is_prod = (settings.APP_ENV or "").strip().lower() in {"prod", "production"}

    if not expected:
        return not is_prod

    provided = (x_internal_token or "").strip()
    return bool(provided) and hmac.compare_digest(provided, expected)


def require_internal_token(
    x_internal_token: str | None = Header(default=None, alias=INTERNAL_AUTH_HEADER),
) -> None:
    """
    Protect internal API routes from direct public access.
    In production, INTERNAL_API_TOKEN must be configured and provided by callers.
    """
    expected = (settings.INTERNAL_API_TOKEN or "").strip()
    is_prod = (settings.APP_ENV or "").strip().lower() in {"prod", "production"}

    if not expected:
        if is_prod:
            raise HTTPException(status_code=503, detail="internal auth is not configured")
        return

    if not has_valid_internal_token(x_internal_token):
        raise HTTPException(status_code=401, detail="unauthorized")

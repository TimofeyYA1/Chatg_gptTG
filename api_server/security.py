from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from common.config import settings


INTERNAL_AUTH_HEADER = "X-Internal-Token"


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

    provided = (x_internal_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")

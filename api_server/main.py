import logging
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import ORJSONResponse, PlainTextResponse

from api_server.routers import (
    account,
    bot_webhook,
    chats,
    health,
    image,
    labs,
    payments,
    promo,
    research,
    subscriptions,
    usage,
    video,
)
from api_server.security import (
    INTERNAL_AUTH_HEADER,
    has_valid_internal_token,
    require_internal_token,
)
from common.config import settings


class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/healthz" not in record.getMessage()


access_logger = logging.getLogger("uvicorn.access")
error_logger = logging.getLogger("uvicorn.error")
access_logger.addFilter(HealthCheckFilter())
error_logger.addFilter(HealthCheckFilter())

is_prod = (settings.APP_ENV or "").strip().lower() in {"prod", "production"}
if is_prod and not (settings.INTERNAL_API_TOKEN or "").strip():
    raise RuntimeError("INTERNAL_API_TOKEN must be configured in production")

show_docs = bool(settings.API_EXPOSE_DOCS) and not is_prod

app = FastAPI(
    title="AI SuperBot API",
    default_response_class=ORJSONResponse,
    docs_url="/docs" if show_docs else None,
    redoc_url="/redoc" if show_docs else None,
    openapi_url="/openapi.json" if show_docs else None,
)


def _extract_hostname(raw_value: str) -> str | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    return parsed.hostname


def _normalize_host_pattern(raw_value: str) -> str | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    if value == "*" or value.startswith("*."):
        return value.lower()
    host = _extract_hostname(value)
    if host:
        return host.lower()
    if ":" in value:
        return value.split(":", 1)[0].strip().lower() or None
    return value.lower()


allowed_origins_raw = (settings.ALLOWED_ORIGINS or "").strip()
if allowed_origins_raw == "*":
    if is_prod:
        raise RuntimeError("ALLOWED_ORIGINS must be explicit in production")
    cors_origins = ["*"]
    cors_allow_credentials = False
    error_logger.warning("ALLOWED_ORIGINS='*' detected; CORS credentials are disabled for safety.")
else:
    cors_origins = [x.strip() for x in allowed_origins_raw.split(",") if x.strip()]
    cors_allow_credentials = True


def _build_allowed_hosts() -> list[str]:
    configured_hosts = [
        host
        for host in (_normalize_host_pattern(x) for x in (settings.ALLOWED_HOSTS or "").split(","))
        if host
    ]
    if configured_hosts:
        return configured_hosts

    allowed_hosts = {"localhost", "127.0.0.1", "api"}
    for value in (settings.API_PUBLIC_URL, settings.PAYMENTS_PUBLIC_URL):
        host = _extract_hostname(value)
        if host:
            allowed_hosts.add(host)
    for origin in cors_origins:
        if origin == "*":
            return ["*"]
        host = _normalize_host_pattern(origin)
        if host:
            allowed_hosts.add(host)
    return sorted(allowed_hosts)


PUBLIC_PATHS = {
    "/healthz",
    "/payments/checkout",
    "/payments/webhook",
}


def _normalize_path(path: str) -> str:
    if path != "/" and path.endswith("/"):
        return path.rstrip("/")
    return path


def _is_public_path(path: str) -> bool:
    return _normalize_path(path) in PUBLIC_PATHS


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_build_allowed_hosts())
if is_prod and bool(settings.FORCE_HTTPS_REDIRECT):
    app.add_middleware(HTTPSRedirectMiddleware)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    path = _normalize_path(request.url.path)
    internal_token = request.headers.get(INTERNAL_AUTH_HEADER)

    if is_prod and not _is_public_path(path) and not has_valid_internal_token(internal_token):
        response = ORJSONResponse(status_code=404, content={"detail": "Not Found"})
    else:
        response = await call_next(request)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if is_prod:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.get("/", include_in_schema=False, response_class=PlainTextResponse)
def root() -> str:
    return "OK"

app.include_router(health.router)
app.include_router(payments.router, prefix="/payments", tags=["payments"])

internal_dep = [Depends(require_internal_token)]
app.include_router(account.router, prefix="/account", tags=["account"], dependencies=internal_dep)
app.include_router(research.router, prefix="/research", tags=["research"], dependencies=internal_dep)
app.include_router(labs.router, prefix="/labs", tags=["labs"], dependencies=internal_dep)
app.include_router(image.router, prefix="/image", tags=["image"], dependencies=internal_dep)
app.include_router(video.router, prefix="/video", tags=["video"], dependencies=internal_dep)
app.include_router(chats.router, prefix="/chats", tags=["chats"], dependencies=internal_dep)
app.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"], dependencies=internal_dep)
app.include_router(usage.router, prefix="/usage", tags=["usage"], dependencies=internal_dep)
app.include_router(promo.router, prefix="/promo", tags=["promo"], dependencies=internal_dep)

# app.include_router(bot_webhook.router, tags=["telegram"])

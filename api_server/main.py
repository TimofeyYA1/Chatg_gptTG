import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

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
from api_server.security import require_internal_token
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

allowed_origins_raw = (settings.ALLOWED_ORIGINS or "").strip()
if allowed_origins_raw == "*":
    cors_origins = ["*"]
    cors_allow_credentials = False
    error_logger.warning("ALLOWED_ORIGINS='*' detected; CORS credentials are disabled for safety.")
else:
    cors_origins = [x.strip() for x in allowed_origins_raw.split(",") if x.strip()]
    cors_allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

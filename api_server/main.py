import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from common.config import settings
from api_server.routers import health, account, image, video, payments, research, labs, bot_webhook
from api_server.routers import chats, subscriptions, promo
from api_server.routers import usage  # <-- добавлено

# Фильтр для отключения логов /healthz в консоли
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/healthz") == -1

# Применяем фильтр к основным логгерам uvicorn
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())
logging.getLogger("uvicorn.error").addFilter(HealthCheckFilter())

app = FastAPI(title="AI SuperBot API", default_response_class=ORJSONResponse)
# from api_server.routers import referrals

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ALLOWED_ORIGINS == "*" else settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(account.router, prefix="/account", tags=["account"])
app.include_router(payments.router, prefix="/payments", tags=["payments"])
app.include_router(research.router, prefix="/research", tags=["research"])
app.include_router(labs.router, prefix="/labs", tags=["labs"])
app.include_router(image.router, prefix="/image", tags=["image"])
app.include_router(video.router, prefix="/video", tags=["video"])
app.include_router(chats.router, prefix="/chats", tags=["chats"])
app.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"])
app.include_router(usage.router, prefix="/usage", tags=["usage"])
app.include_router(promo.router, prefix="/promo", tags=["promo"])
# app.include_router(referrals.router, prefix="/referrals", tags=["referrals"])
# app.include_router(bot_webhook.router, tags=["telegram"])

@app.get("/")
def root():
    return {"ok": True, "name": "AI SuperBot API"}
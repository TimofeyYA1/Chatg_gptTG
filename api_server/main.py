from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from common.config import settings
from api_server.routers import health, account, image, video, payments, research, labs, bot_webhook
from api_server.routers import chats, subscriptions, promo
from api_server.routers import usage  # <-- добавлено
# from api_server.routers import referrals

app = FastAPI(title="AI SuperBot API", default_response_class=ORJSONResponse)

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
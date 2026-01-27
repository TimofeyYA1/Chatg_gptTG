from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

from aiogram import Bot

from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits, Subscription
from common.config import settings
from api_server.services.cloudpayments import cp_service

import logging

router = APIRouter(tags=["payments"])
logger = logging.getLogger("uvicorn.error")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_user(db: Session, chat_id: int) -> User:
    return db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()


def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    c = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user_id)).scalar_one_or_none()
    if c:
        return c
    c = PremiumCredits(user_id=user_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _cp_ok() -> Response:
    # CloudPayments ожидает {"code":0} как "успешно обработано"
    return Response(content='{"code":0}', media_type="application/json")


def _cp_fail(status_code: int = 400, msg: str = "bad request") -> Response:
    # При ошибках НЕ отдаём {"code":0}, чтобы CloudPayments видел проблему и ретраил.
    # code:13 — условный код ошибки (CP важнее HTTP status).
    safe_msg = (msg or "bad request").replace('"', "'")
    return Response(
        content=f'{{"code":13,"message":"{safe_msg}"}}',
        status_code=status_code,
        media_type="application/json",
    )


# --- КОНФИГУРАЦИЯ ТАРИФОВ ---
PLANS_CONFIG = {
    # STANDARD
    "Week_Std": {"price": 399, "desc": "Обычная: Неделя", "rec_interval": "Week", "rec_period": 1},
    "Month_Std": {"price": 1, "desc": "Обычная: Месяц", "rec_interval": "Month", "rec_period": 1},
    "Year_Std": {"price": 5999, "desc": "Обычная: Год", "rec_interval": "Year", "rec_period": 1},
    # PRO
    "Week_Pro": {"price": 799, "desc": "Pro: Неделя", "rec_interval": "Week", "rec_period": 1},
    "Month_Pro": {"price": 2, "desc": "Pro: Месяц", "rec_interval": "Month", "rec_period": 1},
    "Year_Pro": {"price": 11999, "desc": "Pro: Год", "rec_interval": "Year", "rec_period": 1},
}

# Обратная совместимость для старых ссылок
PLANS_CONFIG.update(
    {
        "Week": PLANS_CONFIG["Week_Std"],
        "Month": PLANS_CONFIG["Month_Std"],
        "Year": PLANS_CONFIG["Year_Std"],
    }
)

PACKAGES_CONFIG = {
    "150": {"price": 349, "desc": "Пакет 150 генераций"},
    "1000": {"price": 1999, "desc": "Пакет 1000 генераций"},
    "5000": {"price": 5999, "desc": "Пакет 5000 генераций"},
}


# --- ПОМОЩНИК ОТПРАВКИ СООБЩЕНИЙ (ТЕКСТЫ СТРОГО КАК В ИСХОДНИКЕ) ---
async def send_success_notification(chat_id: int, plan_key: str, message_id: int = 0):
    """
    1. Изменяет старое сообщение на "Максимальный доступ включен".
    2. Отправляет НОВОЕ сообщение с призывом отправить фото.
    """
    try:
        plan_conf = PLANS_CONFIG.get(plan_key, {})
        price = plan_conf.get("price", "---")

        now = datetime.now(timezone.utc)

        is_pro = "Pro" in plan_key
        tier_name = "Pro" if is_pro else "Обычная"

        if "Week" in plan_key:
            next_date_dt = now + timedelta(days=7)
            period_str = "7 дней"
            limit_str = "150"
        elif "Month" in plan_key:
            next_date_dt = now + relativedelta(months=1)
            period_str = "месяц"
            limit_str = "600"
        else:  # Year
            next_date_dt = now + relativedelta(years=1)
            period_str = "год"
            limit_str = "7200"

        plan_name = f"Премиум {tier_name}, {period_str} ({limit_str} генераций)"
        next_date_str = next_date_dt.strftime("%d.%m.%Y, %H:%M MSK")

        text_congrats = (
            "✅ <b>Максимальный доступ включён!</b>\n\n"
            f"✨ Генераций осталось: {limit_str}\n"
            f"🌸 Текущая подписка: {plan_name}\n"
            f"💳 Следующее списание: {next_date_str} ({price}₽)\n\n"
            "💡 Хочешь ещё больше крутых образов? Посмотри /packages и пополняй генерации!"
        )

        text_start = (
            "🏁 <b>Начинаем творить!</b>\n\n"
            "✨ <b>FaceLab</b> — меняй образ за секунды!\n"
            "Примеряй стили и тренды за пару кликов.\n\n"
            "📸 <b>Пожалуйста, отправьте фото, где хорошо видно лицо — и мы сразу создадим новый образ!</b>"
        )

        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            if message_id and message_id > 0:
                try:
                    await bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=text_congrats,
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                except Exception as edit_err:
                    logger.warning(f"Could not edit msg {message_id}: {edit_err}. Sending as new.")
                    await bot.send_message(chat_id=chat_id, text=text_congrats, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=chat_id, text=text_congrats, parse_mode="HTML")

            await bot.send_message(chat_id=chat_id, text=text_start, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Failed to send TG notification to {chat_id}: {e}")


# -------------------------------------------------------------------------
# 1) СТРАНИЦА ОПЛАТЫ
# -------------------------------------------------------------------------
@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(chat_id: int, type: str, value: str, message_id: int = 0):
    public_id = settings.CLOUDPAYMENTS_PUBLIC_ID

    price = 0
    description = ""
    is_subscription = False
    conf = None

    if type == "plan":
        conf = PLANS_CONFIG.get(value)
        if not conf:
            return HTMLResponse("Неверный тариф", 400)
        price = conf["price"]
        description = conf["desc"]
        is_subscription = True

    elif type == "pkg":
        conf = PACKAGES_CONFIG.get(value)
        if not conf:
            return HTMLResponse("Неверный пакет", 400)
        price = conf["price"]
        description = conf["desc"]
        is_subscription = False

    else:
        return HTMLResponse("Неверный тип оплаты", 400)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Оплата</title>
        <script src="https://widget.cloudpayments.ru/bundles/cloudpayments.js"></script>
        <style>
            body {{ font-family: -apple-system, system-ui, sans-serif; background: #1a1a1a; color: #fff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .card {{ background: #2d2d2d; padding: 2rem; border-radius: 12px; text-align: center; max-width: 400px; width: 90%; }}
            button {{ background: #007bff; color: white; border: none; padding: 15px 30px; border-radius: 8px; font-size: 18px; cursor: pointer; width: 100%; margin-top: 20px; }}
            button:hover {{ background: #0056b3; }}
            .footer {{ margin-top: 20px; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>{description}</h2>
            <h1>{price} ₽</h1>
            <button id="payButton">Оплатить картой</button>
            <p id="status" style="margin-top:10px; color:#888;"></p>
            <div class="footer">CloudPayments Secured</div>
        </div>

        <script>
            this.pay = function () {{
                var widget = new cp.CloudPayments();

                // InvoiceId: type_value_chatId_messageId_timestamp
                var invoiceId = '{type}_{value}_{chat_id}_{message_id}_' + Date.now();

                var data = {{
                    publicId: '{public_id}',
                    description: '{description}',
                    amount: {price},
                    currency: 'RUB',
                    invoiceId: invoiceId,
                    accountId: '{chat_id}',
                    skin: "modern",
                    data: {{
                        my_type: '{type}',
                        my_value: '{value}'
                    }}
                }};

                if ({str(is_subscription).lower()}) {{
                    data.data.cloudPayments = {{
                        recurrent: {{
                            interval: '{conf.get("rec_interval") if is_subscription else ""}',
                            period: {conf.get("rec_period") if is_subscription else 0}
                        }}
                    }};
                }}

                widget.pay('charge', data, {{
                    onSuccess: function (options) {{
                        document.getElementById("status").innerText = "✅ Оплата успешна! Можно закрыть окно и вернуться в бота.";
                        document.getElementById("payButton").style.display = "none";
                    }},
                    onFail: function (reason, options) {{
                        document.getElementById("status").innerText = "❌ Ошибка: " + reason;
                    }},
                    onComplete: function (paymentResult, options) {{}}
                }});
            }};

            document.getElementById('payButton').addEventListener('click', pay);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# -------------------------------------------------------------------------
# 2) WEBHOOK
# -------------------------------------------------------------------------
@router.post("/webhook")
async def cloudpayments_webhook(request: Request, db: Session = Depends(get_db)):
    # 1) Подпись (обязательно!)
    body = await request.body()

    # В разных конфигурациях встречается Content-HMAC / X-Content-HMAC
    signature = request.headers.get("Content-HMAC") or request.headers.get("X-Content-HMAC") or ""

    logger.info(
        f"📩 CP webhook hit: ip={request.client.host if request.client else '-'} "
        f"len={len(body)} hmac={'present' if bool(signature) else 'missing'} "
        f"ct={request.headers.get('content-type','-')}"
    )

    if not signature:
        logger.warning("❌ CP webhook: missing HMAC header")
        return _cp_fail(403, "missing signature")

    if not cp_service.check_signature(body, signature):
        logger.warning("❌ CP webhook: invalid signature")
        return _cp_fail(403, "invalid signature")

    # 2) Парсим payload (обычно form-urlencoded)
    ct = (request.headers.get("content-type") or "").lower()
    data = None
    try:
        if "application/json" in ct:
            data = await request.json()
        else:
            data = await request.form()
    except Exception as e:
        logger.error(f"❌ CP webhook: cannot parse body: {e}")
        return _cp_fail(400, "cannot parse body")

    def _get(k: str, default=None):
        # form -> MultiDict, json -> dict
        try:
            return data.get(k, default)
        except Exception:
            return default

    # 3) Проверка статуса
    status = _get("Status")
    if status not in ["Completed", "Authorized"]:
        logger.info(f"🚫 CP Webhook: Payment Status='{status}' (not success). Ignoring.")
        return _cp_ok()

    # 4) Данные
    chat_id_str = _get("AccountId")
    invoice_id = _get("InvoiceId", "") or ""
    cp_sub_id = _get("SubscriptionId")

    amount_raw = _get("Amount", "0")
    try:
        amount = float(amount_raw)
    except Exception:
        amount = 0.0

    pay_type = ""
    pay_value = ""
    message_id = 0

    # InvoiceId:
    # plan_Week_Std_<chatId>_<messageId>_<ts>
    # pkg_150_<chatId>_<messageId>_<ts>
    parts = invoice_id.split("_") if invoice_id else []
    if len(parts) >= 3:
        pay_type = parts[0]

        if pay_type == "plan":
            # plan_Week_Std_123_456_789
            if len(parts) >= 5 and (("Std" in parts[2]) or ("Pro" in parts[2])):
                pay_value = f"{parts[1]}_{parts[2]}"
                if not chat_id_str and len(parts) >= 4:
                    chat_id_str = parts[3]
                if len(parts) >= 5:
                    try:
                        message_id = int(parts[4])
                    except Exception:
                        message_id = 0
            else:
                # план без _Std/_Pro (старые ссылки)
                pay_value = parts[1]
                if not chat_id_str and len(parts) >= 3:
                    chat_id_str = parts[2]
                if len(parts) >= 4:
                    try:
                        message_id = int(parts[3])
                    except Exception:
                        message_id = 0

        elif pay_type == "pkg":
            pay_value = parts[1] if len(parts) >= 2 else ""
            if not chat_id_str and len(parts) >= 3:
                chat_id_str = parts[2]
            if len(parts) >= 4:
                try:
                    message_id = int(parts[3])
                except Exception:
                    message_id = 0

    if not chat_id_str or not pay_type:
        logger.warning(f"❌ CP webhook: missing required fields. AccountId={chat_id_str}, pay_type={pay_type}")
        return _cp_fail(400, "missing required fields")

    try:
        chat_id = int(chat_id_str)
    except Exception:
        logger.wa

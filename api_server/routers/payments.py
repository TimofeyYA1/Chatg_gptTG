from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

# Импортируем Bot для отправки уведомлений
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


# --- КОНФИГУРАЦИЯ ТАРИФОВ ---
PLANS_CONFIG = {
    # STANDARD
    "Week_Std":  {"price": 399,   "desc": "Обычная: Неделя", "rec_interval": "Week",  "rec_period": 1},
    "Month_Std": {"price": 799,  "desc": "Обычная версия месяц",  "rec_interval": "Month", "rec_period": 1},
    "Year_Std":  {"price": 5999,  "desc": "Обычная: Год",    "rec_interval": "Year",  "rec_period": 1},

    # PRO
    "Week_Pro":  {"price": 799,   "desc": "Pro: Неделя", "rec_interval": "Week",  "rec_period": 1},
    "Month_Pro": {"price": 1599,  "desc": "Pro версия месяц",  "rec_interval": "Month", "rec_period": 1},
    "Year_Pro":  {"price": 11999, "desc": "Pro: Год",    "rec_interval": "Year",  "rec_period": 1},
}

# Обратная совместимость для старых ссылок (если есть)
PLANS_CONFIG.update({
    "Week": PLANS_CONFIG["Week_Std"],
    "Month": PLANS_CONFIG["Month_Std"],
    "Year": PLANS_CONFIG["Year_Std"],
})

PACKAGES_CONFIG = {
    "150":  {"price": 349,  "desc": "Пакет 150 генераций"},
    "1000": {"price": 1999, "desc": "Пакет 1000 генераций"},
    "5000": {"price": 5999, "desc": "Пакет 5000 генераций"},
}


# --- ПОМОЩНИК ОТПРАВКИ СООБЩЕНИЙ ---
async def send_success_notification(chat_id: int, plan_key: str, message_id: int = 0):
    """
    1. Изменяет старое сообщение на "Максимальный доступ включен".
    2. Отправляет НОВОЕ сообщение с призывом отправить фото.
    """
    try:
        # Данные для текста
        plan_conf = PLANS_CONFIG.get(plan_key, {})
        price = plan_conf.get("price", "---")

        # Расчет даты следующего списания для текста
        now = datetime.now(timezone.utc)

        # Определяем название плана для пользователя
        is_pro = "Pro" in plan_key
        tier_name = "Pro" if is_pro else "Обычная"

        if "Week" in plan_key:
            next_date_dt = now + timedelta(days=7)
            period_str = "7 дней"
            limit_str = "150"
        elif "Month" in plan_key:
            next_date_dt = now + relativedelta(months=1)
            period_str = "месяц"
            limit_str = "300"
        else:  # Year
            next_date_dt = now + relativedelta(years=1)
            period_str = "год"
            limit_str = "7200"

        plan_name = f"Премиум {tier_name}, {period_str} ({limit_str} генераций)"
        next_date_str = next_date_dt.strftime("%d.%m.%Y, %H:%M MSK")

        # Текст 1: Поздравление
        text_congrats = (
            "✅ <b>Максимальный доступ включён!</b>\n\n"
            f"✨ Генераций осталось: {limit_str}\n"
            f"🌸 Текущая подписка: {plan_name}\n"
            f"💳 Следующее списание: {next_date_str} ({price}₽)\n\n"
            "💡 Хочешь ещё больше крутых образов? Посмотри /packages и пополняй генерации!"
        )

        # Текст 2: Инструкция (приходит следом)
        text_start = (
            "🏁 <b>Начинаем творить!</b>\n\n"
            "✨ <b>FaceLab</b> — меняй образ за секунды!\n"
            "Примеряй стили и тренды за пару кликов.\n\n"
            "📸 <b>Пожалуйста, отправьте фото, где хорошо видно лицо — и мы сразу создадим новый образ!</b>"
        )

        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            # ШАГ 1: Редактируем сообщение с оплатой
            if message_id and message_id > 0:
                try:
                    # reply_markup=None удаляет кнопку "Оплатить"
                    await bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=text_congrats,
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                except Exception as edit_err:
                    logger.warning(f"Could not edit msg {message_id}: {edit_err}. Sending as new.")
                    # Если сообщение удалили, шлем поздравление новым сообщением
                    await bot.send_message(chat_id=chat_id, text=text_congrats, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=chat_id, text=text_congrats, parse_mode="HTML")

            # ШАГ 2: Отправляем призыв к действию (Start)
            await bot.send_message(chat_id=chat_id, text=text_start, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Failed to send TG notification to {chat_id}: {e}")


# -------------------------------------------------------------------------
# 1. СТРАНИЦА ОПЛАТЫ
# -------------------------------------------------------------------------
@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(chat_id: int, type: str, value: str, message_id: int = 0):
    public_id = settings.CLOUDPAYMENTS_PUBLIC_ID

    price = 0
    description = ""
    is_subscription = False

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
# 2. WEBHOOK
# -------------------------------------------------------------------------
@router.post("/webhook")
async def cloudpayments_webhook(request: Request, db: Session = Depends(get_db)):
    # 1) Проверка подписи (БЕЗОПАСНОСТЬ)
    body = await request.body()
    signature = request.headers.get("Content-HMAC", "")

    # Важно: если подпись отсутствует/неверная — НЕ говорим CloudPayments "ok"
    # и не даём злоумышленнику активировать подписку простым POST-ом.
    if not signature:
        logger.warning("❌ CP webhook: missing Content-HMAC")
        return Response(content='{"code":13,"message":"missing signature"}', status_code=403, media_type="application/json")

    if not cp_service.check_signature(body, signature):
        logger.warning("❌ CP webhook: invalid signature")
        return Response(content='{"code":13,"message":"invalid signature"}', status_code=403, media_type="application/json")

    form = await request.form()

    # 2) ПРОВЕРКА СТАТУСА ПЛАТЕЖА
    status = form.get("Status")
    if status not in ["Completed", "Authorized"]:
        logger.info(f"🚫 CP Webhook: Payment Status is '{status}' (not success). Ignoring.")
        return Response(content='{"code":0}', media_type="application/json")

    # 3) Извлечение данных
    chat_id_str = form.get("AccountId")
    amount = float(form.get("Amount", 0))
    cp_sub_id = form.get("SubscriptionId")
    invoice_id = form.get("InvoiceId", "")

    pay_type = ""
    pay_value = ""
    message_id = 0

    # Парсинг InvoiceId: plan_Week_Std_12345_1111_ts
    parts = invoice_id.split("_")
    if len(parts) >= 3:
        pay_type = parts[0]
        # Если в parts[2] есть Std или Pro, значит value было с подчеркиванием
        if pay_type == "plan" and len(parts) > 2 and ("Std" in parts[2] or "Pro" in parts[2]):
            pay_value = parts[1] + "_" + parts[2]
            if not chat_id_str:
                chat_id_str = parts[3]
            if len(parts) >= 6:
                try:
                    message_id = int(parts[4])
                except:
                    message_id = 0
        else:
            # Старая логика или пакеты (pkg_150_...)
            pay_value = parts[1]
            if not chat_id_str:
                chat_id_str = parts[2]
            if len(parts) >= 5:
                try:
                    message_id = int(parts[3])
                except:
                    message_id = 0

    if not chat_id_str or not pay_type:
        return Response(content='{"code":0}', media_type="application/json")

    try:
        chat_id = int(chat_id_str)
    except:
        return Response(content='{"code":0}', media_type="application/json")

    logger.info(f"💰 CP Webhook SUCCESS: User={chat_id}, Type={pay_type}, Val={pay_value}, Status={status}")

    # 4) Взаимодействие с БД
    user = _get_user(db, chat_id)
    if not user:
        user = User(chat_id=chat_id, role="free")
        db.add(user)
        db.commit()
        db.refresh(user)

    # --- ЛОГИКА НАЧИСЛЕНИЯ ПОДПИСКИ ---
    if pay_type == "plan":
        conf = PLANS_CONFIG.get(pay_value)
        if conf:
            start = _now()
            sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()

            if sub and sub.current_period_end and sub.current_period_end > start:
                start = sub.current_period_end

            if "Week" in conf["rec_interval"]:
                end = start + timedelta(days=7)
            elif "Month" in conf["rec_interval"]:
                end = start + relativedelta(months=1)
            else:
                end = start + relativedelta(years=1)

            if not sub:
                sub = Subscription(user_id=user.id)
                db.add(sub)

            sub.plan = pay_value
            sub.status = "active"
            sub.current_period_end = end
            sub.cancel_at_period_end = False

            if cp_sub_id:
                sub.cp_sub_id = cp_sub_id

            credits = _get_or_create_credits(db, user.id)
            # Лимиты берем из названий, т.к. конфиг тут только для платежей
            if "Week" in pay_value:
                credits.img_limit_base = 150
            elif "Month" in pay_value:
                credits.img_limit_base = 300
            elif "Year" in pay_value:
                credits.img_limit_base = 7200

            db.commit()
            logger.info(f"✅ Subscription saved to DB for {chat_id}")

            # 5) Уведомления в ТГ (Поздравление + Старт)
            await send_success_notification(chat_id, pay_value, message_id)

    # --- ЛОГИКА ДЛЯ ПАКЕТОВ ---
    elif pay_type == "pkg":
        qty = 0
        try:
            qty = int(pay_value)
        except:
            pass

        if qty > 0:
            credits = _get_or_create_credits(db, user.id)
            credits.image_credits = (credits.image_credits or 0) + qty
            db.commit()
            logger.info(f"✅ Package credits saved to DB for {chat_id}")

    return Response(content='{"code":0}', media_type="application/json")

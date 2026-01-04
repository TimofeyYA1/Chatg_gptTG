from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
    if c: return c
    c = PremiumCredits(user_id=user_id)
    db.add(c); db.commit(); db.refresh(c)
    return c

# --- КОНФИГУРАЦИЯ ТАРИФОВ ---
PLANS_CONFIG = {
    "Week":  {"price": 399,  "desc": "Премиум на 7 дней", "rec_interval": "Week",  "rec_period": 1},
    "Month": {"price": 1199, "desc": "Премиум на месяц",  "rec_interval": "Month", "rec_period": 1},
    "Year":  {"price": 5999, "desc": "Премиум на год",    "rec_interval": "Year",  "rec_period": 1},
}

PACKAGES_CONFIG = {
    "150":  {"price": 349,  "desc": "Пакет 150 генераций"},
    "1000": {"price": 1999, "desc": "Пакет 1000 генераций"},
    "5000": {"price": 5999, "desc": "Пакет 5000 генераций"},
}

# --- ПОМОЩНИК ОТПРАВКИ СООБЩЕНИЙ ---
async def send_success_notification(chat_id: int, plan_key: str, message_id: int = 0):
    """
    1. Изменяет старое сообщение на Поздравление.
    2. Отправляет НОВОЕ сообщение с призывом отправить фото.
    """
    try:
        names_map = {
            "Week": "Премиум на 7 дней (150 генераций)",
            "Month": "Премиум на месяц (600 генераций)",
            "Year": "Премиум на год (7200 генераций)"
        }
        plan_name = names_map.get(plan_key, f"Премиум ({plan_key})")

        # Текст 1: Поздравление (заменяет кнопку оплаты)
        text_congrats = (
            "🎉 <b>Ура, у вас теперь Премиум-подписка!</b>\n\n"
            f"Вы приобрели пакет <b>{plan_name}</b> 💫\n\n"
            "⭐️ Теперь вам доступны:\n"
            "- более 100 премиум-стилей\n"
            "- HD-качество изображений\n"
            "- отсутствие рекламы\n"
            "- приоритетная генерация\n\n"
            "Спасибо, что выбрали MyLook! 👍"
        )

        # Текст 2: Инструкция (приходит следом)
        text_start = (
            "🏁 <b>Начинаем творить!</b>\n\n"
            "✨ <b>BeautyAIMasterBot</b> — ваша AI-лаборатория.\n"
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
                        reply_markup=None
                    )
                except Exception as edit_err:
                    logger.warning(f"Could not edit msg {message_id}: {edit_err}. Sending as new.")
                    # Если сообщение удалили, шлем поздравление новым сообщением
                    await bot.send_message(chat_id=chat_id, text=text_congrats, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=chat_id, text=text_congrats, parse_mode="HTML")
            
            # ШАГ 2: Отправляем призыв к действию (Start)
            # Небольшая пауза для естественности (опционально, тут без sleep ради скорости)
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
        if not conf: return HTMLResponse("Неверный тариф", 400)
        price = conf["price"]
        description = conf["desc"]
        is_subscription = True
        
    elif type == "pkg":
        conf = PACKAGES_CONFIG.get(value)
        if not conf: return HTMLResponse("Неверный пакет", 400)
        price = conf["price"]
        description = conf["desc"]
        is_subscription = False

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
    # 1. Проверка подписи
    body = await request.body()
    signature = request.headers.get("Content-HMAC", "")

    if not cp_service.check_signature(body, signature):
        logger.warning("❌ Invalid CP Signature")
        return Response(content='{"code":0}', media_type="application/json") 

    form = await request.form()
    
    # 2. ПРОВЕРКА СТАТУСА ПЛАТЕЖА
    status = form.get("Status")
    if status not in ["Completed", "Authorized"]:
        logger.info(f"🚫 CP Webhook: Payment Status is '{status}' (not success). Ignoring.")
        return Response(content='{"code":0}', media_type="application/json")

    # 3. Извлечение данных
    chat_id_str = form.get("AccountId") 
    amount = float(form.get("Amount", 0))
    cp_sub_id = form.get("SubscriptionId")
    invoice_id = form.get("InvoiceId", "")
    
    pay_type = ""
    pay_value = ""
    message_id = 0
    
    parts = invoice_id.split("_")
    if len(parts) >= 3:
        pay_type = parts[0]
        pay_value = parts[1]
        if not chat_id_str:
             chat_id_str = parts[2]
        if len(parts) >= 5: 
            try: message_id = int(parts[3])
            except: message_id = 0

    if not chat_id_str or not pay_type:
        return Response(content='{"code":0}')

    try:
        chat_id = int(chat_id_str)
    except:
        return Response(content='{"code":0}')

    logger.info(f"💰 CP Webhook SUCCESS: User={chat_id}, Type={pay_type}, Val={pay_value}, Status={status}")

    # 4. Взаимодействие с БД
    user = _get_user(db, chat_id)
    if not user:
        user = User(chat_id=chat_id, role="free")
        db.add(user); db.commit(); db.refresh(user)
    
    # --- ЛОГИКА НАЧИСЛЕНИЯ ПОДПИСКИ ---
    if pay_type == "plan":
        conf = PLANS_CONFIG.get(pay_value)
        if conf:
            start = _now()
            sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
            
            if sub and sub.current_period_end and sub.current_period_end > start:
                start = sub.current_period_end
            
            if conf["rec_interval"] == "Week":
                end = start + timedelta(days=7)
            elif conf["rec_interval"] == "Month":
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
            limits_map = {"Week": 150, "Month": 600, "Year": 7200}
            credits.img_limit_base = limits_map.get(pay_value, 0)
            
            db.commit()
            logger.info(f"✅ Subscription saved to DB for {chat_id}")
            
            # 5. Уведомления в ТГ (Поздравление + Старт)
            await send_success_notification(chat_id, pay_value, message_id)

    # --- ЛОГИКА ДЛЯ ПАКЕТОВ ---
    elif pay_type == "pkg":
        qty = 0
        try: qty = int(pay_value)
        except: pass
        
        if qty > 0:
            credits = _get_or_create_credits(db, user.id)
            credits.image_credits = (credits.image_credits or 0) + qty
            db.commit()
            logger.info(f"✅ Package credits saved to DB for {chat_id}")

    return Response(content='{"code":0}', media_type="application/json")
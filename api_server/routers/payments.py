from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

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
# recurrent: { interval: 'Week' | 'Month' | 'Year', period: 1 }
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

# -------------------------------------------------------------------------
# 1. СТРАНИЦА ОПЛАТЫ (ОТКРЫВАЕТСЯ В БРАУЗЕРЕ ЮЗЕРА)
# -------------------------------------------------------------------------
@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(chat_id: int, type: str, value: str):
    """
    type: 'plan' или 'pkg'
    value: 'Week'/'Month' или '150'/'1000'
    """
    
    public_id = settings.CLOUDPAYMENTS_PUBLIC_ID
    
    # Определяем цену и параметры
    price = 0
    description = ""
    is_subscription = False
    
    # Конфиг для JS виджета (подписка)
    recurrent_json_obj = "undefined"

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

    # HTML с виджетом
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
                var data = {{
                    publicId: '{public_id}',
                    description: '{description}',
                    amount: {price},
                    currency: 'RUB',
                    invoiceId: '{type}_{value}_{chat_id}_' + Date.now(), // ID заказа для сверки
                    accountId: '{chat_id}', // chat_id плательщика
                    skin: "modern",
                    data: {{
                        my_type: '{type}',
                        my_value: '{value}'
                    }}
                }};

                // Для подписок добавляем объект рекуррентных платежей
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
# 2. WEBHOOK (СЮДА ПРИХОДИТ УВЕДОМЛЕНИЕ ОТ CLOUDPAYMENTS)
# -------------------------------------------------------------------------
@router.post("/webhook")
async def cloudpayments_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Обрабатывает 'pay' (успешная оплата) и 'recurrent' (автосписание).
    """
    body = await request.body()
    signature = request.headers.get("Content-HMAC", "")

    if not cp_service.check_signature(body, signature):
        logger.warning("❌ Invalid CP Signature")
        return Response(content='{"code":0}', media_type="application/json") # CP всегда ждет code:0

    # CloudPayments шлет данные в Form Data
    form = await request.form()
    
    # Извлекаем данные
    chat_id_str = form.get("AccountId") 
    amount = float(form.get("Amount", 0))
    cp_sub_id = form.get("SubscriptionId") # Придет, если создалась подписка
    
    # InvoiceId: type_value_chatid_ts
    invoice_id = form.get("InvoiceId", "")
    
    if not chat_id_str:
        # Если AccountId пустой, пробуем достать из InvoiceId
        if invoice_id:
            try: chat_id_str = invoice_id.split("_")[2]
            except: pass
            
    if not chat_id_str or not invoice_id:
        return Response(content='{"code":0}')

    try:
        chat_id = int(chat_id_str)
    except:
        return Response(content='{"code":0}')

    # Разбираем InvoiceId
    parts = invoice_id.split("_")
    if len(parts) < 3:
        return Response(content='{"code":0}')
    
    pay_type = parts[0] # plan / pkg
    pay_value = parts[1] # Week / 150

    logger.info(f"💰 CP Webhook: User={chat_id}, Type={pay_type}, Val={pay_value}, Amount={amount}")

    user = _get_user(db, chat_id)
    if not user:
        user = User(chat_id=chat_id, role="free")
        db.add(user); db.commit(); db.refresh(user)

    # --- ЛОГИКА НАЧИСЛЕНИЯ ---
    
    if pay_type == "plan":
        # Активация подписки
        conf = PLANS_CONFIG.get(pay_value)
        if conf:
            start = _now()
            # Ищем текущую подписку
            sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
            
            # Если есть активная подписка, продлеваем её
            if sub and sub.current_period_end and sub.current_period_end > start:
                start = sub.current_period_end
            
            # Считаем дату окончания
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
            
            # Сохраняем ID подписки из CP
            if cp_sub_id:
                sub.cp_sub_id = cp_sub_id
            
            # Обновляем лимиты (Хардкод лимитов в API для синхронизации)
            credits = _get_or_create_credits(db, user.id)
            limits_map = {"Week": 150, "Month": 600, "Year": 7200}
            credits.img_limit_base = limits_map.get(pay_value, 0)
            
            # Обнуляем счетчик "бесплатных" или использованных в рамках подписки, если новая подписка
            # (Логика может отличаться в зависимости от требований, здесь простой сброс)
            # credits.web_queries = 0 

            db.commit()
            logger.info(f"✅ Subscription {pay_value} activated for {chat_id}")

    elif pay_type == "pkg":
        # Покупка пакета
        qty = 0
        try: qty = int(pay_value)
        except: pass
        
        if qty > 0:
            credits = _get_or_create_credits(db, user.id)
            credits.image_credits = (credits.image_credits or 0) + qty
            db.commit()
            logger.info(f"✅ Added {qty} credits for {chat_id}")

    return Response(content='{"code":0}', media_type="application/json")
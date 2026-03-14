from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.services.cloudpayments import cp_service
from common.config import settings
from common.subscriptions import (
    ADDON_QTY,
    CHECKOUT_PLAN_KEYS,
    addon_price_rub_for_tier,
    get_plan_spec,
    normalize_plan_key,
    plan_duration_end,
    tier_code_from_plan,
    tier_name_ru,
)
from db_adapter.database import get_db
from db_adapter.models import PremiumCredits, Subscription, User

router = APIRouter(tags=["payments"])
logger = logging.getLogger("uvicorn.error")

ADMIN_IDS = settings.admin_id_list


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_user(db: Session, chat_id: int) -> User | None:
    return db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()


def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    credits = db.execute(
        select(PremiumCredits).where(PremiumCredits.user_id == user_id)
    ).scalar_one_or_none()
    if credits:
        return credits
    credits = PremiumCredits(user_id=user_id)
    db.add(credits)
    db.commit()
    db.refresh(credits)
    return credits


def _has_active_subscription(sub: Subscription | None, now: datetime | None = None) -> bool:
    if not sub:
        return False
    now = now or _now()
    if sub.current_period_end is None:
        return True
    return sub.current_period_end > now


def _plan_checkout_config(plan_raw: str | None) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    plan_key = normalize_plan_key(plan_raw)
    if not plan_key:
        return None, None
    if plan_key not in CHECKOUT_PLAN_KEYS:
        return None, None
    spec = get_plan_spec(plan_key)
    if not spec:
        return None, None
    return plan_key, {
        "price": spec.price_rub,
        "desc": f"Премиум {tier_name_ru(spec.tier)} — {spec.title_ru}",
        "rec_interval": spec.recurring_interval,
        "rec_period": spec.recurring_period,
        "images_limit": spec.images_limit,
        "period_label": spec.title_ru.split(" ")[0],
    }


def _parse_invoice_id(invoice_id: str, fallback_chat_id: str | None = None) -> tuple[str, str, int, str | None]:
    # Expected format: "{type}_{value}_{chat_id}_{message_id}_{timestamp}"
    # "value" may include underscores, so we parse from the right.
    parts = (invoice_id or "").split("_")
    if len(parts) < 5:
        return "", "", 0, fallback_chat_id

    pay_type = parts[0]
    chat_id_str = fallback_chat_id or parts[-3]
    try:
        message_id = int(parts[-2])
    except Exception:
        message_id = 0
    pay_value = "_".join(parts[1:-3]).strip()
    return pay_type, pay_value, message_id, chat_id_str


class BalanceTopupIn(BaseModel):
    chat_id: int
    amount: int


class AddonBuyIn(BaseModel):
    chat_id: int
    qty: int
    price_cents: int | None = None


@router.post("/balance/topup")
def balance_topup(payload: BalanceTopupIn, db: Session = Depends(get_db)):
    amount = int(payload.amount or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")

    user = _get_user(db, payload.chat_id)
    if not user:
        user = User(chat_id=payload.chat_id, role="free")
        db.add(user)
        db.commit()
        db.refresh(user)

    user.balance_cents = (user.balance_cents or 0) + amount
    db.commit()
    return {"ok": True, "balance_cents": user.balance_cents}


@router.post("/addons/buy")
def buy_addon(payload: AddonBuyIn, db: Session = Depends(get_db)):
    qty = int(payload.qty or 0)
    if qty != ADDON_QTY:
        raise HTTPException(status_code=400, detail=f"only {ADDON_QTY}-generation addon is available")

    user = _get_user(db, payload.chat_id)
    if not user:
        user = User(chat_id=payload.chat_id, role="free")
        db.add(user)
        db.commit()
        db.refresh(user)

    sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
    if not _has_active_subscription(sub):
        raise HTTPException(status_code=400, detail="active subscription required")

    tier_code = tier_code_from_plan(sub.plan if sub else None)
    expected_price_cents = addon_price_rub_for_tier(tier_code) * 100
    if payload.price_cents is not None and int(payload.price_cents) != expected_price_cents:
        raise HTTPException(status_code=400, detail="price mismatch")

    credits = _get_or_create_credits(db, user.id)
    credits.image_credits = (credits.image_credits or 0) + qty
    db.commit()

    return {
        "ok": True,
        "chat_id": payload.chat_id,
        "qty_added": qty,
        "tier": tier_code,
        "expected_price_cents": expected_price_cents,
        "active_until": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
    }


async def notify_admins(bot: Bot, user_id: int, item_name: str, price: Any):
    try:
        try:
            chat = await bot.get_chat(user_id)
            username = f"@{chat.username}" if chat.username else f"ID: {user_id}"
            full_name = chat.full_name or "Unknown"
        except Exception:
            username = f"ID: {user_id}"
            full_name = "Unknown"

        text = (
            "💰 <b>НОВАЯ ПОКУПКА!</b>\n\n"
            f"👤 <b>Пользователь:</b> {full_name} ({username})\n"
            f"🛒 <b>Товар:</b> {item_name}\n"
            f"💵 <b>Сумма:</b> {price}₽"
        )

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
            except Exception as err:
                logger.warning(f"Failed to notify admin {admin_id}: {err}")
    except Exception as err:
        logger.error(f"Failed to prepare admin notification: {err}")


async def send_success_notification(chat_id: int, plan_key: str, message_id: int = 0):
    spec = get_plan_spec(plan_key)
    if not spec:
        return

    next_date_dt = plan_duration_end(_now(), plan_key)
    next_date_str = next_date_dt.strftime("%d.%m.%Y, %H:%M MSK")
    plan_name = f"Премиум {tier_name_ru(spec.tier)}, {spec.title_ru} ({spec.images_limit} генераций)"

    text_congrats = (
        "✅ <b>Максимальный доступ включён!</b>\n\n"
        f"✨ Генераций осталось: {spec.images_limit}\n"
        f"🌸 Текущая подписка: {plan_name}\n"
        f"💳 Следующее списание: {next_date_str} ({spec.price_rub}₽)\n\n"
        "💡 Хочешь ещё больше крутых образов? Посмотри /packages и пополняй генерации!"
    )
    text_start = (
        "🏁 <b>Начинаем творить!</b>\n\n"
        "✨ <b>FaceLab</b> — меняй образ за секунды!\n"
        "📸 Пожалуйста, отправьте фото, где хорошо видно лицо."
    )

    try:
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
            await notify_admins(bot, chat_id, f"Подписка: {plan_key}", spec.price_rub)
    except Exception as err:
        logger.error(f"Failed to send TG notification to {chat_id}: {err}")


@router.get("/checkout", response_class=HTMLResponse)
def checkout_page(chat_id: int, type: str, value: str, message_id: int = 0, db: Session = Depends(get_db)):
    public_id = settings.CLOUDPAYMENTS_PUBLIC_ID

    price = 0
    description = ""
    is_subscription = False
    conf: dict[str, Any] = {}

    if type == "plan":
        plan_key, conf = _plan_checkout_config(value)
        if not plan_key or not conf:
            return HTMLResponse("Неверный тариф", 400)
        price = int(conf["price"])
        description = str(conf["desc"])
        value = plan_key
        is_subscription = True
    elif type == "pkg":
        if value != str(ADDON_QTY):
            return HTMLResponse(f"Доступен только пакет {ADDON_QTY} генераций", 400)

        user = _get_user(db, chat_id)
        if not user:
            return HTMLResponse("Пакет доступен только при активной подписке", 400)
        sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
        if not _has_active_subscription(sub):
            return HTMLResponse("Пакет доступен только при активной подписке", 400)

        tier_code = tier_code_from_plan(sub.plan if sub else None)
        tier_name = tier_name_ru(tier_code)
        price = addon_price_rub_for_tier(tier_code)
        description = f"Пакет {ADDON_QTY} генераций ({tier_name})"
        conf = {"price": price, "desc": description}
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


@router.post("/webhook")
async def cloudpayments_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("Content-HMAC", "")
    if not signature:
        logger.warning("CP webhook: missing Content-HMAC")
        return Response(content='{"code":13,"message":"missing signature"}', status_code=403, media_type="application/json")
    if not cp_service.check_signature(body, signature):
        logger.warning("CP webhook: invalid signature")
        return Response(content='{"code":13,"message":"invalid signature"}', status_code=403, media_type="application/json")

    form = await request.form()
    status = str(form.get("Status") or "")
    if status not in {"Completed", "Authorized"}:
        logger.info(f"CP webhook ignored by status: {status}")
        return Response(content='{"code":0}', media_type="application/json")

    amount = float(form.get("Amount", 0))
    cp_sub_id = form.get("SubscriptionId")
    invoice_id = str(form.get("InvoiceId") or "")
    chat_id_hint = form.get("AccountId")

    pay_type, pay_value, message_id, chat_id_str = _parse_invoice_id(invoice_id, fallback_chat_id=chat_id_hint)
    if not pay_type or not pay_value or not chat_id_str:
        return Response(content='{"code":0}', media_type="application/json")

    try:
        chat_id = int(chat_id_str)
    except Exception:
        return Response(content='{"code":0}', media_type="application/json")

    logger.info(f"CP webhook success: user={chat_id}, type={pay_type}, value={pay_value}, status={status}")

    user = _get_user(db, chat_id)
    if not user:
        user = User(chat_id=chat_id, role="free")
        db.add(user)
        db.commit()
        db.refresh(user)

    if pay_type == "plan":
        plan_key = normalize_plan_key(pay_value)
        spec = get_plan_spec(plan_key)
        if spec:
            start = _now()
            sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
            if sub and sub.current_period_end and sub.current_period_end > start:
                start = sub.current_period_end
            end = plan_duration_end(start, plan_key)

            if not sub:
                sub = Subscription(user_id=user.id)
                db.add(sub)

            sub.plan = plan_key
            sub.status = "active"
            sub.current_period_end = end
            sub.cancel_at_period_end = False
            if cp_sub_id:
                sub.cp_sub_id = cp_sub_id

            credits = _get_or_create_credits(db, user.id)
            credits.img_limit_base = spec.images_limit
            db.commit()

            logger.info(f"Subscription saved for user {chat_id} plan={plan_key}")
            await send_success_notification(chat_id, plan_key, message_id)

    elif pay_type == "pkg":
        try:
            qty = int(pay_value)
        except Exception:
            qty = 0

        if qty == ADDON_QTY:
            sub = db.execute(select(Subscription).where(Subscription.user_id == user.id)).scalar_one_or_none()
            if not _has_active_subscription(sub):
                logger.warning(f"Package rejected for {chat_id}: no active subscription")
            else:
                tier_code = tier_code_from_plan(sub.plan if sub else None)
                expected_rub = addon_price_rub_for_tier(tier_code)
                paid_rub = int(round(amount))
                if paid_rub != expected_rub:
                    logger.warning(
                        f"Package rejected for {chat_id}: price mismatch paid={paid_rub} expected={expected_rub}"
                    )
                    return Response(content='{"code":0}', media_type="application/json")

                credits = _get_or_create_credits(db, user.id)
                credits.image_credits = (credits.image_credits or 0) + qty
                db.commit()

                async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
                    await notify_admins(bot, chat_id, f"Пакет: {qty} генераций", paid_rub)
                    if message_id:
                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    "✅ <b>Оплата прошла успешно!</b>\n"
                                    f"Вам начислено {qty} дополнительных генераций."
                                ),
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
        else:
            logger.warning(f"Package rejected for {chat_id}: unsupported qty={qty}")

    return Response(content='{"code":0}', media_type="application/json")

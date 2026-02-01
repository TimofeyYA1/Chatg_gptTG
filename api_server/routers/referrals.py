# # api_server/routers/referrals.py
# from __future__ import annotations

# from fastapi import APIRouter, Depends, HTTPException
# from pydantic import BaseModel
# from sqlalchemy import select, func
# from sqlalchemy.orm import Session

# from db_adapter.database import get_db
# from db_adapter.models import User, Referral
# from common.config import settings

# router = APIRouter(tags=["referrals"])


# # --------- Pydantic ---------
# class ReferralRegisterIn(BaseModel):
#     """
#     referrer_chat_id  — tg-chat_id пригласившего
#     invited_chat_id   — tg-chat_id приглашённого (того, кто только что нажал /start)
#     """
#     referrer_chat_id: int
#     invited_chat_id: int


# # --------- helpers ---------
# def _get_user(db: Session, chat_id: int) -> User | None:
#     return db.execute(
#         select(User).where(User.chat_id == chat_id)
#     ).scalar_one_or_none()


# def _create_user(db: Session, chat_id: int) -> User:
#     user = User(chat_id=chat_id)
#     db.add(user)
#     db.flush()
#     return user


# # --------- summary ---------
# @router.get("/summary/{chat_id}")
# def referrals_summary(chat_id: int, db: Session = Depends(get_db)):
#     """
#     Краткая статка по рефералке:
#     - invited     — сколько людей пришло по ссылке
#     - subscribed  — сколько из них дали «премиальный» бонус (оформили плату и т.п.)
#     """
#     user = _get_user(db, chat_id)
#     link = f"https://t.me/{getattr(settings, 'BOT_NAME', 'FacelabXbot')}?start={chat_id}"

#     if not user:
#         return {"invited": 0, "subscribed": 0, "ref_link": link}

#     invited = db.execute(
#         select(func.count(Referral.id)).where(Referral.referrer_id == user.id)
#     ).scalar() or 0

#     subscribed = db.execute(
#         select(func.count(Referral.id)).where(
#             Referral.referrer_id == user.id,
#             Referral.bonus_awarded.is_(True),
#         )
#     ).scalar() or 0

#     return {"invited": invited, "subscribed": subscribed, "ref_link": link}


# # --------- register (новый реферал) ---------
# @router.post("/register")
# def register_referral(payload: ReferralRegisterIn, db: Session = Depends(get_db)):
#     """
#     Регистрирует реферала.

#     ВАЖНО:
#     - считаем только НОВЫХ пользователей:
#       если invited_chat_id уже есть в таблице users — ничего не создаём;
#     - один юзер не может быть рефералом дважды;
#     - себя пригласить нельзя.

#     Бонусы:
#     - пригласившему начисляем бонус в баланс (REFERRAL_BONUS_CENTS, по умолчанию = 10⭐)
#       до лимита REFERRAL_MAX_INVITES_PER_USER (если задан).
#     - приглашённому можно выдать welcome-бонус (WELCOME_BONUS_CENTS), если хочется.
#     """

#     ref_chat_id = payload.referrer_chat_id
#     invited_chat_id = payload.invited_chat_id

#     if ref_chat_id == invited_chat_id:
#         raise HTTPException(status_code=400, detail="self_referral_not_allowed")

#     # --- ищем реферера ---
#     referrer = _get_user(db, ref_chat_id)
#     if not referrer:
#         raise HTTPException(status_code=404, detail="referrer_not_found")

#     # --- проверяем, новый ли это пользователь ---
#     invited_user = _get_user(db, invited_chat_id)
#     if invited_user:
#         # пользователь уже существует => он НЕ считается "новым"
#         already_ref = db.execute(
#             select(func.count(Referral.id)).where(
#                 Referral.invited_user_id == invited_user.id
#             )
#         ).scalar() or 0

#         if already_ref:
#             return {"ok": False, "reason": "already_referred_or_existing_user"}

#         return {"ok": False, "reason": "invited_user_not_new"}

#     # --- создаём НОВОГО пользователя ---
#     invited_user = _create_user(db, invited_chat_id)

#     # на всякий — проверяем, что нет дубликата Referral по invited_id
#     exists = db.execute(
#         select(func.count(Referral.id)).where(
#             Referral.invited_user_id == invited_user.id
#         )
#     ).scalar() or 0
#     if exists:
#         return {"ok": False, "reason": "already_referred"}

#     # --- создаём запись Referral ---
#     ref = Referral(
#         referrer_id=referrer.id,
#         invited_user_id=invited_user.id,
#         bonus_awarded=False,
#     )
#     db.add(ref)

#     # --- логика бонусов ---
#     current_invited = db.execute(
#         select(func.count(Referral.id)).where(Referral.referrer_id == referrer.id)
#     ).scalar() or 0

#     # 10⭐ = 1000 "центов"
#     bonus_cents = getattr(settings, "REFERRAL_BONUS_CENTS", 10_00)
#     welcome_cents = getattr(settings, "REFERRAL_WELCOME_BONUS_CENTS", 0)
#     max_invites = getattr(settings, "REFERRAL_MAX_INVITES_PER_USER", None)

#     bonus_applied = False

#     # бонус пригласившему
#     if bonus_cents > 0 and (max_invites is None or current_invited < max_invites):
#         referrer.balance_cents = (referrer.balance_cents or 0) + bonus_cents
#         bonus_applied = True

#     # welcome-бонус приглашённому (опционально)
#     if welcome_cents > 0:
#         invited_user.balance_cents = (invited_user.balance_cents or 0) + welcome_cents

#     db.commit()
#     db.refresh(ref)

#     return {
#         "ok": True,
#         "referral_id": ref.id,
#         "referrer_id": referrer.id,
#         "invited_id": invited_user.id,
#         "referrer_chat_id": ref_chat_id,
#         "invited_chat_id": invited_chat_id,
#         "bonus_cents": bonus_cents if bonus_applied else 0,
#         "welcome_cents": welcome_cents,
#     }


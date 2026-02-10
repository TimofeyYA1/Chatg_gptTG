from __future__ import annotations

import io
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy import select, func
import pandas as pd

from common.config import settings
from db_adapter.database import get_db
from db_adapter.models import User, PremiumCredits, Subscription, Payment

router = APIRouter(tags=["usage"])


def _get_or_create_user(db: Session, chat_id: int) -> User:
    user = db.execute(
        select(User).where(User.chat_id == chat_id)
    ).scalar_one_or_none()

    if user:
        return user

    user = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _get_or_create_credits(db: Session, user: User) -> PremiumCredits:
    # если есть — берём
    p = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user.id)).scalar_one_or_none()
    if p:
        return p
    # нет — создаём
    p = PremiumCredits(user_id=user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _apply_limit(kind: str, value: int, p: PremiumCredits) -> None:
    """
    messages:
        базовый: msg_limit_base
        usage: total_queries
        докупки: web_queries_left

    images:
        базовый: img_limit_base
        usage: web_queries
        докупки: image_credits

    video:
        базовый: video_limit_base
        usage: video_used
        докупки: video_seconds_left

    Алгоритм для всех одинаковый:
        1) считаем остаток по базовому лимиту (base - used)
        2) смотрим, хватает ли base + addons на value
        3) если нет — 402
        4) если да — увеличиваем used, и если ушли «поверх» base, то режем докупки
    """

    if kind == "messages":
        base = p.msg_limit_base or 0
        used = p.total_queries or 0
        addon = p.web_queries_left or 0

        remaining_plan = max(0, base - used)
        total_remaining = remaining_plan + addon
        if value > total_remaining:
            raise HTTPException(402, "text limit exceeded")

        used_before = used
        used_after = used + value

        over_before = max(0, used_before - base)
        over_after = max(0, used_after - base)
        delta_over = max(0, over_after - over_before)

        p.total_queries = used_after
        p.web_queries_left = max(0, addon - delta_over)

    elif kind == "images":
        base = p.img_limit_base or 0
        used = p.web_queries or 0
        addon = p.image_credits or 0

        remaining_plan = max(0, base - used)
        total_remaining = remaining_plan + addon
        if value > total_remaining:
            raise HTTPException(402, "image limit exceeded")

        used_before = used
        used_after = used + value

        over_before = max(0, used_before - base)
        over_after = max(0, used_after - base)
        delta_over = max(0, over_after - over_before)

        p.web_queries = used_after
        p.image_credits = max(0, addon - delta_over)

    elif kind == "video":
        base = p.video_limit_base or 0
        used = p.video_used or 0
        addon = p.video_seconds_left or 0

        remaining_plan = max(0, base - used)
        total_remaining = remaining_plan + addon
        if value > total_remaining:
            raise HTTPException(402, "video limit exceeded")

        used_before = used
        used_after = used + value

        over_before = max(0, used_before - base)
        over_after = max(0, used_after - base)
        delta_over = max(0, over_after - over_before)

        p.video_used = used_after
        p.video_seconds_left = max(0, addon - delta_over)

    else:
        raise HTTPException(400, "invalid kind")


@router.post("/increment")
def increment_usage(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { chat_id: int, kind: "messages"|"images"|"video", value?: int }

    - создаём user/credits при первом запросе
    - проверяем лимит; если не хватает -> 402
    - если хватает -> обновляем usage / докупки и 200
    """
    try:
        chat_id = int(payload.get("chat_id"))
        kind = str(payload.get("kind"))
        value = int(payload.get("value", 1))
    except Exception:
        raise HTTPException(400, "invalid payload")

    if value <= 0:
        raise HTTPException(400, "value must be positive")
    if kind not in {"messages", "images", "video"}:
        raise HTTPException(400, "invalid kind")

    user = _get_or_create_user(db, chat_id)
    credits = _get_or_create_credits(db, user)

    _apply_limit(kind, value, credits)

    db.commit()
    return {"ok": True}


@router.get("/export_users_stats")
def export_users_stats(token: str, db: Session = Depends(get_db)):
    """
    Экспорт статистики по всем пользователям в Excel (XLSX).
    Доступ только по токену (простейшая защита для админского эндпоинта).
    """
    # Простейшая защита - токен из конфига или хардкод (для внутреннего использования ботом)
    # В идеале - вынести в settings.ADMIN_SECRET_KEY
    if token != settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(403, "Access denied")

    # Запрос с join-ами для получения всех данных
    stmt = (
        select(
            User.chat_id,
            User.username,
            User.role,
            User.balance_cents,
            User.created_at,
            # Limits
            PremiumCredits.img_limit_base,
            PremiumCredits.msg_limit_base,
            PremiumCredits.video_limit_base,
            # Usage
            PremiumCredits.web_queries.label("img_used"),
            PremiumCredits.total_queries.label("msg_used"),
            PremiumCredits.video_used,
            # Addons
            PremiumCredits.image_credits.label("img_addon"),
            PremiumCredits.web_queries_left.label("msg_addon"),
            PremiumCredits.video_seconds_left.label("video_addon"),
            # Subscription
            Subscription.plan,
            Subscription.status.label("sub_status"),
            Subscription.current_period_end
        )
        .outerjoin(PremiumCredits, User.id == PremiumCredits.user_id)
        .outerjoin(Subscription, User.id == Subscription.user_id)
        .order_by(User.created_at.desc())
    )
    
    results = db.execute(stmt).all()
    
    # Превращаем в список словарей
    data = []
    for row in results:
        # row - это Row object, к полям можно обращаться как row.chat_id
        d = {
            "Chat ID": row.chat_id,
            "Username": row.username or "",
            "Role": row.role,
            "Balance (RUB)": (row.balance_cents or 0) / 100.0,
            "Registered": row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "",
            
            # Subscription
            "Plan": row.plan or "-",
            "Sub Status": row.sub_status or "-",
            "Sub End": row.current_period_end.strftime("%Y-%m-%d") if row.current_period_end else "-",
            
            # Images
            "Images Limit": row.img_limit_base or 0,
            "Images Used": row.img_used or 0,
            "Images Addon": row.img_addon or 0,
            
            # Messages (если используются)
            "Msgs Limit": row.msg_limit_base or 0,
            "Msgs Used": row.msg_used or 0,
            "Msgs Addon": row.msg_addon or 0,
        }
        data.append(d)
        
    if not data:
        return Response(content=b"", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # Создаем DataFrame
    df = pd.DataFrame(data)
    
    # Записываем в BytesIO
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Users Stats')
        
        # Авто-ширина колонок (примерная)
        worksheet = writer.sheets['Users Stats']
        for idx, col in enumerate(df.columns):
            max_len = max(
                df[col].astype(str).map(len).max(),
                len(col)
            ) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_len, 50) # A=65

    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="users_stats.xlsx"'
    }
    return Response(content=output.getvalue(), headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

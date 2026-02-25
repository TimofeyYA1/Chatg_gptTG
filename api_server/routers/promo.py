from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db_adapter.database import get_db
from db_adapter.models import (
    PremiumCredits,
    PromoToken,
    PromoUsage,
    Subscription,
    TrackLink,
    TrackLinkClick,
    User,
)

router = APIRouter(tags=["promo"])

DEFAULT_PROMO_CREDITS = 50


class GeneratePromoIn(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    credits: int = Field(default=DEFAULT_PROMO_CREDITS, ge=1, le=100000)
    max_uses: int = Field(default=1, ge=1, le=100000)


class UsePromoIn(BaseModel):
    chat_id: int
    token: str


class GenerateTrackLinkIn(BaseModel):
    count: int = Field(default=1, ge=1, le=100)


class UseTrackLinkIn(BaseModel):
    chat_id: int
    token: str


def _get_or_create_user(db: Session, chat_id: int) -> User:
    u = db.execute(select(User).where(User.chat_id == chat_id)).scalar_one_or_none()
    if u:
        return u
    u = User(chat_id=chat_id, role="free", balance_cents=0)
    db.add(u)
    db.flush()
    return u


def _get_or_create_credits(db: Session, user_id: int) -> PremiumCredits:
    p = db.execute(select(PremiumCredits).where(PremiumCredits.user_id == user_id)).scalar_one_or_none()
    if p:
        return p
    p = PremiumCredits(user_id=user_id)
    db.add(p)
    db.flush()
    return p


def _ts(dt: datetime | None) -> float:
    if not dt:
        return float("-inf")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.timestamp()


def _get_subscriptions_map(db: Session, user_ids: list[int]) -> dict[int, Subscription]:
    if not user_ids:
        return {}
    subs = db.execute(
        select(Subscription).where(Subscription.user_id.in_(set(user_ids)))
    ).scalars().all()
    result: dict[int, Subscription] = {}
    for sub in subs:
        prev = result.get(sub.user_id)
        if prev is None or _ts(sub.current_period_end) > _ts(prev.current_period_end):
            result[sub.user_id] = sub
    return result


def _usage_entry(usage: PromoUsage, user: User, sub: Subscription | None) -> dict:
    return {
        "chat_id": user.chat_id,
        "username": user.username,
        "used_at": usage.used_at.isoformat() if usage.used_at else None,
        "has_subscription": sub is not None,
        "subscription_plan": sub.plan if sub else None,
        "subscription_status": sub.status if sub else None,
        "subscription_current_period_end": (
            sub.current_period_end.isoformat() if sub and sub.current_period_end else None
        ),
    }


def _track_click_entry(click: TrackLinkClick, user: User, sub: Subscription | None) -> dict:
    return {
        "chat_id": user.chat_id,
        "username": user.username,
        "clicked_at": click.clicked_at.isoformat() if click.clicked_at else None,
        "has_subscription": sub is not None,
        "subscription_plan": sub.plan if sub else None,
        "subscription_status": sub.status if sub else None,
        "subscription_current_period_end": (
            sub.current_period_end.isoformat() if sub and sub.current_period_end else None
        ),
    }


def _token_stats(
    db: Session,
    token: PromoToken,
    include_users: bool,
    users_limit: int,
) -> dict:
    usage_rows = db.execute(
        select(PromoUsage, User)
        .join(User, User.id == PromoUsage.user_id)
        .where(PromoUsage.token_id == token.id)
        .order_by(PromoUsage.used_at.desc())
    ).all()

    user_ids = [u.id for _, u in usage_rows]
    subscriptions_by_user = _get_subscriptions_map(db, user_ids)

    buyers: list[dict] = []
    non_buyers: list[dict] = []
    for usage, user in usage_rows:
        entry = _usage_entry(usage, user, subscriptions_by_user.get(user.id))
        if entry["has_subscription"]:
            buyers.append(entry)
        else:
            non_buyers.append(entry)

    usage_count = len(usage_rows)
    converted = len(buyers)
    not_converted = len(non_buyers)
    conversion_rate = round((converted / usage_count) * 100, 2) if usage_count else 0.0

    item = {
        "id": token.id,
        "token": token.token,
        "credits": token.credits,
        "max_uses": token.max_uses,
        "current_uses": token.current_uses,
        "usage_records": usage_count,
        "remaining_uses": max(0, token.max_uses - token.current_uses),
        "is_exhausted": token.current_uses >= token.max_uses,
        "converted_subs": converted,
        "not_converted_subs": not_converted,
        "conversion_rate_percent": conversion_rate,
        "created_at": token.created_at.isoformat() if token.created_at else None,
    }

    if include_users:
        item.update({
            "buyers_total": len(buyers),
            "non_buyers_total": len(non_buyers),
            "users_limit": users_limit,
            "buyers": buyers[:users_limit],
            "non_buyers": non_buyers[:users_limit],
            "buyers_truncated": len(buyers) > users_limit,
            "non_buyers_truncated": len(non_buyers) > users_limit,
        })

    return item


def _track_link_stats(
    db: Session,
    track_link: TrackLink,
    include_users: bool,
    users_limit: int,
) -> dict:
    click_rows = db.execute(
        select(TrackLinkClick, User)
        .join(User, User.id == TrackLinkClick.user_id)
        .where(TrackLinkClick.link_id == track_link.id)
        .order_by(TrackLinkClick.clicked_at.desc())
    ).all()

    # "Клики" — это все события. "Покупки/конверсия" считаем по уникальным пользователям.
    seen_user_ids: set[int] = set()
    unique_click_rows: list[tuple[TrackLinkClick, User]] = []
    for click, user in click_rows:
        if user.id in seen_user_ids:
            continue
        seen_user_ids.add(user.id)
        unique_click_rows.append((click, user))

    user_ids = [user.id for _, user in unique_click_rows]
    subscriptions_by_user = _get_subscriptions_map(db, user_ids)

    buyers: list[dict] = []
    non_buyers: list[dict] = []
    for click, user in unique_click_rows:
        entry = _track_click_entry(click, user, subscriptions_by_user.get(user.id))
        if entry["has_subscription"]:
            buyers.append(entry)
        else:
            non_buyers.append(entry)

    total_clicks = len(click_rows)
    unique_users = len(unique_click_rows)
    converted = len(buyers)
    not_converted = len(non_buyers)
    conversion_rate = round((converted / unique_users) * 100, 2) if unique_users else 0.0

    item = {
        "id": track_link.id,
        "token": track_link.token,
        "unlimited_uses": True,
        "total_clicks": total_clicks,
        "unique_users": unique_users,
        "converted_subs": converted,
        "not_converted_subs": not_converted,
        "conversion_rate_percent": conversion_rate,
        "created_at": track_link.created_at.isoformat() if track_link.created_at else None,
    }

    if include_users:
        item.update({
            "buyers_total": len(buyers),
            "non_buyers_total": len(non_buyers),
            "users_limit": users_limit,
            "buyers": buyers[:users_limit],
            "non_buyers": non_buyers[:users_limit],
            "buyers_truncated": len(buyers) > users_limit,
            "non_buyers_truncated": len(non_buyers) > users_limit,
        })

    return item


def _generate_track_token(db: Session) -> str:
    while True:
        token = f"trk_{secrets.token_urlsafe(10)}"
        exists = db.execute(select(TrackLink.id).where(TrackLink.token == token)).scalar_one_or_none()
        if not exists:
            return token


@router.post("/generate")
def generate_promo(payload: GeneratePromoIn, db: Session = Depends(get_db)):
    tokens: list[str] = []
    for _ in range(payload.count):
        token_str = secrets.token_urlsafe(12)
        while token_str.startswith("trk_"):
            token_str = secrets.token_urlsafe(12)
        token = PromoToken(
            token=token_str,
            credits=payload.credits,
            max_uses=payload.max_uses,
            current_uses=0,
            is_used=False,
        )
        db.add(token)
        tokens.append(token_str)
    db.commit()
    return {
        "ok": True,
        "tokens": tokens,
        "count": len(tokens),
        "credits_per_token": payload.credits,
        "max_uses_per_token": payload.max_uses,
    }


@router.post("/use")
def use_promo(payload: UsePromoIn, db: Session = Depends(get_db)):
    token = db.execute(
        select(PromoToken)
        .where(PromoToken.token == payload.token)
        .with_for_update()
    ).scalar_one_or_none()
    if not token:
        raise HTTPException(404, "token_not_found")

    if token.current_uses >= token.max_uses:
        raise HTTPException(400, "token_fully_used")
    if token.is_used and token.max_uses <= 1:
        raise HTTPException(400, "token_already_used")

    user = _get_or_create_user(db, payload.chat_id)

    # Lock user row to reduce race conditions for "one user -> one promo forever".
    db.execute(select(User.id).where(User.id == user.id).with_for_update()).scalar_one()

    sub = db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    ).scalar_one_or_none()
    if sub:
        raise HTTPException(400, "already_had_subscription")

    legacy_used = db.execute(
        select(PromoToken).where(PromoToken.used_by_id == user.id)
    ).scalar_one_or_none()
    if legacy_used:
        raise HTTPException(400, "promo_already_used_by_user")

    new_used = db.execute(
        select(PromoUsage).where(PromoUsage.user_id == user.id)
    ).scalar_one_or_none()
    if new_used:
        raise HTTPException(400, "promo_already_used_by_user")

    credits = _get_or_create_credits(db, user.id)
    credits.image_credits = (credits.image_credits or 0) + token.credits

    token.current_uses += 1
    if token.current_uses >= token.max_uses:
        token.is_used = True

    usage = PromoUsage(token_id=token.id, user_id=user.id)
    db.add(usage)

    if token.max_uses == 1:
        token.used_by_id = user.id

    db.commit()
    return {
        "ok": True,
        "credits_added": token.credits,
        "token_current_uses": token.current_uses,
        "token_max_uses": token.max_uses,
        "token_remaining_uses": max(0, token.max_uses - token.current_uses),
    }


@router.get("/list")
def list_promos(
    limit: int = 50,
    offset: int = 0,
    include_users: bool = False,
    users_limit: int = 20,
    db: Session = Depends(get_db),
):
    limit = min(max(1, int(limit)), 200)
    offset = max(0, int(offset))
    users_limit = min(max(1, int(users_limit)), 100)

    tokens = db.execute(
        select(PromoToken)
        .order_by(PromoToken.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return [_token_stats(db, t, include_users=include_users, users_limit=users_limit) for t in tokens]


@router.get("/stats")
def global_stats(db: Session = Depends(get_db)):
    total_tokens = db.execute(select(func.count(PromoToken.id))).scalar() or 0
    total_usages = db.execute(select(func.count(PromoUsage.id))).scalar() or 0
    total_unique_users = db.execute(
        select(func.count(func.distinct(PromoUsage.user_id)))
    ).scalar() or 0

    promoted_users_query = select(PromoUsage.user_id).distinct()
    total_conversions = db.execute(
        select(func.count(func.distinct(Subscription.user_id)))
        .where(Subscription.user_id.in_(promoted_users_query))
    ).scalar() or 0

    total_without_subscription = max(0, total_unique_users - total_conversions)
    conversion_rate = round((total_conversions / total_unique_users) * 100, 2) if total_unique_users else 0.0

    total_credits_granted = db.execute(
        select(func.coalesce(func.sum(PromoToken.credits), 0))
        .select_from(PromoUsage)
        .join(PromoToken, PromoToken.id == PromoUsage.token_id)
    ).scalar() or 0

    return {
        # Backward-compatible keys
        "total_tokens_created": total_tokens,
        "total_redemptions": total_usages,
        "total_conversions_to_sub": total_conversions,
        # Extended stats
        "total_unique_users": total_unique_users,
        "total_without_subscription": total_without_subscription,
        "conversion_rate_percent": conversion_rate,
        "total_credits_granted": int(total_credits_granted),
    }


@router.post("/track/generate")
def generate_track_links(payload: GenerateTrackLinkIn, db: Session = Depends(get_db)):
    tokens: list[str] = []
    for _ in range(payload.count):
        token_str = _generate_track_token(db)
        db.add(TrackLink(token=token_str))
        tokens.append(token_str)
    db.commit()
    return {
        "ok": True,
        "tokens": tokens,
        "count": len(tokens),
        "unlimited_uses_per_link": True,
    }


@router.post("/track/click")
def register_track_click(payload: UseTrackLinkIn, db: Session = Depends(get_db)):
    track_link = db.execute(
        select(TrackLink)
        .where(TrackLink.token == payload.token)
        .with_for_update()
    ).scalar_one_or_none()
    if not track_link:
        raise HTTPException(404, "token_not_found")

    user = _get_or_create_user(db, payload.chat_id)
    db.add(TrackLinkClick(link_id=track_link.id, user_id=user.id))
    db.commit()

    return {"ok": True}


@router.get("/track/list")
def list_track_links(
    limit: int = 50,
    offset: int = 0,
    include_users: bool = False,
    users_limit: int = 20,
    db: Session = Depends(get_db),
):
    limit = min(max(1, int(limit)), 200)
    offset = max(0, int(offset))
    users_limit = min(max(1, int(users_limit)), 100)

    links = db.execute(
        select(TrackLink)
        .order_by(TrackLink.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return [_track_link_stats(db, t, include_users=include_users, users_limit=users_limit) for t in links]


@router.get("/track/stats")
def global_track_stats(db: Session = Depends(get_db)):
    total_links = db.execute(select(func.count(TrackLink.id))).scalar() or 0
    total_clicks = db.execute(select(func.count(TrackLinkClick.id))).scalar() or 0
    total_unique_users = db.execute(
        select(func.count(func.distinct(TrackLinkClick.user_id)))
    ).scalar() or 0

    tracked_users_query = select(TrackLinkClick.user_id).distinct()
    total_conversions = db.execute(
        select(func.count(func.distinct(Subscription.user_id)))
        .where(Subscription.user_id.in_(tracked_users_query))
    ).scalar() or 0

    total_without_subscription = max(0, total_unique_users - total_conversions)
    conversion_rate = round((total_conversions / total_unique_users) * 100, 2) if total_unique_users else 0.0

    return {
        "total_links_created": total_links,
        "total_clicks": total_clicks,
        "total_conversions_to_sub": total_conversions,
        "total_unique_users": total_unique_users,
        "total_without_subscription": total_without_subscription,
        "conversion_rate_percent": conversion_rate,
    }

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx

API_BASE = os.getenv("API_BASE", "http://api:8000").rstrip("/")
API_TIMEOUT = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)

# простой кэш, чтобы не долбить API на каждый клик
_CACHE: Dict[Tuple[int, str], Tuple[float, Any]] = {}
_CACHE_TTL_SEC = 20


def _cache_get(chat_id: int, key: str) -> Optional[Any]:
    v = _CACHE.get((chat_id, key))
    if not v:
        return None
    ts, data = v
    if time.time() - ts > _CACHE_TTL_SEC:
        _CACHE.pop((chat_id, key), None)
        return None
    return data


def _cache_set(chat_id: int, key: str, data: Any) -> None:
    _CACHE[(chat_id, key)] = (time.time(), data)


def cache_invalidate(chat_id: int) -> None:
    for k in list(_CACHE.keys()):
        if k[0] == chat_id:
            _CACHE.pop(k, None)


async def ensure_user(chat_id: int) -> Dict[str, Any]:
    """
    Гарантированно создаёт пользователя в БД (потому что /account/profile делает get_or_create).
    """
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.get(f"{API_BASE}/account/profile/{chat_id}")
    if r.status_code != 200:
        return {}
    data = r.json()
    _cache_set(chat_id, "profile", data)
    return data


async def get_profile(chat_id: int) -> Dict[str, Any]:
    cached = _cache_get(chat_id, "profile")
    if cached is not None:
        return cached
    return await ensure_user(chat_id)


async def get_sub_summary(chat_id: int) -> Dict[str, Any]:
    cached = _cache_get(chat_id, "sub_summary")
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.get(f"{API_BASE}/subscriptions/summary/{chat_id}")

    if r.status_code != 200:
        return {}

    data = r.json()
    _cache_set(chat_id, "sub_summary", data)
    return data


async def is_premium(chat_id: int) -> bool:
    s = await get_sub_summary(chat_id)
    role = (s.get("role") or "free").lower()
    return role != "free"


async def balance_topup(chat_id: int, amount_cents: int) -> bool:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            f"{API_BASE}/payments/balance/topup",
            json={"chat_id": chat_id, "amount": int(amount_cents)},
        )
    cache_invalidate(chat_id)
    return r.status_code == 200

async def set_plan(chat_id: int, plan: str) -> dict:
    if plan not in PLANS:
        return {"error": True, "detail": "unknown plan in bot"}

    price = PLANS[plan]

    # 1) topup
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r1 = await client.post(f"{API_BASE}/payments/balance/topup", json={"chat_id": chat_id, "amount": int(price)})
    if r1.status_code != 200:
        return {"error": True, "step": "topup", "status": r1.status_code, "detail": r1.text}

    # 2) set_plan
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r2 = await client.post(
            f"{API_BASE}/subscriptions/set_plan",
            json={"chat_id": chat_id, "plan": plan, "price_cents": int(price)},
        )
    if r2.status_code != 200:
        return {"error": True, "step": "set_plan", "status": r2.status_code, "detail": r2.text}

    return r2.json()

async def cancel_plan(chat_id: int) -> bool:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/subscriptions/cancel", json={"chat_id": chat_id})
    cache_invalidate(chat_id)
    return r.status_code == 200

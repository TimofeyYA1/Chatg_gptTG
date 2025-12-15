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


# -------------------- API wrappers --------------------

async def ensure_user(chat_id: int) -> Dict[str, Any]:
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


async def balance_topup(chat_id: int, amount_cents: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            f"{API_BASE}/payments/balance/topup",
            json={"chat_id": chat_id, "amount": int(amount_cents)},
        )
    cache_invalidate(chat_id)

    if r.status_code != 200:
        return {"error": True, "status": r.status_code, "detail": r.text}

    try:
        return r.json()
    except Exception:
        return {"ok": True}


# Paywall “как у них”
PAYWALL = {
    "week":  {"plan": "Week",  "stars": 300_00},
    "month": {"plan": "Month", "stars": 900_00},
    "year":  {"plan": "Year",  "stars": 4500_00},
}

# алиасы на всякий (для обратной совместимости)
_PLAN_ALIASES = {
    "Light": "Week",
    "Max": "Month",
    "Ultra": "Year",
    "week": "Week",
    "month": "Month",
    "year": "Year",
    "Week": "Week",
    "Month": "Month",
    "Year": "Year",
}


def _norm_plan(p: str) -> str:
    p = (p or "").strip()
    return _PLAN_ALIASES.get(p, p)


async def set_plan(chat_id: int, plan: str | None = None, period: str | None = None) -> Dict[str, Any]:
    """
    Совместимый метод (чтобы не ловить неожиданные keyword args):

      - set_plan(chat_id, period="week|month|year")
      - set_plan(chat_id, plan="Week|Month|Year")
      - set_plan(chat_id, plan="Light|Max|Ultra")  (алиасы)

    Реальная покупка без денег:
      1) докидываем ⭐ (topup)
      2) вызываем /subscriptions/set_plan

    ВАЖНО: price_cents НЕ передаём (API сама проверит цену).
    """
    # 1) определяем plan_name и stars
    if period:
        if period not in PAYWALL:
            return {"error": True, "detail": "unknown period"}
        plan_name = PAYWALL[period]["plan"]
        stars = PAYWALL[period]["stars"]
    else:
        plan_name = _norm_plan(plan or "")
        inv = {v["plan"]: v["stars"] for v in PAYWALL.values()}
        if plan_name not in inv:
            return {"error": True, "detail": "unknown plan"}
        stars = inv[plan_name]

    # 2) topup
    topup_res = await balance_topup(chat_id, stars)
    if topup_res.get("error"):
        return {"error": True, "step": "topup", **topup_res}

    # 3) set_plan
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r2 = await client.post(
            f"{API_BASE}/subscriptions/set_plan",
            json={"chat_id": chat_id, "plan": plan_name},
        )

    cache_invalidate(chat_id)

    if r2.status_code != 200:
        return {"error": True, "step": "set_plan", "status": r2.status_code, "detail": r2.text}

    try:
        return r2.json()
    except Exception:
        return {"ok": True, "plan": plan_name}


async def cancel_plan(chat_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/subscriptions/cancel", json={"chat_id": chat_id})

    cache_invalidate(chat_id)

    if r.status_code != 200:
        return {"error": True, "status": r.status_code, "detail": r.text}

    try:
        return r.json()
    except Exception:
        return {"ok": True}

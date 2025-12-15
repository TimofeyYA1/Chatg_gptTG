from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx

API_BASE = os.getenv("API_BASE", "http://api:8000").rstrip("/")
# Увеличим тайм-аут для генерации, так как картинки делаются долго (до 60 сек)
API_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)

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
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.get(f"{API_BASE}/subscriptions/summary/{chat_id}")

    if r.status_code != 200:
        return {}

    data = r.json()
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


# Paywall settings
PAYWALL = {
    "week":  {"plan": "Week",  "stars": 300_00},
    "month": {"plan": "Month", "stars": 900_00},
    "year":  {"plan": "Year",  "stars": 4500_00},
}

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
    if period:
        period_key = period.lower()
        if period_key not in PAYWALL:
            return {"error": True, "detail": "unknown period"}
        plan_name = PAYWALL[period_key]["plan"]
        stars = PAYWALL[period_key]["stars"]
    else:
        plan_name = _norm_plan(plan or "")
        inv = {v["plan"]: v["stars"] for v in PAYWALL.values()}
        if plan_name not in inv:
            return {"error": True, "detail": "unknown plan"}
        stars = inv[plan_name]

    topup_res = await balance_topup(chat_id, stars)
    if topup_res.get("error"):
        return {"error": True, "step": "topup", **topup_res}

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


# --- NEW: Image Generation/Editing ---

async def edit_image(chat_id: int, prompt: str, image_b64: str) -> Dict[str, Any]:
    """
    Отправляет запрос на редактирование/генерацию по фото.
    """
    payload = {
        "chat_id": chat_id,
        "prompt": prompt,
        "image_b64": image_b64,
        "size": "768x768" # Можно вынести в настройки
    }
    
    # Таймаут здесь нужен побольше, так как генерация тяжелая
    timeout = httpx.Timeout(connect=5.0, read=90.0, write=10.0, pool=5.0)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{API_BASE}/image/edit", json=payload)
        
    if r.status_code != 200:
        return {"ok": False, "error": r.text, "status": r.status_code}
        
    try:
        return r.json()
    except:
        return {"ok": False, "error": "invalid_json"}
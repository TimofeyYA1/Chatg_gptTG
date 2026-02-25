from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from common.config import settings

API_BASE = os.getenv("API_BASE", "http://api:8000").rstrip("/")
# Увеличиваем таймаут на чтение до 120 секунд, так как генерация может быть долгой
API_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)

_CACHE: Dict[Tuple[int, str], Tuple[float, Any]] = {}
_CACHE_TTL_SEC = 20


def _internal_headers() -> Dict[str, str]:
    token = (settings.INTERNAL_API_TOKEN or "").strip()
    return {"X-Internal-Token": token} if token else {}


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
        r = await client.get(f"{API_BASE}/account/profile/{chat_id}", headers=_internal_headers())
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
        r = await client.get(f"{API_BASE}/subscriptions/summary/{chat_id}", headers=_internal_headers())

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
            headers=_internal_headers(),
        )
    cache_invalidate(chat_id)

    if r.status_code != 200:
        return {"error": True, "status": r.status_code, "detail": r.text}

    try:
        return r.json()
    except Exception:
        return {"ok": True}

# telegram_bot/api_client.py


async def resume_plan(user_id: int) -> dict:
    """Возобновляет автопродление подписки"""
    # Адрес API внутри Docker-сети
    api_url = "http://api:8000" 
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{API_BASE}/subscriptions/resume",
                json={"chat_id": user_id},
                headers=_internal_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            return {"ok": False, "detail": f"Server error: {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "detail": str(e)}
        
async def buy_addon(chat_id: int, qty: int, price_cents: int) -> Dict[str, Any]:
    await balance_topup(chat_id, price_cents)
    
    payload = {
        "chat_id": chat_id,
        "qty": qty,
        "price_cents": price_cents
    }
    
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/payments/addons/buy", json=payload, headers=_internal_headers())
    
    if r.status_code != 200:
        return {"error": True, "detail": r.text, "status": r.status_code}
    
    try: return r.json()
    except: return {"ok": True}


async def set_plan(chat_id: int, plan: str | None = None, period: str | None = None) -> Dict[str, Any]:
    PAYWALL = {
        "week":  {"plan": "Week",  "stars": 300_00},
        "month": {"plan": "Month", "stars": 900_00},
        "year":  {"plan": "Year",  "stars": 4500_00},
    }
    
    if period:
        period_key = period.lower()
        if period_key not in PAYWALL:
            return {"error": True, "detail": "unknown period"}
        plan_name = PAYWALL[period_key]["plan"]
        stars = PAYWALL[period_key]["stars"]
    else:
        return {"error": True, "detail": "unknown plan"}

    topup_res = await balance_topup(chat_id, stars)
    if topup_res.get("error"):
        return {"error": True, "step": "topup", **topup_res}

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r2 = await client.post(
            f"{API_BASE}/subscriptions/set_plan",
            json={"chat_id": chat_id, "plan": plan_name},
            headers=_internal_headers(),
        )

    cache_invalidate(chat_id)

    if r2.status_code != 200:
        return {"error": True, "step": "set_plan", "status": r2.status_code, "detail": r2.text}

    try:
        return r2.json()
    except Exception:
        return {"ok": True, "plan": plan_name}


# --- Promo Tokens ---

async def generate_promo(count: int, credits: int = 50, max_uses: int = 1) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            f"{API_BASE}/promo/generate",
            json={"count": count, "credits": credits, "max_uses": max_uses},
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        return {"ok": False, "error": r.text}
    return r.json()


async def use_promo(chat_id: int, token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            f"{API_BASE}/promo/use",
            json={"chat_id": chat_id, "token": token},
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        try:
            return {"ok": False, "error": r.json().get("detail", "error"), "status": r.status_code}
        except:
            return {"ok": False, "error": r.text, "status": r.status_code}
    return r.json()


async def get_promo_list(
    limit: int = 50,
    offset: int = 0,
    include_users: bool = False,
    users_limit: int = 20,
) -> list:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        params = {
            "limit": limit,
            "offset": offset,
            "include_users": include_users,
            "users_limit": users_limit,
        }
        r = await client.get(
            f"{API_BASE}/promo/list",
            params=params,
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        return []
    return r.json()


async def get_promo_stats() -> dict:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.get(
            f"{API_BASE}/promo/stats",
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        return {}
    return r.json()


async def generate_track_links(count: int = 1) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            f"{API_BASE}/promo/track/generate",
            json={"count": count},
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        return {"ok": False, "error": r.text}
    return r.json()


async def register_track_click(chat_id: int, token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            f"{API_BASE}/promo/track/click",
            json={"chat_id": chat_id, "token": token},
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        try:
            return {"ok": False, "error": r.json().get("detail", "error"), "status": r.status_code}
        except Exception:
            return {"ok": False, "error": r.text, "status": r.status_code}
    return r.json()


async def get_track_links(
    limit: int = 50,
    offset: int = 0,
    include_users: bool = False,
    users_limit: int = 20,
) -> list:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        params = {
            "limit": limit,
            "offset": offset,
            "include_users": include_users,
            "users_limit": users_limit,
        }
        r = await client.get(
            f"{API_BASE}/promo/track/list",
            params=params,
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        return []
    return r.json()


async def get_track_stats() -> dict:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.get(
            f"{API_BASE}/promo/track/stats",
            headers=_internal_headers(),
        )
    if r.status_code != 200:
        return {}
    return r.json()



async def cancel_plan(chat_id: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(
            f"{API_BASE}/subscriptions/cancel",
            json={"chat_id": chat_id},
            headers=_internal_headers(),
        )

    cache_invalidate(chat_id)

    if r.status_code != 200:
        return {"error": True, "status": r.status_code, "detail": r.text}

    try:
        return r.json()
    except Exception:
        return {"ok": True}


async def admin_give_sub(chat_id: int, days: int, generations: int) -> Dict[str, Any]:
    payload = {"chat_id": chat_id, "days": days, "generations": generations}
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/subscriptions/admin_give", json=payload, headers=_internal_headers())
    
    cache_invalidate(chat_id)
    if r.status_code != 200:
        return {"ok": False, "error": r.text}
    return r.json()


async def admin_cancel_sub(chat_id: int) -> Dict[str, Any]:
    payload = {"chat_id": chat_id}
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        r = await client.post(f"{API_BASE}/subscriptions/admin_cancel", json=payload, headers=_internal_headers())
    
    cache_invalidate(chat_id)
    if r.status_code != 200:
        return {"ok": False, "error": r.text}
    return r.json()


# --- Image Generation/Editing ---

async def edit_image(chat_id: int, prompt: str, image_b64: str) -> Dict[str, Any]:
    payload = {
        "chat_id": chat_id,
        "prompt": prompt,
        "image_b64": image_b64,
        "size": "1536x1536"
    }
    # Используем увеличенный таймаут специально для генерации (должен быть больше TOTAL_TIMEOUT в API)
    timeout = httpx.Timeout(connect=10.0, read=500.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{API_BASE}/image/edit", json=payload, headers=_internal_headers())
    if r.status_code != 200:
        return {"ok": False, "error": r.text, "status": r.status_code}
    try: return r.json()
    except: return {"ok": False, "error": "invalid_json"}

async def generate_from_catalog(chat_id: int, image_b64: str, gender: str, editor_sel: dict, shoot_sel: dict) -> Dict[str, Any]:
    payload = {
        "chat_id": chat_id,
        "image_b64": image_b64,
        "gender": gender,
        "editor_sel": editor_sel,
        "shoot_sel": shoot_sel
    }
    # Используем увеличенный таймаут специально для генерации (должен быть больше TOTAL_TIMEOUT в API)
    timeout = httpx.Timeout(connect=10.0, read=500.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{API_BASE}/image/generate_from_catalog", json=payload, headers=_internal_headers())
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}", "detail": r.text}
    try: return r.json()
    except: return {"ok": False, "error": "invalid_json"}

# --- Export ---

async def export_stats(token: str) -> bytes | None:
    timeout = httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(
            f"{API_BASE}/usage/export_users_stats",
            params={"token": token},
            headers=_internal_headers(),
        )
    
    if r.status_code == 200:
        return r.content
    return None

# --- Catalog Info ---

async def get_catalog_page_info(gender: str, cat: str, page: int) -> int:
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            r = await client.get(
                f"{API_BASE}/image/catalog/info",
                params={"gender": gender, "cat": cat, "page": page},
                headers=_internal_headers(),
            )
        
        if r.status_code == 200:
            data = r.json()
            count = data.get("count", 0)
            return count if count > 0 else 9
            
    except Exception:
        pass
    
    return 9

# --- ВОТ ЭТОЙ ФУНКЦИИ НЕ ХВАТАЛО ---
async def get_catalog_titles(gender: str, selections: Dict[str, int]) -> Dict[str, str]:
    """Получает названия выбранных элементов (hair: 1 -> hair: "Боб")"""
    if not selections: return {}
    
    payload = {"gender": gender, "selections": selections}
    
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            r = await client.post(f"{API_BASE}/image/catalog/titles", json=payload, headers=_internal_headers())
        
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    
    return {}

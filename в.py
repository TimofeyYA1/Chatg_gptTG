# common/openai_balance.py
"""
Простой скрипт: получить текущий баланс OpenAI (кредиты).
Использует OPENAI_API_KEY из common.config.Settings.

Запуск из консоли:
    python -m common.openai_balance
"""

from __future__ import annotations

from typing import Any, Dict

import requests

from common.config import settings

API_BASE = "https://api.openai.com"


class OpenAIBalanceError(RuntimeError):
    pass


def _get_headers() -> Dict[str, str]:
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise OpenAIBalanceError("OPENAI_API_KEY пуст. Задай его в .env / переменных окружения.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def fetch_credit_grants(timeout: int = 30) -> Dict[str, Any]:
    """
    Основной эндпоинт для баланса кредитов:
      GET /v1/dashboard/billing/credit_grants

    Для некоторых аккаунтов может работать иначе или быть недоступен.
    В этом случае просто пробрасываем ошибку с текстом ответа.
    """
    try:
        resp = requests.get(
            f"{API_BASE}/v1/dashboard/billing/credit_grants",
            headers=_get_headers(),
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise OpenAIBalanceError(f"Сетевая ошибка: {e!r}") from e

    if resp.status_code != 200:
        # Показываем текст ошибки, чтобы было понятно, что не так
        raise OpenAIBalanceError(
            f"Ошибка {resp.status_code} при запросе /v1/dashboard/billing/credit_grants: {resp.text}"
        )

    try:
        return resp.json()
    except ValueError as e:
        raise OpenAIBalanceError(f"Не удалось распарсить JSON: {resp.text}") from e


def get_balance(timeout: int = 30) -> Dict[str, float]:
    """
    Вернуть баланс в виде словаря:
    {
        "total_granted": <float | None>,
        "total_used": <float | None>,
        "total_available": <float | None>,
    }

    Значения обычно в USD.
    """
    data = fetch_credit_grants(timeout=timeout)

    # В большинстве случаев структура:
    # {
    #   "object": "credit_summary",
    #   "total_granted": 5.0,
    #   "total_used": 1.23,
    #   "total_available": 3.77,
    #   "grants": {...}
    # }
    total_granted = data.get("total_granted")
    total_used = data.get("total_used")
    total_available = data.get("total_available")

    # Если по какой-то причине эти поля отсутствуют — просто вернём None.
    return {
        "total_granted": float(total_granted) if total_granted is not None else None,
        "total_used": float(total_used) if total_used is not None else None,
        "total_available": float(total_available) if total_available is not None else None,
    }


# ---------------- CLI ----------------

def main() -> None:
    """
    Запуск как скрипта:
        python -m common.openai_balance
    """
    try:
        balance = get_balance()
    except OpenAIBalanceError as e:
        print(f"[ERROR] {e}")
        return

    print("=== OpenAI balance (credits) ===")
    print(f"Total granted:   {balance['total_granted']}")
    print(f"Total used:      {balance['total_used']}")
    print(f"Total available: {balance['total_available']}")


if __name__ == "__main__":
    main()

from __future__ import annotations
from typing import List, Dict, Optional

from openai import OpenAI
from common.config import settings


class OpenAIProvider:
    """
    Тонкая обёртка над OpenAI с:
      • экономными пресетами (модель/температура/лимиты),
      • короткими и безопасными таймаутами,
      • надёжными фолбэками (никогда не «висим»).
    """

    def __init__(self) -> None:
        # Клиент создаём только если есть ключ.
        # ВАЖНО: задаём общий таймаут, чтобы API не подвисал.
        self.client: Optional[OpenAI] = (
            OpenAI(api_key=settings.OPENAI_API_KEY, timeout=10.0)
            if settings.OPENAI_API_KEY
            else None
        )

    def enabled(self) -> bool:
        return bool(self.client) and bool(settings.OPENAI_ENABLED)

    # ---------------- TEXT ----------------

    def chat_reply(self, history: List[Dict[str, str]], user_prompt: str) -> str:
        """
        history: [{'role':'user'|'assistant','content': '...'}, ...]
        Возвращает короткий текст-ответ (1–3 предложения).
        """
        text = (user_prompt or "").strip()
        if not text:
            return "🤖 Сообщение пустое."

        if not self.enabled():
            return f"🤖 (симуляция) Я получил: {text}"

        # Урезаем контекст (последние N сообщений).
        tail = history[-settings.OPENAI_CONTEXT_MESSAGES:] if history else []

        messages = (
            [
                {
                    "role": "system",
                    "content": (
                        "Отвечай кратко (1–3 предложения) и по делу. "
                        "Язык ответа = язык пользователя."
                    ),
                }
            ]
            + tail
            + [{"role": "user", "content": text}]
        )

        try:
            # Дешёвая модель по умолчанию задаётся в settings.OPENAI_MODEL_CHAT
            resp = self.client.chat.completions.create(
                model=settings.OPENAI_MODEL_CHAT,
                messages=messages,
                max_tokens=settings.OPENAI_MAX_OUTPUT_TOKENS,
                temperature=settings.OPENAI_TEMPERATURE,
            )
            out = (resp.choices[0].message.content or "").strip()
            return out or "🤖 (пустой ответ)"
        except Exception:
            # Никогда не падаем вверх по стеку — всегда отдаём фолбэк.
            return f"🤖 (сбой провайдера) Я получил: {text}"

    # ---------------- IMAGE ----------------

    def generate_image_b64(self, prompt: str, size: str = "512x512") -> str | None:
        """
        Генерация изображения (base64 PNG) через gpt-image-1.
        size: одно из '512x512' | '768x768' | '1024x1024' (меньше — дешевле).
        Возвращает base64 или None при ошибке/выключенном провайдере.
        """
        p = (prompt or "").strip()
        if not p or not self.enabled():
            return None

        # Нормализуем размер (на всякий случай).
        allowed = {"512x512", "768x768", "1024x1024"}
        sz = size if size in allowed else "512x512"

        try:
            img = self.client.images.generate(
                model=settings.OPENAI_MODEL_IMAGE,  # обычно "gpt-image-1"
                prompt=p,
                size=sz,
                response_format="b64_json",
                n=1,
            )
            return img.data[0].b64_json
        except Exception:
            return None

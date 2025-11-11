from __future__ import annotations
from typing import List, Dict, Optional

from openai import OpenAI
from common.config import settings


class OpenAIProvider:
    def __init__(self) -> None:
        # клиент создаём только если есть ключ
        self.client: Optional[OpenAI] = (
            OpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
        )

    def enabled(self) -> bool:
        return bool(self.client) and bool(settings.OPENAI_ENABLED)

    # ------- TEXT -------
    def chat_reply(self, history: List[Dict[str, str]], user_prompt: str) -> str:
        """
        history: [{'role':'user'|'assistant','content': '...'}, ...]
        """
        text = user_prompt.strip()
        if not text:
            return "🤖 Сообщение пустое."

        if not self.enabled():
            return f"🤖 (симуляция) Я получил: {text}"

        # урезаем контекст (последние N сообщений)
        tail = history[-settings.OPENAI_CONTEXT_MESSAGES:] if history else []

        messages = (
            [{"role": "system", "content": "Отвечай коротко (1–3 предложения), по делу."}]
            + tail
            + [{"role": "user", "content": text}]
        )

        try:
            resp = self.client.chat.completions.create(
                model=settings.OPENAI_MODEL_CHAT,   # дешёвый by default: gpt-4o-mini
                messages=messages,
                max_tokens=settings.OPENAI_MAX_OUTPUT_TOKENS,
                temperature=settings.OPENAI_TEMPERATURE,
            )
            return (resp.choices[0].message.content or "").strip() or "🤖 (пустой ответ)"
        except Exception:
            return f"🤖 (симуляция, ошибка провайдера) Я получил: {text}"

    # ------- IMAGE -------
    def generate_image_b64(self, prompt: str, size: str = "512x512") -> str | None:
        """
        Возвращает base64 PNG. Размеры: 512x512/768x768/1024x1024 — чем меньше, тем дешевле.
        """
        p = prompt.strip()
        if not self.enabled() or not p:
            return None
        try:
            img = self.client.images.generate(
                model=settings.OPENAI_MODEL_IMAGE,  # gpt-image-1
                prompt=p,
                size=size,
                response_format="b64_json",
                n=1,
            )
            return img.data[0].b64_json
        except Exception:
            return None

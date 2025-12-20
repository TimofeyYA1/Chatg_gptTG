from __future__ import annotations
from typing import List, Dict, Optional

import logging
import io
import base64
import time

from openai import OpenAI
from common.config import settings

logger = logging.getLogger(__name__)

# Импорт Google GenAI
try:
    from google import genai as _google_genai
    from google.genai import types
    from google.genai import errors as genai_errors
except Exception:
    _google_genai = None
    types = None
    genai_errors = None

# Импорт Pillow
try:
    from PIL import Image
except Exception:
    Image = None


class OpenAIProvider:
    def __init__(self) -> None:
        self.client: Optional[OpenAI] = (
            OpenAI(api_key=settings.OPENAI_API_KEY, timeout=10.0)
            if settings.OPENAI_API_KEY
            else None
        )

        self._nano_client = None
        if getattr(settings, "NANOBANANA_ENABLED", False) and settings.GEMINI_API_KEY:
            if _google_genai is None:
                logger.warning("NANOBANANA_ENABLED=True, но пакет google-genai не установлен.")
            else:
                try:
                    self._nano_client = _google_genai.Client(
                        api_key=settings.GEMINI_API_KEY
                    )
                    logger.info("NanoBanana (Gemini) клиент инициализирован.")
                except Exception:
                    logger.exception("Не удалось инициализировать Gemini client.")
                    self._nano_client = None

    def enabled(self) -> bool:
        return bool(self.client) and bool(settings.OPENAI_ENABLED)

    def _nano_enabled(self) -> bool:
        return bool(self._nano_client) and bool(
            getattr(settings, "NANOBANANA_ENABLED", False)
        )

    # ------------- TEXT -------------
    
    def _use_max_completion_tokens(self) -> bool:
        model = (settings.OPENAI_MODEL_CHAT or "").lower()
        markers = ("4.1", "gpt-5", "o3", "o4")
        return any(m in model for m in markers)

    def chat_reply(self, history: List[Dict[str, str]], user_prompt: str) -> str:
        text = (user_prompt or "").strip()
        if not text:
            return "🤖 Сообщение пустое."

        if not self.enabled():
            return f"🤖 (симуляция) Я получил: {text}"

        tail = history[-settings.OPENAI_CONTEXT_MESSAGES:] if history else []
        messages = ([{"role": "system", "content": "You are a helpful assistant."}] + tail + [{"role": "user", "content": text}])

        try:
            params: Dict = {
                "model": settings.OPENAI_MODEL_CHAT,
                "messages": messages,
                "temperature": settings.OPENAI_TEMPERATURE,
            }
            if self._use_max_completion_tokens():
                params["max_completion_tokens"] = settings.OPENAI_MAX_OUTPUT_TOKENS
            else:
                params["max_tokens"] = settings.OPENAI_MAX_OUTPUT_TOKENS

            resp = self.client.chat.completions.create(**params)
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            logger.exception("OpenAI chat_reply failed")
            return "🤖 Ошибка нейросети."

    # ------------- IMAGE -------------

    def _edit_image_with_nano(self, image_bytes: bytes, prompt: str) -> str | None:
        if not self._nano_enabled(): return None
        if Image is None: return None

        # Модели
        primary_model = getattr(settings, "NANOBANANA_MODEL_IMAGE", "gemini-2.0-flash-exp")
        fallback_model = getattr(settings, "NANOBANANA_MODEL_IMAGE_FALLBACK", "gemini-1.5-flash") # 1.5 flash часто более лояльна
        
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        max_retries = getattr(settings, "NANOBANANA_MAX_RETRIES", 2)

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return None

        # Конфиг безопасности для google-genai
        # Используем типы SDK если доступны, иначе dict
        safety_settings = [
            {'category': 'HARM_CATEGORY_HATE_SPEECH', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'},
        ]
        
        # Для нового SDK google-genai v1.0
        config = {'safety_settings': safety_settings}

        for model_name in models_to_try:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"🎨 GenAI ({model_name}) attempt {attempt}...")
                    
                    response = self._nano_client.models.generate_content(
                        model=model_name,
                        contents=[prompt, img],
                        config=config
                    )

                    # 1. Проверяем наличие картинки (inline_data)
                    if hasattr(response, 'candidates') and response.candidates:
                        for part in response.candidates[0].content.parts:
                            if part.inline_data and part.inline_data.data:
                                # УСПЕХ
                                raw = part.inline_data.data
                                if isinstance(raw, str): raw = base64.b64decode(raw)
                                out_img = Image.open(io.BytesIO(raw))
                                buf = io.BytesIO()
                                out_img.save(buf, format="PNG")
                                return base64.b64encode(buf.getvalue()).decode("utf-8")
                            
                            # Если картинки нет, но есть текст (отказ)
                            if part.text:
                                logger.warning(f"⚠️ Model refused with text: {part.text[:100]}...")

                    logger.warning(f"⚠️ Пустой ответ от {model_name} (Safety filter?)")
                    time.sleep(1)

                except Exception as e:
                    # Ловим 429 и Safety errors
                    err_str = str(e)
                    if "429" in err_str or "Resource exhausted" in err_str:
                        logger.warning(f"🚫 Лимиты {model_name}. Break.")
                        break # Сразу к следующей модели
                    logger.warning(f"⚠️ Error {model_name}: {err_str}")
                    time.sleep(1)
            
            # Если цикл попыток кончился, идем к следующей модели
            
        return None

    def edit_image_b64(self, image_bytes: bytes, prompt: str, size: str = "1024x1024") -> str | None:
        p = (prompt or "").strip()
        if not p or not image_bytes: return None
        return self._edit_image_with_nano(image_bytes, p)
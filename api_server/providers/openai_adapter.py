from __future__ import annotations
from typing import List, Dict, Optional, Any

import logging
import io
import base64
import time
import os

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

    def _edit_image_with_nano(self, image_bytes: bytes, prompt: str, is_pro: bool = False) -> Dict[str, Any]:
        """
        Возвращает словарь:
        {
            "b64": str | None,
            "reason": str | None  # код ошибки (safety_filter, api_error и т.д.)
        }
        """
        if not self._nano_enabled(): 
            return {"b64": None, "reason": "provider_disabled"}
        if Image is None: 
            return {"b64": None, "reason": "pillow_missing"}

        # --- МОДЕЛИ ИЗ КОНФИГА ---
        # PRIMARY (она же PRO) -> gemini-3-pro-image-preview
        primary_model = os.getenv("NANOBANANA_MODEL_IMAGE") or getattr(settings, "NANOBANANA_MODEL_IMAGE", "gemini-3-pro-image-preview")
        # FALLBACK (она же STANDARD) -> gemini-2.0-flash-exp
        fallback_model = os.getenv("NANOBANANA_MODEL_IMAGE_FALLBACK") or getattr(settings, "NANOBANANA_MODEL_IMAGE_FALLBACK", "gemini-2.0-flash-exp")
        
        models_to_try = []

        if is_pro:
            # Юзер PRO: Сначала Primary (Pro), затем Fallback (Std)
            models_to_try.append(primary_model)
            if fallback_model != primary_model:
                models_to_try.append(fallback_model)
        else:
            # Юзер ОБЫЧНЫЙ: Только Fallback (Std)
            models_to_try.append(fallback_model)

        max_retries = getattr(settings, "NANOBANANA_MAX_RETRIES", 2)

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return {"b64": None, "reason": "invalid_image_file"}

        # Конфиг безопасности
        safety_settings = [
            {'category': 'HARM_CATEGORY_HATE_SPEECH', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'},
        ]
        
        config = {'safety_settings': safety_settings}
        
        last_error = "unknown_error"

        for model_name in models_to_try:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"🎨 GenAI Attempt ({model_name}). User Pro: {is_pro}. Attempt {attempt}...")
                    
                    response = self._nano_client.models.generate_content(
                        model=model_name,
                        contents=[prompt, img],
                        config=config
                    )

                    if not response.candidates:
                        logger.warning(f"⚠️ Пустой ответ от {model_name} (Safety filter?)")
                        last_error = "safety_filter"
                        break 

                    candidate = response.candidates[0]

                    if not candidate.content or not candidate.content.parts:
                        finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                        logger.warning(f"⚠️ Модель {model_name} вернула кандидата без контента. FinishReason: {finish_reason}")
                        
                        if str(finish_reason) in ["SAFETY", "BLOCK_LOW_AND_ABOVE", "BLOCK_MEDIUM_AND_ABOVE"]:
                            last_error = "safety_filter"
                        else:
                            last_error = "model_refusal"
                        
                        time.sleep(1)
                        continue

                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            raw = part.inline_data.data
                            if isinstance(raw, str): raw = base64.b64decode(raw)
                            out_img = Image.open(io.BytesIO(raw))
                            buf = io.BytesIO()
                            out_img.save(buf, format="JPEG", quality=90)
                            return {"b64": base64.b64encode(buf.getvalue()).decode("utf-8"), "reason": None}
                        
                        if part.text:
                            logger.warning(f"⚠️ Model refused with text: {part.text[:100]}...")
                            last_error = "model_refusal"

                    logger.warning(f"⚠️ Нет данных изображения от {model_name}")
                    time.sleep(1)

                except Exception as e:
                    err_str = str(e)
                    if "404" in err_str and "NOT_FOUND" in err_str:
                        logger.error(f"❌ Модель {model_name} не найдена (404). Проверь название в .env")
                        last_error = "model_not_found"
                        break 
                    
                    if "429" in err_str or "Resource exhausted" in err_str:
                        logger.warning(f"🚫 Лимиты {model_name}. Break.")
                        last_error = "limit_exceeded"
                        break 
                        
                    logger.warning(f"⚠️ Error {model_name}: {err_str}")
                    last_error = "api_error"
                    time.sleep(1)
            
        return {"b64": None, "reason": last_error}

    def edit_image_b64(self, image_bytes: bytes, prompt: str, size: str = "1024x1024", is_pro: bool = False) -> Dict[str, Any]:
        """
        Публичный метод.
        """
        p = (prompt or "").strip()
        if not p or not image_bytes: 
            return {"b64": None, "reason": "empty_input"}
        
        if self._nano_enabled():
            # Передаем is_pro в приватный метод
            return self._edit_image_with_nano(image_bytes, p, is_pro=is_pro)
        
        return {"b64": None, "reason": "no_provider_enabled"}
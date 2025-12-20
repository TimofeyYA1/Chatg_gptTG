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
    from google.genai import errors as genai_errors
except Exception:
    _google_genai = None
    genai_errors = None

# Импорт Pillow
try:
    from PIL import Image
except Exception:
    Image = None


class OpenAIProvider:
    """
    Обёртка над:
      • OpenAI (для текста),
      • NanoBanana (Gemini) для РЕДАКТИРОВАНИЯ картинок с поддержкой Fallback.
    """

    def __init__(self) -> None:
        # --- OpenAI клиент для текста ---
        self.client: Optional[OpenAI] = (
            OpenAI(api_key=settings.OPENAI_API_KEY, timeout=10.0)
            if settings.OPENAI_API_KEY
            else None
        )

        # --- Gemini / NanoBanana клиент для изображений ---
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
            raw_content = resp.choices[0].message.content
            out = (raw_content or "").strip()

            if not out:
                return "🤖 (пустой ответ провайдера)"
            return out

        except Exception as e:
            logger.exception("OpenAI chat_reply failed")
            return f"🤖 (сбой провайдера) Я получил: {text}"

    # ------------- IMAGE: NanoBanana / Gemini (EDIT ONLY) -------------

    def _edit_image_with_nano(self, image_bytes: bytes, prompt: str) -> str | None:
        """
        Редактирование с поддержкой Fallback моделей.
        1. Пробуем Primary модель (из .env).
        2. Если ошибка/лимиты — пробуем Fallback модель.
        """
        if not self._nano_enabled():
            return None

        if Image is None:
            logger.error("Pillow не установлен.")
            return None

        # --- Сборка списка моделей ---
        # 1. Основная (например, gemini-1.5-pro)
        primary_model = getattr(settings, "NANOBANANA_MODEL_IMAGE", "gemini-2.0-flash-exp")
        
        # 2. Запасная (например, gemini-1.5-flash) - берем из .env или дефолт
        fallback_model = getattr(settings, "NANOBANANA_MODEL_IMAGE_FALLBACK", "gemini-2.0-flash-exp")
        
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        max_retries_per_model = getattr(settings, "NANOBANANA_MAX_RETRIES", 3)

        # Открываем изображение один раз
        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            logger.exception("Не удалось открыть изображение Pillow")
            return None

        for model_name in models_to_try:
            logger.info(f"🎨 Пробую генерацию через модель: {model_name}")
            
            # Цикл ретраев для ТЕКУЩЕЙ модели
            for attempt in range(1, max_retries_per_model + 1):
                try:
                    response = self._nano_client.models.generate_content(
                        model=model_name,
                        contents=[prompt, img],
                    )

                    # Проверка ответа
                    parts = getattr(response, "parts", None)
                    if not parts and getattr(response, "candidates", None):
                        try:
                            parts = response.candidates[0].content.parts
                        except Exception:
                            parts = None

                    if not parts:
                        logger.warning(f"Модель {model_name} вернула пустой ответ (Safety?), попытка {attempt}")
                        time.sleep(1)
                        continue

                    # Ищем картинку в ответе
                    for part in parts:
                        inline = getattr(part, "inline_data", None)
                        if inline and inline.data:
                            # УСПЕХ!
                            if isinstance(inline.data, (bytes, bytearray)):
                                raw = inline.data
                            elif isinstance(inline.data, str):
                                raw = base64.b64decode(inline.data)
                            else:
                                continue
                            
                            # Конвертируем в PNG base64
                            out_img = Image.open(io.BytesIO(raw))
                            buf = io.BytesIO()
                            out_img.save(buf, format="PNG")
                            logger.info(f"✅ Успех на модели {model_name}")
                            return base64.b64encode(buf.getvalue()).decode("utf-8")

                    # Если parts были, но картинки внутри нет
                    logger.warning(f"Модель {model_name}: нет картинки в ответе, попытка {attempt}")
                    time.sleep(1)

                except Exception as e:
                    # Логируем ошибку
                    is_server_error = (genai_errors and isinstance(e, genai_errors.ServerError))
                    
                    if is_server_error:
                        logger.warning(f"⚠️ Ошибка сервера {model_name} (500/503): {e}")
                    else:
                        # Если ошибка 429 (Resource Exhausted) или 400 - это часто фатально для текущей модели
                        if "429" in str(e) or "Resource exhausted" in str(e):
                            logger.warning(f"🚫 Лимиты исчерпаны для {model_name}. Переход к следующей модели.")
                            break # Выход из цикла ретраев, переход к следующей модели
                        
                        logger.warning(f"⚠️ Ошибка генерации {model_name} (попытка {attempt}): {e}")

                    if attempt < max_retries_per_model:
                        time.sleep(2)
            
            # Если дошли сюда — значит эта модель не справилась за все попытки.
            # Цикл for перейдет к следующей модели в списке.
            logger.warning(f"❌ Модель {model_name} не справилась. Пробую следующую (если есть)...")

        logger.error("☠️ Все модели не смогли сгенерировать изображение.")
        return None

    # ------------- IMAGE: публичные методы -------------

    def edit_image_b64(
        self, image_bytes: bytes, prompt: str, size: str = "1024x1024"
    ) -> str | None:
        p = (prompt or "").strip()
        if not p or not image_bytes:
            return None

        b64 = self._edit_image_with_nano(image_bytes, p)
        if not b64:
            logger.warning("NanoBanana edit_image_b64 вернул None")
        return b64
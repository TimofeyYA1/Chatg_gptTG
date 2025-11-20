from __future__ import annotations
from typing import List, Dict, Optional

import logging
import io
import base64
import time  # для бэкоффа при ретраях

from openai import OpenAI
from common.config import settings

logger = logging.getLogger(__name__)

# Пытаемся импортировать Google GenAI (Gemini / Nano Banana)
try:
    from google import genai as _google_genai  # type: ignore[import-not-found]
    from google.genai import errors as genai_errors  # type: ignore[import-not-found]
except Exception:
    _google_genai = None
    genai_errors = None  # type: ignore[assignment]

try:
    from google.genai import errors as _google_genai_errors  # type: ignore[import-not-found]
except Exception:
    _google_genai_errors = None

# Пытаемся импортировать Pillow (для работы с изображениями)
try:
    from PIL import Image  # type: ignore[import-not-found]
except Exception:
    Image = None  # type: ignore[assignment]


class OpenAIProvider:
    """
    Обёртка над:
      • OpenAI (для текста),
      • NanoBanana (Gemini 2.5 Flash Image) для РЕДАКТИРОВАНИЯ картинок (если включено в конфиге).
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
                logger.warning(
                    "NANOBANANA_ENABLED=True, но пакет google-genai не установлен. "
                    "Функции работы с изображениями будут недоступны."
                )
            else:
                try:
                    self._nano_client = _google_genai.Client(
                        api_key=settings.GEMINI_API_KEY
                    )
                    logger.info(
                        "NanoBanana (Gemini 2.5 Flash Image) клиент инициализирован."
                    )
                except Exception:
                    logger.exception(
                        "Не удалось инициализировать Gemini client. "
                        "Функции работы с изображениями будут недоступны."
                    )
                    self._nano_client = None

    # ----------------- общие флаги -----------------

    def enabled(self) -> bool:
        """Включен ли текстовый провайдер (OpenAI)."""
        return bool(self.client) and bool(settings.OPENAI_ENABLED)

    def _nano_enabled(self) -> bool:
        """
        Включен ли NanoBanana (через Gemini API) для картинок.
        """
        return bool(self._nano_client) and bool(
            getattr(settings, "NANOBANANA_ENABLED", False)
        )

    # ------------- TEXT -------------

    def _use_max_completion_tokens(self) -> bool:
        """
        Новые модели (4.1 / 5 / o3 / o4 и т.п.) требуют max_completion_tokens
        вместо max_tokens. Определяем по имени модели из конфига.
        """
        model = (settings.OPENAI_MODEL_CHAT or "").lower()
        markers = ("4.1", "gpt-5", "o3", "o4")
        return any(m in model for m in markers)

    def chat_reply(self, history: List[Dict[str, str]], user_prompt: str) -> str:
        """
        history: [{'role':'user'|'assistant','content': '...'}, ...]
        """
        text = (user_prompt or "").strip()
        if not text:
            return "🤖 Сообщение пустое."

        if not self.enabled():
            return f"🤖 (симуляция) Я получил: {text}"

        # урезаем контекст
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

            # для старых моделей — max_tokens, для новых — max_completion_tokens
            if self._use_max_completion_tokens():
                params["max_completion_tokens"] = settings.OPENAI_MAX_OUTPUT_TOKENS
            else:
                params["max_tokens"] = settings.OPENAI_MAX_OUTPUT_TOKENS

            resp = self.client.chat.completions.create(**params)  # type: ignore[arg-type]

            raw_content = resp.choices[0].message.content
            out = (raw_content or "").strip()

            if not out:
                logger.warning(
                    "OpenAI returned EMPTY content\n"
                    "  model: %s\n"
                    "  params: %r\n"
                    "  raw_choice: %r\n"
                    "  raw_response: %r",
                    settings.OPENAI_MODEL_CHAT,
                    params,
                    resp.choices[0],
                    resp,
                )
                return "🤖 (пустой ответ провайдера)"

            return out

        except Exception as e:
            logger.exception(
                "OpenAI chat_reply failed: model=%s, text_snippet=%r, error=%r",
                settings.OPENAI_MODEL_CHAT,
                text[:200],
                e,
            )
            return f"🤖 (сбой провайдера) Я получил: {text}"

    # ------------- IMAGE: NanoBanana / Gemini (EDIT ONLY) -------------

    def _edit_image_with_nano(self, image_bytes: bytes, prompt: str) -> str | None:
        """
        Внутренний метод редактирования изображения через NanoBanana
        с агрессивными ретраями при временных ошибках / пустых parts / пустом inline_data.
        Возвращает base64 PNG или None.
        """
        if not self._nano_enabled():
            logger.warning("NanoBanana не настроен или выключен, edit_image недоступен.")
            return None

        if Image is None:
            logger.warning(
                "Pillow (PIL) не установлен, не могу использовать NanoBanana. "
                "Установи пакет 'Pillow' или выключи NANOBANANA_ENABLED."
            )
            return None

        # сколько раз пробуем в сумме
        # по умолчанию: 5 попыток:
        #  1–2: без задержки
        #  3: после неё задержка 1 сек
        #  4–5: перед следующей попыткой задержка 2 сек
        max_retries = getattr(settings, "NANOBANANA_MAX_RETRIES", 5)
        last_exc: Optional[Exception] = None

        def _sleep_before_retry(attempt: int) -> None:
            """Логика пауз между попытками."""
            # если следующей попытки уже не будет — не спим
            if attempt >= max_retries:
                return
            # первые две попытки — без задержки
            if attempt <= 2:
                return
            # третья — 1 сек, дальше — 2 сек
            delay = 1 if attempt == 3 else 2
            try:
                time.sleep(delay)
            except Exception:
                pass

        for attempt in range(1, max_retries + 1):
            try:
                img = Image.open(io.BytesIO(image_bytes))

                model_name = (
                    settings.NANOBANANA_MODEL_IMAGE
                    if getattr(settings, "NANOBANANA_MODEL_IMAGE", None)
                    else "gemini-2.5-flash-image"
                )

                response = self._nano_client.models.generate_content(  # type: ignore[union-attr]
                    model=model_name,
                    contents=[prompt, img],
                )

                parts = getattr(response, "parts", None)
                if not parts and getattr(response, "candidates", None):
                    try:
                        parts = response.candidates[0].content.parts  # type: ignore[index]
                    except Exception:
                        parts = None

                if not parts:
                    # Частый кейс: IMAGE_SAFETY / SAFETY → пустые parts
                    last_exc = RuntimeError(
                        f"NanoBanana edit_image: empty parts (possibly safety/moderation), attempt={attempt}"
                    )
                    logger.warning(
                        "NanoBanana (Gemini) не вернул parts в ответе, model=%s, attempt=%s/%s",
                        model_name,
                        attempt,
                        max_retries,
                    )
                    _sleep_before_retry(attempt)
                    continue

                got_image = False

                for part in parts:
                    inline = getattr(part, "inline_data", None)
                    if inline is None:
                        continue

                    data = getattr(inline, "data", None)
                    if not data:
                        continue

                    if isinstance(data, (bytes, bytearray)):
                        raw = data
                    elif isinstance(data, str):
                        try:
                            raw = base64.b64decode(data)
                        except Exception:
                            logger.warning(
                                "NanoBanana: не удалось декодировать base64 inline_data (attempt=%s)",
                                attempt,
                            )
                            continue
                    else:
                        continue

                    try:
                        out_img = Image.open(io.BytesIO(raw))
                    except Exception:
                        logger.exception(
                            "NanoBanana: не удалось распознать изображение из inline_data (attempt=%s)",
                            attempt,
                        )
                        continue

                    buf = io.BytesIO()
                    out_img.save(buf, format="PNG")
                    got_image = True
                    return base64.b64encode(buf.getvalue()).decode("utf-8")

                if not got_image:
                    last_exc = RuntimeError(
                        f"NanoBanana edit_image: no valid inline_data, attempt={attempt}"
                    )
                    logger.warning(
                        "NanoBanana (Gemini) не найдено корректного inline_data в parts, model=%s, attempt=%s/%s",
                        model_name,
                        attempt,
                        max_retries,
                    )
                    _sleep_before_retry(attempt)
                    continue

            except Exception as e:
                last_exc = e
                # Пытаемся понять, это именно временная ошибка сервера или что-то фатальное
                is_server_error = (
                    genai_errors is not None
                    and isinstance(e, genai_errors.ServerError)  # type: ignore[attr-defined]
                )

                code = None
                if is_server_error:
                    resp = getattr(e, "response", None)
                    if isinstance(resp, dict):
                        code = resp.get("error", {}).get("code")

                if is_server_error and code in (500, 503):
                    logger.error(
                        "NanoBanana edit_image_with_nano временная ошибка (code=%s, attempt=%s/%s)",
                        code,
                        attempt,
                        max_retries,
                    )
                else:
                    logger.exception(
                        "NanoBanana edit_image_with_nano failed (attempt=%s/%s)",
                        attempt,
                        max_retries,
                    )

                _sleep_before_retry(attempt)
                continue

        if last_exc:
            logger.error(
                "NanoBanana edit_image_with_nano exhausted retries, last_error=%r",
                last_exc,
            )
        return None

    # ------------- IMAGE: публичные методы (EDIT ONLY) -------------

    def edit_image_b64(
        self, image_bytes: bytes, prompt: str, size: str = "1024x1024"
    ) -> str | None:
        """
        Редактирование изображения ТОЛЬКО через NanoBanana.
        Генерации с нуля здесь больше нет.

        Если NanoBanana недоступен или после всех ретраев не получилось —
        возвращаем None, чтобы верхний уровень отдал заглушку / stub.
        """
        p = (prompt or "").strip()
        if not p or not image_bytes:
            return None

        b64 = self._edit_image_with_nano(image_bytes, p)
        if not b64:
            logger.warning(
                "NanoBanana edit_image_b64 вернул None (prompt=%r)", p[:200]
            )
        return b64

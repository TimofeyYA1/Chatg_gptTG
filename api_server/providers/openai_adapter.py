from __future__ import annotations
from typing import List, Dict, Optional, Any

import logging
import io
import base64
import time
import os
import re

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
                        api_key=settings.GEMINI_API_KEY,
                        http_options={'timeout': 180000} # 180,000 ms = 180 seconds (3 minutes)
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

    def nano_chat_reply(self, system_prompt: str, user_prompt: str, model_name: str = None) -> str:
        """
        Текстовый ответ через Gemini (NanoBanana).
        """
        if not self._nano_enabled():
            return "🤖 Gemini provider disabled."
        
        # Список моделей для попыток (если первая перегружена)
        primary_model = model_name or os.getenv("NANOBANANA_MODEL_CHAT") or "gemini-2.5-pro"
        fallback_model = getattr(settings, "NANOBANANA_MODEL_IMAGE_FALLBACK", "gemini-2.0-flash-exp")
        
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        logger.info(f"🤖 Translation models to try: {models_to_try}")

        last_error = ""
        for current_model in models_to_try:
            try:
                logger.info(f"🤖 Gemini chat_reply attempt with model: {current_model}")
                response = self._nano_client.models.generate_content(
                    model=current_model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.1,
                    )
                )
                return response.text.strip()
            except Exception as e:
                last_error = str(e)
                if "503" in last_error or "high demand" in last_error.lower() or "UNAVAILABLE" in last_error:
                    if len(models_to_try) > 1 and current_model == models_to_try[0]:
                        logger.warning(f"🔥 Модель {current_model} перегружена. Срочный переход на {models_to_try[1]} для перевода промпта. Причина: {last_error}")
                        continue
                
                logger.error(f"❌ Ошибка перевода на модели {current_model}: {e}")
                if len(models_to_try) > 1 and current_model == models_to_try[0]:
                    continue
                break
        
        return f"Error: {last_error}"

    # ------------- IMAGE -------------

    @staticmethod
    def _normalize_ratio(width: str, height: str) -> str:
        return f"{int(width)}:{int(height)}"

    def _closest_supported_ratio(self, width: int, height: int) -> str:
        supported_ratios = (
            "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"
        )
        if width <= 0 or height <= 0:
            return "1:1"

        source_ratio = width / height
        best_ratio = "1:1"
        best_delta = float("inf")
        for ratio in supported_ratios:
            parsed = self._parse_ratio(ratio)
            if not parsed:
                continue
            rw, rh = parsed
            delta = abs(source_ratio - (rw / rh))
            if delta < best_delta:
                best_delta = delta
                best_ratio = ratio
        return best_ratio

    def _detect_aspect_ratio(self, prompt: str, default_ratio: str = "9:16") -> str:
        supported_ratios = {
            "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"
        }

        text = (prompt or "").lower()

        # Explicit numeric formats, e.g. 16:9, 16x9, 16/9, 16 на 9, 16 to 9
        explicit_patterns = [
            r"\b(\d{1,2})\s*:\s*(\d{1,2})\b",
            r"\b(\d{1,2})\s*[xх×]\s*(\d{1,2})\b",
            r"\b(\d{1,2})\s*/\s*(\d{1,2})\b",
            r"\b(\d{1,2})\s*на\s*(\d{1,2})\b",
            r"\b(\d{1,2})\s*to\s*(\d{1,2})\b",
        ]

        for pattern in explicit_patterns:
            m = re.search(pattern, text)
            if not m:
                continue
            ratio = self._normalize_ratio(m.group(1), m.group(2))
            if ratio in supported_ratios:
                logger.info(f"📐 Detected explicit aspect ratio in prompt: {ratio}")
                return ratio
            logger.warning(f"⚠️ Detected ratio {ratio} is not supported. Falling back to {default_ratio}")
            return default_ratio

        # Keyword fallback (EN + RU). Keep this strict to avoid false positives
        # from prompts like "family portrait", which should not force 9:16.
        if any(word in text for word in ("horizontal", "landscape", "wide", "горизонт", "альбом")):
            return "16:9"
        if any(word in text for word in ("square", "квадрат")):
            return "1:1"

        vertical_patterns = (
            r"\bvertical\b",
            r"\bvertical\s+orientation\b",
            r"\bportrait\s+orientation\b",
            r"вертикальн",
            r"портретн\w*\s+ориентац",
        )
        if any(re.search(pattern, text) for pattern in vertical_patterns):
            return "9:16"

        logger.info(f"📐 No aspect ratio detected, using default: {default_ratio}")
        return default_ratio

    @staticmethod
    def _parse_ratio(ratio: str) -> tuple[int, int] | None:
        try:
            w, h = (ratio or "").split(":")
            wi, hi = int(w), int(h)
            if wi <= 0 or hi <= 0:
                return None
            return wi, hi
        except Exception:
            return None

    def _enforce_aspect_ratio(self, img: "Image.Image", ratio: str) -> "Image.Image":
        parsed = self._parse_ratio(ratio)
        if not parsed:
            return img

        target_w, target_h = parsed
        width, height = img.size
        if width <= 0 or height <= 0:
            return img

        current = width / height
        target = target_w / target_h
        if abs(current - target) < 0.01:
            return img

        if current > target:
            # Too wide -> crop width.
            new_width = max(1, min(width, int(round(height * target))))
            left = max(0, (width - new_width) // 2)
            right = left + new_width
            fixed = img.crop((left, 0, right, height))
        else:
            # Too tall -> crop height.
            new_height = max(1, min(height, int(round(width / target))))
            top = max(0, (height - new_height) // 2)
            bottom = top + new_height
            fixed = img.crop((0, top, width, bottom))

        logger.warning(
            f"⚠️ Output aspect ratio corrected from {width}:{height} to {fixed.size[0]}:{fixed.size[1]} "
            f"(target {ratio})"
        )
        return fixed

    def _image_config_for_model(self, model_name: str, aspect_ratio: str) -> Any:
        model_l = (model_name or "").lower()
        max_size = "4K" if "pro-image" in model_l else None

        # Flash image models have fixed native max resolution (~1K), so only ratio is configurable.
        if max_size:
            logger.info(f"[image] model={model_name} image_size={max_size} (max)")
        else:
            logger.info(f"[image] model={model_name} uses native max resolution (aspect_ratio={aspect_ratio})")

        if types is None or not hasattr(types, "ImageConfig") or not hasattr(types, "GenerateContentConfig"):
            logger.warning("[image] SDK has no ImageConfig support; using provider defaults")
            return None

        cfg_fields = getattr(types.GenerateContentConfig, "model_fields", {}) or {}
        if "image_config" not in cfg_fields:
            logger.warning("[image] SDK GenerateContentConfig has no image_config field; using provider defaults")
            return None

        try:
            if max_size:
                return types.ImageConfig(aspect_ratio=aspect_ratio, image_size=max_size)
            return types.ImageConfig(aspect_ratio=aspect_ratio)
        except Exception as e:
            logger.warning(f"[image] failed to build ImageConfig for {model_name}: {e}")
            return None

    def _edit_image_with_nano(self, image_bytes: bytes, prompt: str, is_pro: bool = False) -> Dict[str, Any]:
        if not self._nano_enabled(): return {"b64": None, "reason": "provider_disabled"}
        if Image is None: return {"b64": None, "reason": "pillow_missing"}

        # --- ЖЕСТКОЕ ФОРМИРОВАНИЕ СПИСКА МОДЕЛЕЙ ---
        # Берем из настроек, если пусто - используем дефолты
        m_pro = str(getattr(settings, "NANOBANANA_MODEL_IMAGE", "") or "gemini-3-pro-image-preview").strip()
        m_flash = str(getattr(settings, "NANOBANANA_MODEL_IMAGE_FALLBACK", "") or "gemini-2.5-flash-image").strip()
        
        if not m_pro: m_pro = "gemini-3-pro-image-preview"
        if not m_flash: m_flash = "gemini-2.5-flash-image"
        
        selected_model = m_pro if is_pro else m_flash
        if not selected_model:
            selected_model = "gemini-3-pro-image-preview" if is_pro else "gemini-2.5-flash-image"

        models_to_try = [selected_model]
        logger.info(f"[image] selected model (Pro={is_pro}): {selected_model}")

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            logger.error("❌ Ошибка: Не удалось открыть изображение через PIL")
            return {"b64": None, "reason": "invalid_image_file"}

        # Системная инструкция для стабильности сохранения лица
        # Мы переносим это сюда из роутера, чтобы модель видела это как системное правило
        system_instruction = (
            "You are a professional high-fidelity image editor. "
            "CRITICAL REQUIREMENT: You MUST preserve the exact facial identity, structure, and features of the person from the source image. "
            "The output image must look exactly like the same person. Do not change eyes, nose, mouth, or jawline. "
            "Keep the skin tone consistent. High fidelity face swap.\n"
            "If the user asks for multiple images or files, focus on creating ONE perfect image that follows the description.\n"
            "MANDATORY FORMATTING: The output image must be in the requested aspect ratio. "
            "If no specific aspect ratio is mentioned, preserve the source image aspect ratio."
        )

        # Конфиг безопасности
        safety_settings = [
            {'category': 'HARM_CATEGORY_HATE_SPEECH', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'},
        ]
        
        # Parse explicit ratio first; otherwise preserve source ratio.
        source_ratio = self._closest_supported_ratio(*img.size)
        aspect_ratio = self._detect_aspect_ratio(prompt, default_ratio=source_ratio)
        logger.info(f"📐 Resulting aspect ratio: {aspect_ratio}")

        last_error = "unknown_error"
        total_timeout = 500
        retry_delay_sec = 30
        attempts = 2
        start_time = time.time()
        model_name = models_to_try[0]
        overloaded_markers = (
            "503",
            "429",
            "504",
            "overloaded",
            "resource exhausted",
            "high demand",
            "unavailable",
            "deadline exceeded",
            "deadline_exceeded",
            "timeout",
            "timed out",
        )

        for attempt in range(1, attempts + 1):
            elapsed = time.time() - start_time
            if elapsed > total_timeout:
                logger.warning(f"⏱️ [timeout] exceeded ({int(elapsed)}s > {total_timeout}s)")
                return {"b64": None, "reason": "timeout"}

            try:
                logger.info(f"[image] try model={model_name} attempt={attempt}/{attempts}")
                full_user_prompt = f"{prompt}\n\nIMPORTANT: Use {aspect_ratio} aspect ratio for the output image."

                gen_cfg_kwargs = {
                    "system_instruction": system_instruction,
                    "safety_settings": safety_settings,
                }
                image_config = self._image_config_for_model(model_name, aspect_ratio)
                if image_config is not None:
                    gen_cfg_kwargs["image_config"] = image_config

                gen_config = types.GenerateContentConfig(**gen_cfg_kwargs)

                response = self._nano_client.models.generate_content(
                    model=model_name,
                    contents=[full_user_prompt, img],
                    config=gen_config,
                )

                if not response:
                    last_error = "no_response"
                    raise RuntimeError(last_error)
                if not response.candidates:
                    last_error = "safety_filter"
                    raise RuntimeError(last_error)

                candidate = response.candidates[0]
                finish_reason = str(getattr(candidate, "finish_reason", "UNKNOWN"))
                logger.info(f"API [{model_name}]: finish_reason={finish_reason}")

                if not candidate.content or not candidate.content.parts:
                    if any(x in finish_reason for x in ["SAFETY", "BLOCK"]):
                        last_error = "safety_filter"
                    else:
                        last_error = "model_refusal"
                    raise RuntimeError(last_error)

                image_found = False
                for part in candidate.content.parts:
                    if not (part.inline_data and part.inline_data.data):
                        continue
                    image_found = True

                    raw = part.inline_data.data
                    if isinstance(raw, str):
                        raw = base64.b64decode(raw)

                    try:
                        out_img = Image.open(io.BytesIO(raw))
                        source_format = (out_img.format or "JPEG").upper()
                        fixed_img = self._enforce_aspect_ratio(out_img, aspect_ratio)

                        if fixed_img.size == out_img.size:
                            ext_map = {"JPEG": "jpg", "JPG": "jpg", "PNG": "png", "WEBP": "webp"}
                            image_ext = ext_map.get(source_format, "jpg")
                            logger.info(f"[image] success via {model_name} without re-encoding, format={source_format}")
                            return {
                                "b64": base64.b64encode(raw).decode("utf-8"),
                                "reason": None,
                                "image_ext": image_ext,
                            }

                        if fixed_img.mode not in ("RGB", "RGBA"):
                            fixed_img = fixed_img.convert("RGB")
                        buf = io.BytesIO()
                        fixed_img.save(buf, format="PNG", optimize=True)
                        logger.info(f"[image] success via {model_name} with lossless PNG postprocess")
                        return {
                            "b64": base64.b64encode(buf.getvalue()).decode("utf-8"),
                            "reason": None,
                            "image_ext": "png",
                        }
                    except Exception as decode_err:
                        logger.error(f"API [{model_name}]: decode error: {decode_err}")
                        last_error = "invalid_image_data"
                        raise RuntimeError(last_error)

                if not image_found:
                    last_error = "no_image_in_parts"
                    raise RuntimeError(last_error)

            except Exception as e:
                err_str = str(e)
                if last_error == "unknown_error":
                    last_error = err_str

                lowered_err = err_str.lower()
                is_busy = any(marker in lowered_err for marker in overloaded_markers)
                if is_busy:
                    logger.warning(f"API [{model_name}] overloaded/busy: {err_str}")
                    # Do not spend another full cycle after provider-side deadline errors.
                    is_deadline = ("deadline exceeded" in lowered_err) or ("deadline_exceeded" in lowered_err)
                    if is_deadline:
                        return {"b64": None, "reason": "server_overloaded"}
                    if attempt < attempts:
                        remaining = total_timeout - (time.time() - start_time)
                        if remaining <= 0:
                            return {"b64": None, "reason": "timeout"}
                        sleep_for = min(retry_delay_sec, max(0, int(remaining)))
                        if sleep_for > 0:
                            logger.warning(f"[image] retrying {model_name} in {sleep_for}s")
                            time.sleep(sleep_for)
                        continue
                    return {"b64": None, "reason": "server_overloaded"}

                logger.error(f"API [{model_name}] error: {err_str}")
                break

        lowered = str(last_error).lower()
        return {
            "b64": None,
            "reason": "server_overloaded" if any(marker in lowered for marker in overloaded_markers) else last_error,
        }


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

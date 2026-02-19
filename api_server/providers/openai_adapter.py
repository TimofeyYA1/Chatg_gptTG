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
                        http_options={'timeout': 300000} # 300,000 ms = 300 seconds (5 minutes)
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

    def _edit_image_with_nano(self, image_bytes: bytes, prompt: str, is_pro: bool = False) -> Dict[str, Any]:
        if not self._nano_enabled(): return {"b64": None, "reason": "provider_disabled"}
        if Image is None: return {"b64": None, "reason": "pillow_missing"}

        # --- ЖЕСТКОЕ ФОРМИРОВАНИЕ СПИСКА МОДЕЛЕЙ ---
        # Берем из настроек, если пусто - используем дефолты
        m_pro = str(getattr(settings, "NANOBANANA_MODEL_IMAGE--", "") or "gemini-3-pro-image-preview").strip()
        m_flash = str(getattr(settings, "NANOBANANA_MODEL_IMAGE_FALLBACK--", "") or "gemini-2.5-flash-image").strip()
        
        # Гарантируем, что модели не пустые
        if not m_pro: m_pro = "gemini-3-pro-image-preview"
        if not m_flash: m_flash = "gemini-2.5-flash-image"
        
        # Если модели одинаковые, принудительно делаем их разными для фоллбэка
        if m_pro == m_flash:
            logger.warning(f"⚠️ Primary и Fallback модели одинаковые ({m_pro}). Принудительно разделяем их.")
            if "pro" in m_pro.lower():
                m_flash = "gemini-2.5-flash-image"
            else:
                m_pro = "gemini-3-pro-image-preview"

        if is_pro:
            raw_models = [m_pro, m_flash]
        else:
            raw_models = [m_flash, m_pro]
            
        # Формируем итоговый список (на случай если что-то еще пошло не так)
        models_to_try = []
        for m in raw_models:
            if m and m not in models_to_try:
                models_to_try.append(m)

        # Если всё же осталась одна модель, добавляем вторую принудительно
        if len(models_to_try) < 2:
            second = "gemini-2.5-flash-image" if models_to_try[0] != "gemini-2.5-flash-image" else "gemini-3-pro-image-preview"
            models_to_try.append(second)

        logger.info(f"🚀 ПОДГОТОВКА: Очередь моделей (Pro={is_pro}): {models_to_try}")

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
            "If no specific aspect ratio is mentioned, you MUST produce a vertical image in 9:16 aspect ratio."
        )

        # Конфиг безопасности
        safety_settings = [
            {'category': 'HARM_CATEGORY_HATE_SPEECH', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'},
        ]
        
        # Попытка извлечь соотношение сторон из промпта
        aspect_ratio = "9:16"  # Дефолт: классическое вертикальное фото (как на приложенном фото)
        
        # 1. Поиск явных пропорций (16:9, 9:16, 4:3, 3:4, 1:1)
        ar_match = re.search(r'\b(16:9|9:16|4:3|3:4|1:1)\b', prompt)
        if ar_match:
            aspect_ratio = ar_match.group(1)
            logger.info(f"📐 Detected explicit aspect ratio in prompt: {aspect_ratio}")
        else:
            # 2. Поиск ключевых слов, если пропорции не указаны цифрами
            # (Промпт к этому моменту уже переведен на английский в роутере)
            p_lower = prompt.lower()
            if "horizontal" in p_lower or "landscape" in p_lower or "широкое" in p_lower:
                aspect_ratio = "16:9"
            elif "square" in p_lower or "квадратное" in p_lower:
                aspect_ratio = "1:1"
            elif "vertical" in p_lower or "portrait" in p_lower or "вертикальное" in p_lower:
                aspect_ratio = "9:16"
            
            logger.info(f"📐 Resulting aspect ratio: {aspect_ratio}")

        last_error = "unknown_error"
        TOTAL_TIMEOUT = 500 
        start_time = time.time()
        
        # СТРАТЕГИЯ ГЕНЕРАЦИИ: 2 цикла (Primary->Fallback) с паузой 30с между ними
        # В каждом цикле пробуем каждую модель по ОДНОМУ разу.
        for cycle in range(1, 3):
            if cycle == 2:
                logger.warning(f"⏳ [ЦИКЛ 1 ЗАВЕРШЕН ОШИБКОЙ] Ждем 30 секунд перед финальным ЦИКЛОМ 2...")
                time.sleep(30)

            for m_idx, model_name in enumerate(models_to_try):
                elapsed = time.time() - start_time
                if elapsed > TOTAL_TIMEOUT:
                    logger.warning(f"⏱️ [ТАЙМАУТ] Превышено время ({int(elapsed)}s > {TOTAL_TIMEOUT}s). Выход.")
                    return {"b64": None, "reason": "timeout"}

                try:
                    logger.info(f"--- ОБРАЩАЮСЬ К МОДЕЛИ: {model_name} (Цикл {cycle}) ---")
                    
                    # Формируем итоговый промпт с явным указанием формата
                    full_user_prompt = f"{prompt}\n\nIMPORTANT: Use {aspect_ratio} aspect ratio for the output image."
                
                    # Формируем конфиг
                    gen_config = types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        safety_settings=safety_settings,
                    )
                    
                    # ВЫЗОВ API
                    response = self._nano_client.models.generate_content(
                        model=model_name,
                        contents=[full_user_prompt, img],
                        config=gen_config
                    )

                    if not response:
                        logger.error(f"ЛОГИ ОТ АПИ ({model_name}): [ПУСТОЙ ОТВЕТ]")
                        last_error = "no_response"
                        if m_idx < len(models_to_try) - 1:
                            logger.info(f"Попытка не удалась, пробую фоллбэк...")
                            continue
                        else: break

                    if not response.candidates:
                        logger.warning(f"ЛОГИ ОТ АПИ ({model_name}): [НЕТ КАНДИДАТОВ] - вероятно, Safety Filter")
                        last_error = "safety_filter"
                        if m_idx < len(models_to_try) - 1:
                            logger.info(f"Попытка не удалась, пробую фоллбэк...")
                            continue
                        else: break

                    candidate = response.candidates[0]
                    finish_reason = str(getattr(candidate, 'finish_reason', 'UNKNOWN'))
                    logger.info(f"ЛОГИ ОТ АПИ ({model_name}): FinishReason={finish_reason}")

                    if not candidate.content or not candidate.content.parts:
                        logger.warning(f"ЛОГИ ОТ АПИ ({model_name}): ПУСТОЙ КОНТЕНТ. Reason: {finish_reason}")
                        if any(x in finish_reason for x in ["SAFETY", "BLOCK"]):
                            last_error = "safety_filter"
                            if m_idx < len(models_to_try) - 1:
                                logger.info(f"Попытка не удалась, пробую фоллбэк...")
                                continue
                            else: break
                        last_error = "model_refusal"
                        if m_idx < len(models_to_try) - 1:
                            logger.info(f"Попытка не удалась, пробую фоллбэк...")
                            continue
                        else: break

                    # Успешный ответ
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            raw = part.inline_data.data
                            if isinstance(raw, str): raw = base64.b64decode(raw)
                            try:
                                out_img = Image.open(io.BytesIO(raw))
                                buf = io.BytesIO()
                                out_img.save(buf, format="JPEG", quality=90)
                                logger.info(f"✨ УСПЕХ: Модель {model_name} сгенерировала изображение!")
                                return {"b64": base64.b64encode(buf.getvalue()).decode("utf-8"), "reason": None}
                            except Exception as e:
                                logger.error(f"ЛОГИ ОТ АПИ ({model_name}): ОШИБКА ДЕКОДИРОВАНИЯ: {e}")
                                last_error = "invalid_image_data"
                                continue
                    
                    logger.error(f"ЛОГИ ОТ АПИ ({model_name}): Изображение не найдено в ответе.")
                    last_error = "no_image_in_parts"

                except Exception as e:
                    err_str = str(e)
                    last_error = err_str
                    
                    is_busy = any(x in err_str for x in ["503", "429", "Overloaded", "Resource exhausted", "high demand", "UNAVAILABLE"])
                    
                    if is_busy:
                        logger.warning(f"ЛОГИ ОТ АПИ ({model_name}): [ЗАНЯТО/503/429] - {err_str}")
                    else:
                        logger.error(f"ЛОГИ ОТ АПИ ({model_name}): [ОШИБКА API] - {err_str}")
                    
                    # ПЕРЕХОД К СЛЕДУЮЩЕЙ МОДЕЛИ (если она есть)
                    if m_idx < len(models_to_try) - 1:
                        next_model = models_to_try[m_idx+1]
                        logger.warning(f"🔄 ОШИБКА МОДЕЛИ '{model_name}'. ПЕРЕКЛЮЧАЮСЬ НА ФОЛЛБЭК: '{next_model}'")
                        continue 
                    else:
                        logger.error(f"❌ Модель '{model_name}' была ПОСЛЕДНЕЙ в списке для этого цикла.")
                    
            # Конец цикла моделей
            if cycle == 1:
                logger.error(f"❌ Цикл 1 не удался для всех моделей. Последняя ошибка: {last_error}")

        return {"b64": None, "reason": "server_overloaded" if "503" in last_error else last_error}


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
from __future__ import annotations
from typing import List, Dict, Optional, Any

import logging
import io
import base64
import time
import re

from common.config import settings

logger = logging.getLogger(__name__)
TELEGRAM_PHOTO_SAFE_MAX_BYTES = 9_500_000

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
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


class GeminiProvider:
    def __init__(self) -> None:
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
        return self._nano_enabled()

    def _nano_enabled(self) -> bool:
        return bool(self._nano_client) and bool(
            getattr(settings, "NANOBANANA_ENABLED", False)
        )

    # ------------- TEXT -------------

    @staticmethod
    def _history_to_plaintext(history: List[Dict[str, str]], user_prompt: str) -> str:
        lines: list[str] = []
        for item in history:
            role = (item.get("role") or "user").strip()
            content = (item.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        lines.append(f"user: {user_prompt}")
        return "\n".join(lines)

    @staticmethod
    def _safe_token_count(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _modality_token_counts(self, details: Any) -> dict[str, int]:
        counts = {"text": 0, "image": 0}
        for item in details or []:
            modality_raw = str(getattr(item, "modality", "") or "").upper()
            token_count = self._safe_token_count(getattr(item, "token_count", 0))
            if "TEXT" in modality_raw:
                counts["text"] += token_count
            elif "IMAGE" in modality_raw:
                counts["image"] += token_count
        return counts

    def _fallback_image_input_tokens_for_model(self, model_name: str, has_input_image: bool) -> int:
        if not has_input_image:
            return 0
        model = (model_name or "").strip().lower()
        # Gemini 3 Pro Image pricing docs provide explicit image-input token equivalent.
        if "gemini-3-pro-image-preview" in model:
            return 560
        return 0

    def _extract_gemini_usage(
        self,
        response: Any,
        *,
        model_name: str,
        has_input_image: bool = False,
    ) -> dict[str, int]:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return {
                "input_text_tokens": 0,
                "input_image_tokens": 0,
                "output_text_tokens": 0,
                "output_image_tokens": 0,
            }

        prompt_counts = self._modality_token_counts(getattr(usage, "prompt_tokens_details", None))
        candidate_counts = self._modality_token_counts(getattr(usage, "candidates_tokens_details", None))
        thoughts_tokens = self._safe_token_count(getattr(usage, "thoughts_token_count", 0))

        input_image_tokens = prompt_counts["image"]
        if input_image_tokens == 0:
            input_image_tokens = self._fallback_image_input_tokens_for_model(model_name, has_input_image)

        return {
            "input_text_tokens": prompt_counts["text"],
            "input_image_tokens": input_image_tokens,
            "output_text_tokens": candidate_counts["text"] + thoughts_tokens,
            "output_image_tokens": candidate_counts["image"],
        }

    def chat_reply(
        self,
        history: List[Dict[str, str]],
        user_prompt: str,
        return_meta: bool = False,
    ) -> str | Dict[str, Any]:
        text = (user_prompt or "").strip()
        if not text:
            if return_meta:
                return {
                    "text": "🤖 Сообщение пустое.",
                    "error": None,
                    "provider": "system",
                    "model_used": "none",
                    "usage_tokens": {
                        "input_text_tokens": 0,
                        "input_image_tokens": 0,
                        "output_text_tokens": 0,
                        "output_image_tokens": 0,
                    },
                }
            return "🤖 Сообщение пустое."

        if not self._nano_enabled():
            if return_meta:
                return {
                    "text": "🤖 Ошибка нейросети.",
                    "error": "provider_disabled",
                    "provider": "system",
                    "model_used": "none",
                    "usage_tokens": {
                        "input_text_tokens": 0,
                        "input_image_tokens": 0,
                        "output_text_tokens": 0,
                        "output_image_tokens": 0,
                    },
                }
            return "🤖 Ошибка нейросети."

        tail = history[-settings.GEMINI_CONTEXT_MESSAGES:] if history else []
        request_text = self._history_to_plaintext(tail, text)
        reply = self.nano_chat_reply(
            system_prompt="You are a helpful assistant. Use conversation history if provided and answer clearly.",
            user_prompt=request_text,
            model_name=settings.NANOBANANA_MODEL_CHAT,
            return_meta=return_meta,
        )

        if return_meta:
            if isinstance(reply, dict):
                reply_text = str(reply.get("text") or "").strip()
                if reply_text:
                    return reply
            logger.warning("Gemini chat reply failed: %s", reply)
            return {"text": "🤖 Ошибка нейросети.", "error": "provider_error"}

        if isinstance(reply, str) and reply and not reply.startswith("Error:"):
            return reply.strip()
        logger.warning("Gemini chat reply failed: %s", reply)
        return "🤖 Ошибка нейросети."

    def nano_chat_reply(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str = None,
        return_meta: bool = False,
    ) -> str | Dict[str, Any]:
        """
        Text response via Gemini (NanoBanana).
        """
        if not self._nano_enabled():
            if return_meta:
                return {"text": "", "error": "Gemini provider disabled."}
            return "Gemini provider disabled."

        primary_model = (model_name or settings.NANOBANANA_MODEL_CHAT or "gemini-2.5-pro").strip()
        fallback_model = (settings.NANOBANANA_MODEL_CHAT_FALLBACK or "gemini-2.5-flash").strip()

        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        logger.info("Gemini translation models to try: %s", models_to_try)

        last_error = ""
        for current_model in models_to_try:
            try:
                logger.info("Gemini chat_reply attempt with model: %s", current_model)
                response = self._nano_client.models.generate_content(
                    model=current_model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=settings.GEMINI_TEMPERATURE,
                    )
                )
                response_text = (getattr(response, "text", "") or "").strip()
                if not response_text:
                    last_error = "empty_response"
                    continue

                if return_meta:
                    return {
                        "text": response_text,
                        "error": None,
                        "provider": "gemini",
                        "model_used": current_model,
                        "usage_tokens": self._extract_gemini_usage(response, model_name=current_model, has_input_image=False),
                    }
                return response_text
            except Exception as e:
                last_error = str(e)
                if "503" in last_error or "high demand" in last_error.lower() or "unavailable" in last_error.lower():
                    if len(models_to_try) > 1 and current_model == models_to_try[0]:
                        logger.warning(
                            "Model %s overloaded, switching to %s. Reason: %s",
                            current_model,
                            models_to_try[1],
                            last_error,
                        )
                        continue

                logger.error("Gemini chat error on model %s: %s", current_model, e)
                if len(models_to_try) > 1 and current_model == models_to_try[0]:
                    continue
                break

        if return_meta:
            return {"text": "", "error": f"Error: {last_error}"}
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

    @staticmethod
    def _extract_quoted_lines(prompt: str) -> list[str]:
        text = str(prompt or "")
        raw: list[str] = []
        for pattern in (r'"([^"\n]{1,200})"', r"«([^»\n]{1,200})»"):
            raw.extend(re.findall(pattern, text))

        lines: list[str] = []
        seen: set[str] = set()
        for item in raw:
            line = str(item or "").strip()
            if not line or line in seen:
                continue
            seen.add(line)
            lines.append(line)
        return lines

    @staticmethod
    def _is_text_poster_prompt(prompt: str, quoted_lines: list[str] | None = None) -> bool:
        lines = quoted_lines or []
        if not lines:
            return False
        text = (prompt or "").lower()
        markers = (
            "poster", "banner", "typography", "headline", "font", "text",
            "постер", "баннер", "реклам", "надпись", "шрифт", "текст",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _pick_text_color(prompt: str) -> tuple[int, int, int, int]:
        text = (prompt or "").lower()
        if "gold" in text or "золот" in text:
            return (236, 198, 108, 255)
        return (255, 255, 255, 255)

    @staticmethod
    def _load_font(size: int, bold: bool = False):
        if ImageFont is None:
            return None

        bold_paths = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
        )
        regular_paths = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
        )
        paths = bold_paths if bold else regular_paths
        for path in paths:
            try:
                return ImageFont.truetype(path, size=max(8, int(size)))
            except Exception:
                continue
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    def _fit_font_to_width(
        self,
        draw: "ImageDraw.ImageDraw",
        text: str,
        *,
        max_width: int,
        start_size: int,
        min_size: int,
        bold: bool,
        stroke_width: int = 1,
    ) -> tuple[Any, tuple[int, int, int, int]]:
        size = max(min_size, start_size)
        while size >= min_size:
            font = self._load_font(size, bold=bold)
            if font is None:
                break
            bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
            if (bbox[2] - bbox[0]) <= max_width:
                return font, bbox
            size -= 2

        fallback = self._load_font(min_size, bold=bold)
        if fallback is None:
            raise RuntimeError("font_unavailable")
        return fallback, draw.textbbox((0, 0), text, font=fallback, stroke_width=stroke_width)

    def _augment_prompt_for_exact_text(self, prompt: str) -> str:
        lines = self._extract_quoted_lines(prompt)
        if not self._is_text_poster_prompt(prompt, lines):
            return prompt

        exact_lines = "\n".join(f"{idx + 1}. {line}" for idx, line in enumerate(lines[:8]))
        strict_block = (
            "STRICT TYPOGRAPHY REQUIREMENTS:\n"
            "- Render text exactly as provided, without spelling changes.\n"
            "- Preserve alphabet (Cyrillic/Latin), punctuation, and symbols exactly.\n"
            "- Keep the text sharp, straight, and readable.\n"
            "- Do not add extra tiny symbols, microtext, or watermark-like artifacts.\n"
            "- Keep a clean background under text areas.\n"
            "- If exact text cannot be rendered, keep text area clean; do not output misspelled text.\n"
            "EXACT TEXT LINES:\n"
            f"{exact_lines}"
        )
        return f"{prompt}\n\n{strict_block}"

    def _overlay_exact_poster_text(self, img: "Image.Image", prompt: str) -> "Image.Image | None":
        if ImageDraw is None or ImageFont is None:
            return None

        lines = self._extract_quoted_lines(prompt)
        if not self._is_text_poster_prompt(prompt, lines):
            return None

        headline = lines[0].strip()
        sublines = [line.strip() for line in lines[1:] if line.strip()]
        if not headline:
            return None

        canvas = img.convert("RGBA")
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        color = self._pick_text_color(prompt)
        shadow = (0, 0, 0, 170)
        text_l = (prompt or "").lower()

        top_ratio = 0.38
        if any(k in text_l for k in ("в верхней", "вверху", "upper", "top")):
            top_ratio = 0.20
        elif any(k in text_l for k in ("в центре", "center", "centre")):
            top_ratio = 0.40

        main_start_size = max(int(width * 0.115), 36)
        main_font, main_bbox = self._fit_font_to_width(
            draw,
            headline,
            max_width=int(width * 0.86),
            start_size=main_start_size,
            min_size=24,
            bold=True,
            stroke_width=2,
        )
        main_w = main_bbox[2] - main_bbox[0]
        main_h = main_bbox[3] - main_bbox[1]
        main_x = (width - main_w) // 2
        y = int(height * top_ratio)

        draw.text((main_x + 2, y + 2), headline, font=main_font, fill=shadow)
        draw.text(
            (main_x, y),
            headline,
            font=main_font,
            fill=color,
            stroke_width=3,
            stroke_fill=(0, 0, 0, 120),
        )

        if not sublines:
            return canvas

        y += main_h + max(int(height * 0.035), 16)
        sub_start = max(int(main_start_size * 0.38), 20)
        for line in sublines[:5]:
            sub_font, sub_bbox = self._fit_font_to_width(
                draw,
                line,
                max_width=int(width * 0.90),
                start_size=sub_start,
                min_size=15,
                bold=False,
                stroke_width=1,
            )
            sub_w = sub_bbox[2] - sub_bbox[0]
            sub_h = sub_bbox[3] - sub_bbox[1]
            sx = (width - sub_w) // 2
            draw.text((sx + 1, y + 1), line, font=sub_font, fill=shadow)
            draw.text(
                (sx, y),
                line,
                font=sub_font,
                fill=color,
                stroke_width=1,
                stroke_fill=(0, 0, 0, 90),
            )
            y += sub_h + max(int(height * 0.009), 6)

        return canvas

    @staticmethod
    def _normalize_model_tier(model_tier: str | None, is_pro: bool = False) -> str:
        if model_tier:
            tier = str(model_tier).strip().lower()
            aliases = {
                "std": "start",
                "standard": "start",
                "start": "start",
                "pro2": "pro",
                "mid": "pro",
                "middle": "pro",
                "pro": "pro",
                "elite": "elite",
                "max": "elite",
                "premium": "elite",
            }
            return aliases.get(tier, "start")
        return "elite" if is_pro else "start"

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

    def _prepare_transport_image(
        self,
        img: "Image.Image",
        *,
        source_raw: bytes | None = None,
        source_ext: str = "jpg",
        max_bytes: int = TELEGRAM_PHOTO_SAFE_MAX_BYTES,
    ) -> tuple[bytes, str]:
        src_ext = str(source_ext or "jpg").lower()
        if src_ext == "jpeg":
            src_ext = "jpg"

        if source_raw and len(source_raw) <= max_bytes and src_ext in {"jpg", "png", "webp"}:
            return source_raw, src_ext

        resampling = getattr(Image, "Resampling", None)
        lanczos = resampling.LANCZOS if resampling else getattr(Image, "LANCZOS", Image.BICUBIC)

        best_payload: tuple[bytes, str] | None = None
        width = max(1, int(getattr(img, "width", 0) or 1))
        height = max(1, int(getattr(img, "height", 0) or 1))

        for scale in (1.0, 0.92, 0.84, 0.76):
            if scale >= 0.999:
                candidate = img
            else:
                new_w = max(1, int(width * scale))
                new_h = max(1, int(height * scale))
                candidate = img.resize((new_w, new_h), resample=lanczos)

            # Prefer JPEG for Telegram photo size constraints.
            jpeg_base = candidate.convert("RGB") if candidate.mode not in ("RGB", "L") else candidate
            for quality in (92, 88, 84, 80, 76, 72, 68):
                try:
                    b = io.BytesIO()
                    jpeg_base.save(
                        b,
                        format="JPEG",
                        quality=quality,
                        optimize=True,
                        progressive=True,
                    )
                    data = b.getvalue()
                    if best_payload is None or len(data) < len(best_payload[0]):
                        best_payload = (data, "jpg")
                    if len(data) <= max_bytes:
                        return data, "jpg"
                except Exception:
                    continue

            try:
                b = io.BytesIO()
                candidate.save(b, format="PNG", optimize=True)
                data = b.getvalue()
                if best_payload is None or len(data) < len(best_payload[0]):
                    best_payload = (data, "png")
                if len(data) <= max_bytes:
                    return data, "png"
            except Exception:
                pass

        if best_payload:
            logger.warning(
                "[image] output still large after compression attempts: %s bytes",
                len(best_payload[0]),
            )
            return best_payload

        fallback = source_raw or b""
        return fallback, (src_ext if src_ext in {"jpg", "png", "webp"} else "jpg")

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

    def _edit_image_with_nano(
        self,
        image_bytes: bytes,
        prompt: str,
        is_pro: bool = False,
        model_tier: str | None = None,
    ) -> Dict[str, Any]:
        if not self._nano_enabled(): return {"b64": None, "reason": "provider_disabled"}
        if Image is None: return {"b64": None, "reason": "pillow_missing"}

        # --- ЖЕСТКОЕ ФОРМИРОВАНИЕ СПИСКА МОДЕЛЕЙ ---
        # Берем из настроек, если пусто - используем дефолты
        m_elite = str(getattr(settings, "NANOBANANA_MODEL_IMAGE", "") or "gemini-3-pro-image-preview").strip()
        m_pro2 = str(getattr(settings, "NANOBANANA_MODEL_IMAGE_PRO2", "") or "gemini-3.1-flash-image-preview").strip()
        m_start = str(getattr(settings, "NANOBANANA_MODEL_IMAGE_FALLBACK", "") or "gemini-2.5-flash-image").strip()

        if not m_elite:
            m_elite = "gemini-3-pro-image-preview"
        if not m_pro2:
            m_pro2 = "gemini-3.1-flash-image-preview"
        if not m_start:
            m_start = "gemini-2.5-flash-image"

        normalized_tier = self._normalize_model_tier(model_tier, is_pro=is_pro)
        if normalized_tier == "elite":
            selected_model = m_elite
        elif normalized_tier == "pro":
            selected_model = m_pro2
        else:
            selected_model = m_start

        quoted_lines = self._extract_quoted_lines(prompt)
        strict_text_mode = self._is_text_poster_prompt(prompt, quoted_lines)
        if strict_text_mode and selected_model != m_elite:
            logger.info("[image] strict text mode enabled -> forcing elite model for cleaner typography")
            selected_model = m_elite

        prompt_for_model = self._augment_prompt_for_exact_text(prompt) if strict_text_mode else prompt
        logger.info(f"[image] selected model (tier={normalized_tier}): {selected_model}")

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
        model_name = selected_model
        last_usage_tokens: dict[str, int] | None = None
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

        def _pack_result(payload: Dict[str, Any]) -> Dict[str, Any]:
            payload["provider"] = "gemini"
            payload["model_used"] = model_name
            if last_usage_tokens is not None:
                payload["usage_tokens"] = last_usage_tokens
            return payload

        for attempt in range(1, attempts + 1):
            elapsed = time.time() - start_time
            if elapsed > total_timeout:
                logger.warning(f"⏱️ [timeout] exceeded ({int(elapsed)}s > {total_timeout}s)")
                return _pack_result({"b64": None, "reason": "timeout"})

            try:
                logger.info(f"[image] try model={model_name} attempt={attempt}/{attempts}")
                full_user_prompt = f"{prompt_for_model}\n\nIMPORTANT: Use {aspect_ratio} aspect ratio for the output image."

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
                last_usage_tokens = self._extract_gemini_usage(
                    response,
                    model_name=model_name,
                    has_input_image=True,
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

                        if strict_text_mode:
                            corrected_img = self._overlay_exact_poster_text(fixed_img, prompt)
                            if corrected_img is not None:
                                png_buf = io.BytesIO()
                                corrected_img.save(png_buf, format="PNG", optimize=True)
                                png_raw = png_buf.getvalue()
                                payload_bytes, payload_ext = self._prepare_transport_image(
                                    corrected_img,
                                    source_raw=png_raw,
                                    source_ext="png",
                                )
                                logger.info(f"[image] success via {model_name} with exact-text overlay")
                                return _pack_result(
                                    {
                                        "b64": base64.b64encode(payload_bytes).decode("utf-8"),
                                        "reason": None,
                                        "image_ext": payload_ext,
                                    }
                                )

                        if fixed_img.size == out_img.size:
                            ext_map = {"JPEG": "jpg", "JPG": "jpg", "PNG": "png", "WEBP": "webp"}
                            image_ext = ext_map.get(source_format, "jpg")
                            payload_bytes, payload_ext = self._prepare_transport_image(
                                fixed_img,
                                source_raw=raw,
                                source_ext=image_ext,
                            )
                            logger.info(f"[image] success via {model_name} without re-encoding, format={source_format}")
                            return _pack_result(
                                {
                                    "b64": base64.b64encode(payload_bytes).decode("utf-8"),
                                    "reason": None,
                                    "image_ext": payload_ext,
                                }
                            )

                        payload_bytes, payload_ext = self._prepare_transport_image(
                            fixed_img,
                            source_ext="png",
                        )
                        logger.info(f"[image] success via {model_name} with lossless PNG postprocess")
                        return _pack_result(
                            {
                                "b64": base64.b64encode(payload_bytes).decode("utf-8"),
                                "reason": None,
                                "image_ext": payload_ext,
                            }
                        )
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
                        return _pack_result({"b64": None, "reason": "server_overloaded"})
                    if attempt < attempts:
                        remaining = total_timeout - (time.time() - start_time)
                        if remaining <= 0:
                            return _pack_result({"b64": None, "reason": "timeout"})
                        sleep_for = min(retry_delay_sec, max(0, int(remaining)))
                        if sleep_for > 0:
                            logger.warning(f"[image] retrying {model_name} in {sleep_for}s")
                            time.sleep(sleep_for)
                        continue
                    return _pack_result({"b64": None, "reason": "server_overloaded"})

                logger.error(f"API [{model_name}] error: {err_str}")
                break

        lowered = str(last_error).lower()
        return _pack_result(
            {
                "b64": None,
                "reason": "server_overloaded" if any(marker in lowered for marker in overloaded_markers) else last_error,
            }
        )


    def edit_image_b64(
        self,
        image_bytes: bytes,
        prompt: str,
        size: str = "1024x1024",
        is_pro: bool = False,
        model_tier: str | None = None,
    ) -> Dict[str, Any]:
        """
        Публичный метод.
        """
        p = (prompt or "").strip()
        if not p or not image_bytes: 
            return {"b64": None, "reason": "empty_input"}
        
        if self._nano_enabled():
            # Передаем is_pro в приватный метод
            return self._edit_image_with_nano(image_bytes, p, is_pro=is_pro, model_tier=model_tier)
        
        return {"b64": None, "reason": "no_provider_enabled"}


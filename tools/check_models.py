from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import settings


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str = ""


def _run_gemini_checks(results: list[CheckResult], deep_image: bool = False) -> None:
    if not settings.GEMINI_API_KEY:
        results.append(CheckResult("gemini_api_key_present", False, "GEMINI_API_KEY is empty"))
        return

    try:
        from google import genai
    except Exception as exc:
        results.append(CheckResult("gemini_sdk_import", False, str(exc)))
        return

    client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options={"timeout": 30000})
    models = [
        ("NANOBANANA_MODEL_CHAT", settings.NANOBANANA_MODEL_CHAT),
        ("NANOBANANA_MODEL_CHAT_FALLBACK", settings.NANOBANANA_MODEL_CHAT_FALLBACK),
        ("NANOBANANA_MODEL_IMAGE", settings.NANOBANANA_MODEL_IMAGE),
        ("NANOBANANA_MODEL_IMAGE_PRO2", settings.NANOBANANA_MODEL_IMAGE_PRO2),
        ("NANOBANANA_MODEL_IMAGE_FALLBACK", settings.NANOBANANA_MODEL_IMAGE_FALLBACK),
    ]

    for env_name, model in models:
        model = (model or "").strip()
        if not model:
            results.append(CheckResult(f"gemini.model_name:{env_name}", False, "empty model name"))
            continue
        try:
            client.models.get(model=model)
            results.append(CheckResult(f"gemini.models.get:{env_name}={model}", True))
        except Exception as exc:
            results.append(CheckResult(f"gemini.models.get:{env_name}={model}", False, str(exc)))

    for model in (settings.NANOBANANA_MODEL_CHAT, settings.NANOBANANA_MODEL_CHAT_FALLBACK):
        model = (model or "").strip()
        if not model:
            continue
        try:
            out = client.models.generate_content(model=model, contents="Reply with OK only.")
            text = (getattr(out, "text", "") or "").strip()
            details = f"response={text[:80]}" if text else "empty response"
            results.append(CheckResult(f"gemini.generate_content:{model}", bool(text), details))
        except Exception as exc:
            results.append(CheckResult(f"gemini.generate_content:{model}", False, str(exc)))

    if deep_image:
        image_prompt = "Generate one simple image of a blue square on white background."
        for model in (
            settings.NANOBANANA_MODEL_IMAGE,
            settings.NANOBANANA_MODEL_IMAGE_PRO2,
            settings.NANOBANANA_MODEL_IMAGE_FALLBACK,
        ):
            model = (model or "").strip()
            if not model:
                continue
            try:
                out = client.models.generate_content(model=model, contents=image_prompt)
                has_image = False
                for candidate in (out.candidates or []):
                    content = getattr(candidate, "content", None)
                    parts = getattr(content, "parts", None) or []
                    for part in parts:
                        inline_data = getattr(part, "inline_data", None)
                        if inline_data is not None and getattr(inline_data, "data", None):
                            has_image = True
                            break
                    if has_image:
                        break
                details = "has_image_part" if has_image else "no_image_part"
                results.append(CheckResult(f"gemini.generate_image:{model}", has_image, details))
            except Exception as exc:
                results.append(CheckResult(f"gemini.generate_image:{model}", False, str(exc)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate configured Gemini models.")
    parser.add_argument(
        "--deep-image",
        action="store_true",
        help="Run expensive live image generation checks for Gemini image models.",
    )
    args = parser.parse_args()

    results: list[CheckResult] = []
    _run_gemini_checks(results, deep_image=args.deep_image)

    payload = {
        "nanobanana_enabled": bool(settings.NANOBANANA_ENABLED),
        "checks": [asdict(r) for r in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    failures = [r for r in results if not r.ok]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

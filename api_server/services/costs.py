from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

from sqlalchemy.orm import Session

from db_adapter.models import GenerationCostEvent, User

# Source: Google AI Gemini API pricing (ai.google.dev/gemini-api/docs/pricing)
# Snapshot date used for these rates: 2026-02-28.
# Prices are USD per 1M tokens.

MILLION = Decimal("1000000")
Q6 = Decimal("0.000001")


@dataclass(frozen=True)
class ModelRates:
    input_text_per_1m: Decimal
    input_image_per_1m: Decimal
    output_text_per_1m: Decimal
    output_image_per_1m: Decimal


GEMINI_IMAGE_25_FLASH = ModelRates(
    input_text_per_1m=Decimal("0.30"),
    input_image_per_1m=Decimal("0.30"),
    output_text_per_1m=Decimal("2.50"),
    output_image_per_1m=Decimal("30.00"),
)

GEMINI_IMAGE_31_FLASH_PREVIEW = ModelRates(
    input_text_per_1m=Decimal("0.25"),
    input_image_per_1m=Decimal("0.25"),
    output_text_per_1m=Decimal("1.50"),
    output_image_per_1m=Decimal("60.00"),
)

GEMINI_IMAGE_3_PRO_PREVIEW = ModelRates(
    input_text_per_1m=Decimal("2.00"),
    input_image_per_1m=Decimal("2.00"),
    output_text_per_1m=Decimal("12.00"),
    output_image_per_1m=Decimal("120.00"),
)

GEMINI_TEXT_25_FLASH = ModelRates(
    input_text_per_1m=Decimal("0.30"),
    input_image_per_1m=Decimal("0.30"),
    output_text_per_1m=Decimal("2.50"),
    output_image_per_1m=Decimal("0"),
)

GEMINI_TEXT_25_PRO_LOW_CTX = ModelRates(
    input_text_per_1m=Decimal("1.25"),
    input_image_per_1m=Decimal("1.25"),
    output_text_per_1m=Decimal("10.00"),
    output_image_per_1m=Decimal("0"),
)

GEMINI_TEXT_25_PRO_HIGH_CTX = ModelRates(
    input_text_per_1m=Decimal("2.50"),
    input_image_per_1m=Decimal("2.50"),
    output_text_per_1m=Decimal("15.00"),
    output_image_per_1m=Decimal("0"),
)


def _to_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_usage_tokens(usage_tokens: Mapping[str, Any] | None) -> dict[str, int]:
    usage = usage_tokens or {}
    return {
        "input_text_tokens": _to_non_negative_int(usage.get("input_text_tokens")),
        "input_image_tokens": _to_non_negative_int(usage.get("input_image_tokens")),
        "output_text_tokens": _to_non_negative_int(usage.get("output_text_tokens")),
        "output_image_tokens": _to_non_negative_int(usage.get("output_image_tokens")),
    }


def _rates_for_model(model_name: str, input_tokens_total: int) -> ModelRates | None:
    model = (model_name or "").strip().lower()
    if not model:
        return None

    if "gemini-3-pro-image-preview" in model:
        return GEMINI_IMAGE_3_PRO_PREVIEW
    if "gemini-3.1-flash-image-preview" in model:
        return GEMINI_IMAGE_31_FLASH_PREVIEW
    if "gemini-2.5-flash-image" in model:
        return GEMINI_IMAGE_25_FLASH
    if "gemini-2.5-pro" in model:
        return GEMINI_TEXT_25_PRO_HIGH_CTX if input_tokens_total > 200_000 else GEMINI_TEXT_25_PRO_LOW_CTX
    if "gemini-2.5-flash" in model:
        return GEMINI_TEXT_25_FLASH

    return None


def calculate_generation_cost_usd(model_name: str, usage_tokens: Mapping[str, Any] | None) -> float:
    usage = normalize_usage_tokens(usage_tokens)
    input_total = usage["input_text_tokens"] + usage["input_image_tokens"]
    rates = _rates_for_model(model_name, input_total)
    if rates is None:
        return 0.0

    total = (
        Decimal(usage["input_text_tokens"]) * rates.input_text_per_1m / MILLION
        + Decimal(usage["input_image_tokens"]) * rates.input_image_per_1m / MILLION
        + Decimal(usage["output_text_tokens"]) * rates.output_text_per_1m / MILLION
        + Decimal(usage["output_image_tokens"]) * rates.output_image_per_1m / MILLION
    )
    total = total.quantize(Q6, rounding=ROUND_HALF_UP)
    return float(total)


def record_generation_cost(
    db: Session,
    user: User,
    *,
    kind: str,
    provider: str,
    model_name: str,
    usage_tokens: Mapping[str, Any] | None,
) -> float:
    usage = normalize_usage_tokens(usage_tokens)
    cost_usd = calculate_generation_cost_usd(model_name, usage)
    if cost_usd <= 0:
        return 0.0

    event = GenerationCostEvent(
        user_id=user.id,
        kind=kind,
        provider=(provider or "").strip().lower() or "unknown",
        model_name=(model_name or "").strip(),
        input_text_tokens=usage["input_text_tokens"],
        input_image_tokens=usage["input_image_tokens"],
        output_text_tokens=usage["output_text_tokens"],
        output_image_tokens=usage["output_image_tokens"],
        cost_usd=cost_usd,
    )
    db.add(event)

    current_total = Decimal(str(user.total_generation_cost_usd or 0))
    user.total_generation_cost_usd = float((current_total + Decimal(str(cost_usd))).quantize(Q6, rounding=ROUND_HALF_UP))
    return cost_usd

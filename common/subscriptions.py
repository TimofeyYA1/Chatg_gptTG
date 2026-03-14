from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from dateutil.relativedelta import relativedelta

TierCode = Literal["start", "pro", "elite"]
PlanPeriod = Literal["week", "month", "year"]


@dataclass(frozen=True)
class PlanSpec:
    key: str
    tier: TierCode
    period: PlanPeriod
    price_rub: int
    price_stars: int
    images_limit: int
    title_ru: str

    @property
    def price_cents(self) -> int:
        return self.price_rub * 100

    @property
    def recurring_interval(self) -> str:
        return {"week": "Week", "month": "Month", "year": "Year"}[self.period]

    @property
    def recurring_period(self) -> int:
        return 1


PLAN_SPECS: tuple[PlanSpec, ...] = (
    PlanSpec(
        key="Week_Std",
        tier="start",
        period="week",
        price_rub=399,
        price_stars=300,
        images_limit=150,
        title_ru="7 дней (Старт)",
    ),
    PlanSpec(
        key="Month_Std",
        tier="start",
        period="month",
        price_rub=799,
        price_stars=900,
        images_limit=300,
        title_ru="месяц (Старт)",
    ),
    PlanSpec(
        key="Year_Std",
        tier="start",
        period="year",
        price_rub=5999,
        price_stars=4500,
        images_limit=7200,
        title_ru="год (Старт)",
    ),
    PlanSpec(
        key="Week_Pro",
        tier="elite",
        period="week",
        price_rub=799,
        price_stars=600,
        images_limit=150,
        title_ru="7 дней (Элит)",
    ),
    PlanSpec(
        key="Month_Std2",
        tier="pro",
        period="month",
        price_rub=999,
        price_stars=1150,
        images_limit=300,
        title_ru="месяц (Про)",
    ),
    PlanSpec(
        key="Month_Pro",
        tier="elite",
        period="month",
        price_rub=1599,
        price_stars=1800,
        images_limit=300,
        title_ru="месяц (Элит)",
    ),
    PlanSpec(
        key="Year_Pro",
        tier="elite",
        period="year",
        price_rub=11999,
        price_stars=9000,
        images_limit=7200,
        title_ru="год (Элит)",
    ),
)

PLAN_BY_KEY: dict[str, PlanSpec] = {spec.key: spec for spec in PLAN_SPECS}

PLAN_ALIASES_FOR_STORAGE: dict[str, str] = {
    "week": "Week_Std",
    "month": "Month_Std",
    "year": "Year_Std",
    "week_std": "Week_Std",
    "month_std": "Month_Std",
    "year_std": "Year_Std",
    "month_std2": "Month_Std2",
    "week_pro": "Week_Pro",
    "month_pro": "Month_Pro",
    "year_pro": "Year_Pro",
    "light": "Week_Std",
    "max": "Month_Std2",
    "ultra": "Month_Pro",
    "std": "Month_Std",
    "standard": "Month_Std",
    "start": "Month_Std",
    "pro": "Month_Pro",
    "premium": "Month_Pro",
    "elite": "Month_Pro",
}

# Current product line: only monthly tiers are sold through UI.
CHECKOUT_PLAN_KEYS: tuple[str, ...] = ("Month_Std", "Month_Std2", "Month_Pro")

TIER_NAME_RU: dict[TierCode, str] = {
    "start": "Старт",
    "pro": "Про",
    "elite": "Элит",
}

TIER_NAME_EN: dict[TierCode, str] = {
    "start": "Start",
    "pro": "Pro",
    "elite": "Elite",
}

ADDON_QTY = 300
ADDON_PRICE_RUB_BY_TIER: dict[TierCode, int] = {
    "start": 799,
    "pro": 999,
    "elite": 1599,
}
ADDON_PRICE_STARS_BY_TIER: dict[TierCode, int] = {
    "start": 900,
    "pro": 1150,
    "elite": 1800,
}

# Legacy values that may still exist in DB for old clients.
LEGACY_TIER_ALIASES: dict[str, TierCode] = {
    "free": "start",
    "week": "elite",
    "month": "elite",
    "year": "elite",
    "std": "start",
    "standard": "start",
    "start": "start",
    "light": "start",
    "max": "pro",
    "pro2": "pro",
    "mid": "pro",
    "ultra": "elite",
    "pro": "elite",
    "premium": "elite",
    "elite": "elite",
    "admin": "elite",
}

LEGACY_PLAN_TITLE_RU: dict[str, str] = {
    "week": "7 дней (Элит, legacy)",
    "month": "месяц (Элит, legacy)",
    "year": "год (Элит, legacy)",
    "light": "7 дней (Старт, legacy)",
    "max": "месяц (Про, legacy)",
    "ultra": "год (Элит, legacy)",
    "std": "месяц (Старт, legacy)",
    "standard": "месяц (Старт, legacy)",
    "start": "месяц (Старт, legacy)",
    "pro": "месяц (Элит, legacy)",
    "premium": "месяц (Элит, legacy)",
    "elite": "месяц (Элит, legacy)",
}

LEGACY_PLAN_PRICE_RUB: dict[str, int] = {
    "week": 799,
    "month": 1599,
    "year": 11999,
    "light": 399,
    "max": 999,
    "ultra": 11999,
    "std": 799,
    "standard": 799,
    "start": 799,
    "pro": 1599,
    "premium": 1599,
    "elite": 1599,
}

LEGACY_PLAN_IMAGE_LIMIT: dict[str, int] = {
    "week": 150,
    "month": 300,
    "year": 7200,
    "light": 150,
    "max": 300,
    "ultra": 7200,
    "std": 300,
    "standard": 300,
    "start": 300,
    "pro": 300,
    "premium": 300,
    "elite": 300,
}


def normalize_plan_key(plan_raw: str | None) -> str | None:
    if not plan_raw:
        return None
    plan = str(plan_raw).strip()
    if not plan:
        return None
    if plan in PLAN_BY_KEY:
        return plan
    return PLAN_ALIASES_FOR_STORAGE.get(plan.lower())


def get_plan_spec(plan_raw: str | None) -> PlanSpec | None:
    plan_key = normalize_plan_key(plan_raw)
    if not plan_key:
        return None
    return PLAN_BY_KEY.get(plan_key)


def tier_code_from_plan(plan_raw: str | None) -> TierCode:
    raw = str(plan_raw or "").strip().lower()
    if not raw or raw == "free":
        return "start"

    # Keep exact canonical plan mapping first.
    exact_spec = PLAN_BY_KEY.get(str(plan_raw or "").strip())
    if exact_spec:
        return exact_spec.tier

    # For legacy DB values we must not silently downgrade users.
    if raw in LEGACY_TIER_ALIASES:
        return LEGACY_TIER_ALIASES[raw]

    spec = get_plan_spec(plan_raw)
    if spec:
        return spec.tier

    if "std2" in raw:
        return "pro"
    if "_pro" in raw:
        return "elite"
    if "_std" in raw:
        return "start"
    return "elite"


def tier_name_ru(code: TierCode) -> str:
    return TIER_NAME_RU.get(code, "Старт")


def tier_name_en(code: TierCode) -> str:
    return TIER_NAME_EN.get(code, "Start")


def plan_title_ru(plan_raw: str | None) -> str:
    raw = str(plan_raw or "").strip().lower()
    if raw in LEGACY_PLAN_TITLE_RU:
        return LEGACY_PLAN_TITLE_RU[raw]
    spec = get_plan_spec(plan_raw)
    if spec:
        return spec.title_ru
    return f"период ({tier_name_ru(tier_code_from_plan(plan_raw))})"


def plan_price_rub(plan_raw: str | None) -> int:
    exact_spec = PLAN_BY_KEY.get(str(plan_raw or "").strip())
    if exact_spec:
        return exact_spec.price_rub
    raw = str(plan_raw or "").strip().lower()
    if raw in LEGACY_PLAN_PRICE_RUB:
        return LEGACY_PLAN_PRICE_RUB[raw]
    spec = get_plan_spec(plan_raw)
    return spec.price_rub if spec else 0


def plan_price_cents(plan_raw: str | None) -> int:
    spec = get_plan_spec(plan_raw)
    return spec.price_cents if spec else 0


def plan_images_limit(plan_raw: str | None) -> int:
    exact_spec = PLAN_BY_KEY.get(str(plan_raw or "").strip())
    if exact_spec:
        return exact_spec.images_limit
    raw = str(plan_raw or "").strip().lower()
    if raw in LEGACY_PLAN_IMAGE_LIMIT:
        return LEGACY_PLAN_IMAGE_LIMIT[raw]
    spec = get_plan_spec(plan_raw)
    return spec.images_limit if spec else 0


def plan_duration_end(start: datetime, plan_raw: str | None) -> datetime:
    spec = get_plan_spec(plan_raw)
    if not spec:
        return start
    if spec.period == "week":
        return start + timedelta(days=7)
    if spec.period == "month":
        return start + relativedelta(months=1)
    return start + relativedelta(years=1)


def addon_price_rub_for_tier(tier: TierCode) -> int:
    return ADDON_PRICE_RUB_BY_TIER[tier]


def addon_price_stars_for_tier(tier: TierCode) -> int:
    return ADDON_PRICE_STARS_BY_TIER[tier]

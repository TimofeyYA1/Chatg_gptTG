from pathlib import Path
import re
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# абсолютный путь к .env на уровень выше папки common/
ENV_FILE = (Path(__file__).resolve().parents[1] / ".env").as_posix()


def _parse_int_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    result: list[int] = []
    for chunk in re.split(r"[,\s;]+", str(raw).strip()):
        if not chunk:
            continue
        try:
            result.append(int(chunk))
        except ValueError:
            continue
    return result


class Settings(BaseSettings):
    # --- базовые ---
    APP_NAME: str = "AI SuperBot API"
    APP_ENV: str = "development"
    ALLOWED_ORIGINS: str = "*"
    ALLOWED_HOSTS: str = Field(
        "",
        validation_alias=AliasChoices("ALLOWED_HOSTS", "allowed_hosts"),
    )
    FORCE_HTTPS_REDIRECT: bool = Field(
        False,
        validation_alias=AliasChoices("FORCE_HTTPS_REDIRECT", "force_https_redirect"),
    )
    API_EXPOSE_DOCS: bool = False
    INTERNAL_API_TOKEN: str = Field("", validation_alias=AliasChoices("INTERNAL_API_TOKEN", "internal_api_token"))
    
    # Публичный URL API
    API_PUBLIC_URL: str = Field("http://localhost:8000", validation_alias=AliasChoices("API_PUBLIC_URL", "api_public_url"))
    PAYMENTS_PUBLIC_URL: str = Field(
        "",
        validation_alias=AliasChoices("PAYMENTS_PUBLIC_URL", "payments_public_url"),
    )

    # --- Postgres ---
    DB_HOST: str = Field("db", validation_alias=AliasChoices("DB_HOST", "db_host"))
    DB_PORT: int = Field(5432, validation_alias=AliasChoices("DB_PORT", "db_port"))
    DB_NAME: str = Field("ai_superbot", validation_alias=AliasChoices("DB_NAME", "db_name"))
    DB_USER: str = Field("postgres", validation_alias=AliasChoices("DB_USER", "db_user"))
    DB_PASSWORD: str = Field("postgres", validation_alias=AliasChoices("DB_PASSWORD", "db_password"))

    POSTGRES_DSN: str = Field("", validation_alias=AliasChoices("POSTGRES_DSN", "postgres_dsn"))

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = Field("", validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "telegram_bot_token"))
    BOT_NAME: str = Field("FacelabXbot", validation_alias=AliasChoices("BOT_NAME", "bot_name"))
    ADMIN_IDS: str = Field("", validation_alias=AliasChoices("ADMIN_IDS", "admin_ids"))

    # --- CloudPayments ---
    CLOUDPAYMENTS_PUBLIC_ID: str = Field("", validation_alias=AliasChoices("CLOUDPAYMENTS_PUBLIC_ID", "cloudpayments_public_id"))
    CLOUDPAYMENTS_API_SECRET: str = Field("", validation_alias=AliasChoices("CLOUDPAYMENTS_API_SECRET", "cloudpayments_api_secret"))

    # --- Cost estimation (USD) ---
    ESTIMATED_COST_IMAGE_STD_USD: float = Field(
        0.02,
        validation_alias=AliasChoices("ESTIMATED_COST_IMAGE_STD_USD", "estimated_cost_image_std_usd"),
    )
    ESTIMATED_COST_IMAGE_PRO_USD: float = Field(
        0.06,
        validation_alias=AliasChoices("ESTIMATED_COST_IMAGE_PRO_USD", "estimated_cost_image_pro_usd"),
    )
    ESTIMATED_COST_MESSAGE_USD: float = Field(
        0.001,
        validation_alias=AliasChoices("ESTIMATED_COST_MESSAGE_USD", "estimated_cost_message_usd"),
    )
    ESTIMATED_COST_VIDEO_SECOND_USD: float = Field(
        0.01,
        validation_alias=AliasChoices("ESTIMATED_COST_VIDEO_SECOND_USD", "estimated_cost_video_second_usd"),
    )

    # --- NanoBanana / Gemini ---
    GEMINI_API_KEY: str = Field("", validation_alias=AliasChoices("GEMINI_API_KEY", "gemini_api_key"))
    NANOBANANA_ENABLED: bool = Field(False, validation_alias=AliasChoices("NANOBANANA_ENABLED", "nanobanana_enabled"))
    GEMINI_CONTEXT_MESSAGES: int = Field(
        4, validation_alias=AliasChoices("GEMINI_CONTEXT_MESSAGES", "gemini_context_messages"),
    )
    GEMINI_TEMPERATURE: float = Field(
        0.1, validation_alias=AliasChoices("GEMINI_TEMPERATURE", "gemini_temperature"),
    )

    NANOBANANA_MODEL_CHAT: str = Field(
        "gemini-2.5-pro",
        validation_alias=AliasChoices("NANOBANANA_MODEL_CHAT", "nanobanana_model_chat"),
    )
    NANOBANANA_MODEL_CHAT_FALLBACK: str = Field(
        "gemini-2.5-flash",
        validation_alias=AliasChoices("NANOBANANA_MODEL_CHAT_FALLBACK", "nanobanana_model_chat_fallback"),
    )
    
    # PRIMARY MODEL (Для PRO аккаунтов) -> gemini-3-pro-image-preview
    NANOBANANA_MODEL_IMAGE: str = Field(
        "gemini-3-pro-image-preview",
        validation_alias=AliasChoices("NANOBANANA_MODEL_IMAGE", "nanobanana_model_image"),
    )
    
    # FALLBACK MODEL (Для STD аккаунтов и как запасная для PRO) -> gemini-2.5-flash-image
    NANOBANANA_MODEL_IMAGE_FALLBACK: str = Field(
        "gemini-2.5-flash-image",
        validation_alias=AliasChoices("NANOBANANA_MODEL_IMAGE_FALLBACK", "nanobanana_model_image_fallback"),
    )

    # MID MODEL (NanoBanana 2 / Тариф Про)
    NANOBANANA_MODEL_IMAGE_PRO2: str = Field(
        "gemini-3.1-flash-image-preview",
        validation_alias=AliasChoices("NANOBANANA_MODEL_IMAGE_PRO2", "nanobanana_model_image_pro2"),
    )
    
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    @property
    def admin_id_list(self) -> list[int]:
        return _parse_int_list(self.ADMIN_IDS)

settings = Settings()

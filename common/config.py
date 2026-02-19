from pathlib import Path
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# абсолютный путь к .env на уровень выше папки common/
ENV_FILE = (Path(__file__).resolve().parents[1] / ".env").as_posix()


class Settings(BaseSettings):
    # --- базовые ---
    APP_NAME: str = "AI SuperBot API"
    ALLOWED_ORIGINS: str = "*"
    
    # Публичный URL API
    API_PUBLIC_URL: str = Field("http://localhost:8000", validation_alias=AliasChoices("API_PUBLIC_URL", "api_public_url"))

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

    # --- CloudPayments ---
    CLOUDPAYMENTS_PUBLIC_ID: str = Field("", validation_alias=AliasChoices("CLOUDPAYMENTS_PUBLIC_ID", "cloudpayments_public_id"))
    CLOUDPAYMENTS_API_SECRET: str = Field("", validation_alias=AliasChoices("CLOUDPAYMENTS_API_SECRET", "cloudpayments_api_secret"))

    # --- OpenAI ---
    OPENAI_API_KEY: str = Field("", validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"))
    OPENAI_ENABLED: bool = Field(True, validation_alias=AliasChoices("OPENAI_ENABLED", "openai_enabled"))

    OPENAI_MODEL_CHAT: str = Field(
        "gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL_CHAT", "openai_model_chat", "OPENAI_CHAT_MODEL", "openai_chat_model"),
    )
    OPENAI_MODEL_IMAGE: str = Field(
        "gpt-image-1",
        validation_alias=AliasChoices("OPENAI_MODEL_IMAGE", "openai_model_image", "OPENAI_IMAGE_MODEL", "openai_image_model"),
    )

    OPENAI_MAX_OUTPUT_TOKENS: int = Field(
        128, validation_alias=AliasChoices("OPENAI_MAX_OUTPUT_TOKENS", "openai_max_output_tokens"),
    )
    OPENAI_CONTEXT_MESSAGES: int = Field(
        4, validation_alias=AliasChoices("OPENAI_CONTEXT_MESSAGES", "openai_context_messages"),
    )
    OPENAI_TEMPERATURE: float = Field(
        1, validation_alias=AliasChoices("OPENAI_TEMPERATURE", "openai_temperature"),
    )

    # --- NanoBanana / Gemini ---
    GEMINI_API_KEY: str = Field("", validation_alias=AliasChoices("GEMINI_API_KEY", "gemini_api_key"))
    NANOBANANA_ENABLED: bool = Field(False, validation_alias=AliasChoices("NANOBANANA_ENABLED", "nanobanana_enabled"))
    
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
    
    DEEPGRAM_API_KEY: str = Field(
        'None', validation_alias=AliasChoices("DEEPGRAM_API_KEY", "DEEPGRAM_API_KEY"),
    )

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

settings = Settings()
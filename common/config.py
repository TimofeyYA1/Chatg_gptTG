from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- базовые ---
    APP_NAME: str = "AI SuperBot API"
    ALLOWED_ORIGINS: str = "*"

    # --- Postgres ---
    DB_HOST: str = Field("db", validation_alias=AliasChoices("DB_HOST", "db_host"))
    DB_PORT: int = Field(5432, validation_alias=AliasChoices("DB_PORT", "db_port"))
    DB_NAME: str = Field("ai_superbot", validation_alias=AliasChoices("DB_NAME", "db_name"))
    DB_USER: str = Field("postgres", validation_alias=AliasChoices("DB_USER", "db_user"))
    DB_PASSWORD: str = Field("postgres", validation_alias=AliasChoices("DB_PASSWORD", "db_password"))

    # Поддержим как готовый DSN (из .env), так и сборку из кусочков
    POSTGRES_DSN: str = Field(
        "",
        validation_alias=AliasChoices("POSTGRES_DSN", "postgres_dsn"),
    )

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = Field(
        "", validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "telegram_bot_token")
    )

    BOT_NAME: str = Field(
        "ai_superbot",  # дефолт на случай, если в .env нет ключа
        validation_alias=AliasChoices("BOT_NAME", "bot_name"),
    )

    # --- OpenAI (экономный пресет по умолчанию) ---
    OPENAI_API_KEY: str = Field(
        "", validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key")
    )
    OPENAI_ENABLED: bool = Field(
        True, validation_alias=AliasChoices("OPENAI_ENABLED", "openai_enabled")
    )

    # Поддерживаем Оба имени: OPENAI_MODEL_CHAT и OPENAI_CHAT_MODEL
    OPENAI_MODEL_CHAT: str = Field(
        "gpt-4o-mini",
        validation_alias=AliasChoices(
            "OPENAI_MODEL_CHAT", "openai_model_chat", "OPENAI_CHAT_MODEL", "openai_chat_model"
        ),
    )
    OPENAI_MODEL_IMAGE: str = Field(
        "gpt-image-1",
        validation_alias=AliasChoices(
            "OPENAI_MODEL_IMAGE", "openai_model_image", "OPENAI_IMAGE_MODEL", "openai_image_model"
        ),
    )

    # лимиты для экономии токенов
    OPENAI_MAX_OUTPUT_TOKENS: int = Field(
        128,
        validation_alias=AliasChoices(
            "OPENAI_MAX_OUTPUT_TOKENS", "openai_max_output_tokens"
        ),
    )
    OPENAI_CONTEXT_MESSAGES: int = Field(
        4,
        validation_alias=AliasChoices(
            "OPENAI_CONTEXT_MESSAGES", "openai_context_messages"
        ),
    )
    OPENAI_TEMPERATURE: float = Field(
        0.2, validation_alias=AliasChoices("OPENAI_TEMPERATURE", "openai_temperature")
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


settings = Settings()

"""
Configuration module for Smart Goblin.

Uses pydantic-settings to load and validate configuration from environment variables.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database connection settings."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    url: SecretStr = Field(
        ...,
        alias="DATABASE_URL",
        description="PostgreSQL connection string for asyncpg",
    )

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate that URL is suitable for asyncpg.

        Normalizes Railway-style postgres:// and postgresql:// URLs
        to the postgresql+asyncpg:// scheme required by asyncpg.
        """
        if not v:
            raise ValueError("DATABASE_URL is required")
        # Normalize Railway-provided URLs (postgres:// or postgresql://)
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use postgresql+asyncpg:// scheme for async support"
            )
        return v

    @property
    def asyncpg_url(self) -> str:
        """Return the URL formatted for asyncpg (without +asyncpg suffix)."""
        url = self.url.get_secret_value()
        return url.replace("postgresql+asyncpg://", "postgresql://")


class TelegramSettings(BaseSettings):
    """Telegram bot settings."""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", extra="ignore")

    bot_token: SecretStr = Field(
        ...,
        description="Telegram Bot API token from @BotFather",
    )


class OpenAISettings(BaseSettings):
    """OpenAI API settings."""

    model_config = SettingsConfigDict(env_prefix="OPENAI_", extra="ignore")

    api_key: SecretStr = Field(
        ...,
        description="OpenAI API key",
    )
    model: str = Field(
        default="gpt-4o",
        description="Model for text generation",
    )
    vision_model: str = Field(
        default="gpt-4o",
        description="Model for image analysis",
    )


class ParserSettings(BaseSettings):
    """Parser and external API settings."""

    model_config = SettingsConfigDict(extra="ignore")

    scryfall_api_base: str = Field(
        default="https://api.scryfall.com",
        description="Scryfall API base URL",
    )
    seventeenlands_base: str = Field(
        default="https://www.17lands.com",
        description="17lands base URL",
    )
    parser_schedule_hour: int = Field(
        default=3,
        ge=0,
        le=23,
        description="Hour (UTC) when daily parser runs",
    )
    parser_schedule_enabled: bool = Field(
        default=True,
        description="Enable or disable the automatic cron scheduler",
    )


class Settings(BaseSettings):
    """
    Main application settings.

    Aggregates all sub-settings and provides a single point of access
    to the application configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sub-settings (loaded from environment)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    parser: ParserSettings = Field(default_factory=ParserSettings)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )

    def __repr__(self) -> str:
        """Return a safe string representation without secrets."""
        return (
            f"Settings(log_level={self.log_level!r}, "
            f"database=DatabaseSettings(...), "
            f"telegram=TelegramSettings(...), "
            f"openai=OpenAISettings(model={self.openai.model!r}, vision_model={self.openai.vision_model!r}), "
            f"parser=ParserSettings(scryfall_api_base={self.parser.scryfall_api_base!r}, ...))"
        )


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.

    Returns a cached instance of Settings to avoid re-reading
    environment variables on every call.
    """
    return Settings()

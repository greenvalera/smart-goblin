"""
Unit tests for the configuration module.

Tests cover:
- TC-3.1: Settings() with valid .env returns all fields
- TC-3.2: Missing TELEGRAM_BOT_TOKEN raises ValidationError
- TC-3.3: DATABASE_URL is correctly parsed for asyncpg
- TC-3.4: Settings.model_dump() does not contain secret values in repr
"""

import os
from unittest import mock

import pytest
from pydantic import ValidationError

from src.config import (
    DatabaseSettings,
    OpenAISettings,
    ParserSettings,
    Settings,
    TelegramSettings,
)


class TestTC31ValidSettings:
    """TC-3.1: Settings() with valid .env returns all fields."""

    def test_settings_loads_all_fields_from_env(self):
        """Settings should load all configuration from environment variables."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
            "OPENAI_API_KEY": "sk-test-key-123",
            "OPENAI_MODEL": "gpt-4o",
            "OPENAI_VISION_MODEL": "gpt-4o-vision",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
            "LOG_LEVEL": "DEBUG",
            "SCRYFALL_API_BASE": "https://api.scryfall.com",
            "SEVENTEENLANDS_BASE": "https://www.17lands.com",
            "PARSER_SCHEDULE_HOUR": "5",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()

            # Check Telegram settings
            assert settings.telegram.bot_token.get_secret_value() == "123456:ABC-DEF"

            # Check OpenAI settings
            assert settings.openai.api_key.get_secret_value() == "sk-test-key-123"
            assert settings.openai.model == "gpt-4o"
            assert settings.openai.vision_model == "gpt-4o-vision"

            # Check Database settings
            assert (
                settings.database.url.get_secret_value()
                == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
            )

            # Check Parser settings
            assert settings.parser.scryfall_api_base == "https://api.scryfall.com"
            assert settings.parser.seventeenlands_base == "https://www.17lands.com"
            assert settings.parser.parser_schedule_hour == 5

            # Check log level
            assert settings.log_level == "DEBUG"

    def test_settings_uses_defaults_for_optional_fields(self):
        """Settings should use defaults when optional fields are not provided."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
            "OPENAI_API_KEY": "sk-test-key-123",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()

            # Check defaults
            assert settings.openai.model == "gpt-4o"
            assert settings.openai.vision_model == "gpt-4o"
            assert settings.parser.scryfall_api_base == "https://api.scryfall.com"
            assert settings.parser.seventeenlands_base == "https://www.17lands.com"
            assert settings.parser.parser_schedule_hour == 3
            assert settings.log_level == "INFO"


class TestTC32MissingTelegramToken:
    """TC-3.2: Missing TELEGRAM_BOT_TOKEN raises ValidationError."""

    def test_missing_telegram_token_raises_validation_error(self):
        """Settings should raise ValidationError when TELEGRAM_BOT_TOKEN is missing."""
        env_vars = {
            "OPENAI_API_KEY": "sk-test-key-123",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()

            # Check that the error is about the missing token
            errors = exc_info.value.errors()
            error_fields = [e["loc"][0] for e in errors]
            assert "telegram" in error_fields or "bot_token" in str(errors)

    def test_telegram_settings_requires_bot_token(self):
        """TelegramSettings should require bot_token."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                TelegramSettings()

            errors = exc_info.value.errors()
            assert any("bot_token" in str(e) for e in errors)


class TestTC33DatabaseUrlParsing:
    """TC-3.3: DATABASE_URL is correctly parsed for asyncpg."""

    def test_database_url_with_asyncpg_scheme(self):
        """DATABASE_URL with postgresql+asyncpg:// should be accepted."""
        env_vars = {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            db_settings = DatabaseSettings()

            assert (
                db_settings.url.get_secret_value()
                == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
            )

    def test_database_url_auto_converts_from_postgresql(self):
        """DATABASE_URL with postgresql:// should be auto-converted to asyncpg."""
        env_vars = {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            db_settings = DatabaseSettings()

            # Should be converted to asyncpg
            assert (
                db_settings.url.get_secret_value()
                == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
            )

    def test_database_url_asyncpg_url_property(self):
        """asyncpg_url property should return URL without +asyncpg suffix."""
        env_vars = {
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            db_settings = DatabaseSettings()

            # asyncpg_url should have plain postgresql://
            assert (
                db_settings.asyncpg_url == "postgresql://user:pass@localhost:5432/testdb"
            )

    def test_database_url_auto_converts_from_postgres_shorthand(self):
        """DATABASE_URL with postgres:// (Railway format) should be auto-converted to asyncpg."""
        env_vars = {
            "DATABASE_URL": "postgres://user:pass@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            db_settings = DatabaseSettings()

            assert (
                db_settings.url.get_secret_value()
                == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
            )

    def test_database_url_rejects_invalid_scheme(self):
        """DATABASE_URL with invalid scheme should raise ValidationError."""
        env_vars = {
            "DATABASE_URL": "mysql://user:pass@localhost:3306/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                DatabaseSettings()

            assert "postgresql+asyncpg://" in str(exc_info.value)

    def test_database_url_missing_raises_validation_error(self):
        """Missing DATABASE_URL should raise ValidationError."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError):
                DatabaseSettings()


class TestTC34SecretsNotInRepr:
    """TC-3.4: Settings.model_dump() does not contain secret values in repr."""

    def test_settings_repr_hides_secrets(self):
        """Settings repr should not contain actual secret values."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF-SENSITIVE-TOKEN",
            "OPENAI_API_KEY": "sk-super-secret-api-key",
            "DATABASE_URL": "postgresql+asyncpg://user:secret-password@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            repr_str = repr(settings)

            # Secrets should not appear in repr
            assert "123456:ABC-DEF-SENSITIVE-TOKEN" not in repr_str
            assert "sk-super-secret-api-key" not in repr_str
            assert "secret-password" not in repr_str

    def test_settings_str_hides_secrets(self):
        """Settings str() should not contain actual secret values."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF-SENSITIVE-TOKEN",
            "OPENAI_API_KEY": "sk-super-secret-api-key",
            "DATABASE_URL": "postgresql+asyncpg://user:secret-password@localhost:5432/testdb",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            str_output = str(settings)

            # Secrets should not appear in str output
            assert "123456:ABC-DEF-SENSITIVE-TOKEN" not in str_output
            assert "sk-super-secret-api-key" not in str_output
            assert "secret-password" not in str_output

    def test_secret_str_hides_value_in_repr(self):
        """SecretStr fields should hide values in their repr."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "sensitive-token",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            telegram_settings = TelegramSettings()

            # SecretStr repr should show '**********'
            assert "sensitive-token" not in repr(telegram_settings.bot_token)
            assert "**********" in repr(telegram_settings.bot_token)

    def test_model_dump_with_secrets_mode(self):
        """model_dump() should respect secrets mode."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "sensitive-token",
            "OPENAI_API_KEY": "sk-secret",
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/db",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()

            # Default dump should hide secrets (SecretStr values)
            dump = settings.model_dump()

            # SecretStr objects are returned as-is in dump
            telegram_dump = settings.telegram.model_dump()
            assert isinstance(telegram_dump["bot_token"], str) is False


class TestSubSettings:
    """Tests for individual sub-settings classes."""

    def test_openai_settings_loads_correctly(self):
        """OpenAISettings should load all fields."""
        env_vars = {
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_MODEL": "gpt-4",
            "OPENAI_VISION_MODEL": "gpt-4-vision",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            settings = OpenAISettings()

            assert settings.api_key.get_secret_value() == "sk-test"
            assert settings.model == "gpt-4"
            assert settings.vision_model == "gpt-4-vision"

    def test_parser_settings_validates_schedule_hour(self):
        """ParserSettings should validate schedule_hour range."""
        # Valid hour
        env_vars = {"PARSER_SCHEDULE_HOUR": "12"}
        with mock.patch.dict(os.environ, env_vars, clear=True):
            settings = ParserSettings()
            assert settings.parser_schedule_hour == 12

        # Invalid hour (negative)
        env_vars = {"PARSER_SCHEDULE_HOUR": "-1"}
        with mock.patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError):
                ParserSettings()

        # Invalid hour (> 23)
        env_vars = {"PARSER_SCHEDULE_HOUR": "24"}
        with mock.patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError):
                ParserSettings()

    def test_log_level_validates_allowed_values(self):
        """Settings should only accept valid log levels."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "token",
            "OPENAI_API_KEY": "key",
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
            "LOG_LEVEL": "INVALID",
        }

        with mock.patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError):
                Settings()

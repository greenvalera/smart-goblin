"""
Unit tests for the LLM client module.

Tests cover:
- TC-8.1: call_vision() accepts base64 image and returns structured JSON
- TC-8.2: call_completion() with deck context returns Ukrainian text
- TC-8.3: Timeout after 60 seconds raises LLMTimeoutError
- TC-8.4: API error (429, 500) triggers retry with exponential backoff (up to 3 attempts)
"""

import asyncio
import base64
import json
import os
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from src.config import get_settings
from src.llm.client import LLMClient
from src.llm.exceptions import (
    LLMAPIError,
    LLMParseError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
)
from src.llm.prompts import CardRecognitionResult


@pytest.fixture
def mock_env():
    """Setup environment variables for tests."""
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "OPENAI_API_KEY": "sk-test-key",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    }
    # get_settings() is @lru_cache'd: a Settings instance built earlier in the
    # test session (or from .env) would otherwise leak the real OPENAI_API_KEY
    # into LLMClient and bypass these mocked env vars.
    get_settings.cache_clear()
    with mock.patch.dict(os.environ, env_vars, clear=True):
        yield
    get_settings.cache_clear()


@pytest.fixture
def sample_image_bytes():
    """Sample image bytes for testing."""
    # Create a simple 1x1 pixel PNG
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"


@pytest.fixture
def sample_image_base64(sample_image_bytes):
    """Sample base64-encoded image."""
    return base64.b64encode(sample_image_bytes).decode("utf-8")


def create_mock_response(content: str):
    """Create a mock OpenAI response object."""
    mock_message = MagicMock()
    mock_message.content = content

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    return mock_response


class TestTC81CallVisionReturnsJSON:
    """TC-8.1: call_vision() accepts base64 image and returns structured JSON."""

    @pytest.mark.asyncio
    async def test_call_vision_with_bytes_returns_json(self, mock_env, sample_image_bytes):
        """call_vision() should accept bytes and return parsed JSON."""
        expected_response = {
            "main_deck": ["Lightning Bolt", "Counterspell"],
            "sideboard": ["Negate"],
            "detected_set": "MKM",
        }

        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response(json.dumps(expected_response))
            )
            mock_get_client.return_value = mock_openai

            result = await client.call_vision(sample_image_bytes, "Recognize cards")

            assert result == expected_response
            assert isinstance(result, dict)
            assert "main_deck" in result
            assert "sideboard" in result

        await client.close()

    @pytest.mark.asyncio
    async def test_call_vision_with_base64_returns_json(self, mock_env, sample_image_base64):
        """call_vision() should accept base64 string and return parsed JSON."""
        expected_response = {
            "main_deck": ["Forest", "Island"],
            "sideboard": [],
            "detected_set": None,
        }

        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response(json.dumps(expected_response))
            )
            mock_get_client.return_value = mock_openai

            result = await client.call_vision(sample_image_base64, "Recognize cards")

            assert result == expected_response
            assert isinstance(result["main_deck"], list)
            assert isinstance(result["sideboard"], list)

        await client.close()

    @pytest.mark.asyncio
    async def test_call_vision_raises_parse_error_on_invalid_json(
        self, mock_env, sample_image_bytes
    ):
        """call_vision() should raise LLMParseError for invalid JSON response."""
        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response("Not valid JSON {{{")
            )
            mock_get_client.return_value = mock_openai

            with pytest.raises(LLMParseError) as exc_info:
                await client.call_vision(sample_image_bytes, "Recognize cards")

            assert "Invalid JSON" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_call_vision_raises_parse_error_on_empty_response(
        self, mock_env, sample_image_bytes
    ):
        """call_vision() should raise LLMParseError for empty response."""
        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response("")
            )
            mock_get_client.return_value = mock_openai

            with pytest.raises(LLMParseError) as exc_info:
                await client.call_vision(sample_image_bytes, "Recognize cards")

            assert "Empty response" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_recognize_cards_returns_result_object(
        self, mock_env, sample_image_bytes
    ):
        """recognize_cards() should return CardRecognitionResult."""
        expected_response = {
            "main_deck": ["Card A", "Card B"],
            "sideboard": ["Card C"],
            "detected_set": "OTJ",
        }

        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response(json.dumps(expected_response))
            )
            mock_get_client.return_value = mock_openai

            result = await client.recognize_cards(sample_image_bytes)

            assert isinstance(result, CardRecognitionResult)
            assert result.main_deck == ["Card A", "Card B"]
            assert result.sideboard == ["Card C"]
            assert result.detected_set == "OTJ"

        await client.close()


class TestTC82CallCompletionReturnsUkrainianText:
    """TC-8.2: call_completion() with deck context returns Ukrainian text."""

    @pytest.mark.asyncio
    async def test_call_completion_returns_text(self, mock_env):
        """call_completion() should return text response."""
        ukrainian_response = "Ваша колода має хороший баланс. Рекомендую додати більше карт з низькою маною."

        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response(ukrainian_response)
            )
            mock_get_client.return_value = mock_openai

            messages = [{"role": "user", "content": "Проаналізуй колоду"}]
            result = await client.call_completion(messages)

            assert result == ukrainian_response
            assert isinstance(result, str)

        await client.close()

    @pytest.mark.asyncio
    async def test_call_completion_uses_system_prompt(self, mock_env):
        """call_completion() should include system prompt in messages."""
        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response("Response")
            )
            mock_get_client.return_value = mock_openai

            messages = [{"role": "user", "content": "Test"}]
            await client.call_completion(messages)

            # Verify system prompt was included
            call_args = mock_openai.chat.completions.create.call_args
            sent_messages = call_args.kwargs.get("messages", [])
            assert len(sent_messages) >= 2
            assert sent_messages[0]["role"] == "system"

        await client.close()

    @pytest.mark.asyncio
    async def test_call_completion_with_custom_system_prompt(self, mock_env):
        """call_completion() should use custom system prompt when provided."""
        custom_prompt = "You are a custom assistant."
        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response("Response")
            )
            mock_get_client.return_value = mock_openai

            messages = [{"role": "user", "content": "Test"}]
            await client.call_completion(messages, system_prompt=custom_prompt)

            call_args = mock_openai.chat.completions.create.call_args
            sent_messages = call_args.kwargs.get("messages", [])
            assert sent_messages[0]["content"] == custom_prompt

        await client.close()

    @pytest.mark.asyncio
    async def test_generate_advice_returns_ukrainian_text(self, mock_env):
        """generate_advice() should return Ukrainian advice text."""
        ukrainian_advice = """Загальна оцінка: Колода має хороший потенціал з середнім рейтингом 3.5.

Рекомендації:
- Замініть "Слабка Карта" на "Сильна Карта" з сайдборду
- Зверніть увагу на криву мани"""

        client = LLMClient()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=create_mock_response(ukrainian_advice)
            )
            mock_get_client.return_value = mock_openai

            main_deck = [
                {"name": "Lightning Bolt", "rating": 4.5, "win_rate": 58.0, "cmc": 1},
                {"name": "Counterspell", "rating": 4.0, "win_rate": 55.0, "cmc": 2},
            ]
            sideboard = [{"name": "Negate", "rating": 3.0, "win_rate": 50.0}]
            analysis = {
                "total_score": 3.5,
                "estimated_win_rate": 52.5,
                "mana_curve": {0: 1, 1: 5, 2: 8, 3: 5, 4: 3, 5: 1},
                "color_distribution": {"U": 40, "R": 60},
            }

            result = await client.generate_advice(main_deck, sideboard, analysis)

            assert isinstance(result, str)
            assert len(result) > 0

        await client.close()


class TestTC83TimeoutRaisesLLMTimeoutError:
    """TC-8.3: Timeout after 60 seconds raises LLMTimeoutError."""

    @pytest.mark.asyncio
    async def test_timeout_raises_llm_timeout_error(self, mock_env, sample_image_bytes):
        """Timeout should raise LLMTimeoutError after all retries."""
        client = LLMClient(timeout=60.0, max_retries=1)

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                side_effect=APITimeoutError(request=MagicMock())
            )
            mock_get_client.return_value = mock_openai

            with pytest.raises(LLMTimeoutError) as exc_info:
                await client.call_vision(sample_image_bytes, "Test")

            assert exc_info.value.timeout == 60.0
            assert "timed out" in str(exc_info.value)

        await client.close()

    @pytest.mark.asyncio
    async def test_timeout_includes_timeout_value(self, mock_env):
        """LLMTimeoutError should include the timeout value."""
        client = LLMClient(timeout=30.0, max_retries=1)

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                side_effect=APITimeoutError(request=MagicMock())
            )
            mock_get_client.return_value = mock_openai

            with pytest.raises(LLMTimeoutError) as exc_info:
                await client.call_completion([{"role": "user", "content": "Test"}])

            assert exc_info.value.timeout == 30.0

        await client.close()

    @pytest.mark.asyncio
    async def test_default_timeout_is_60_seconds(self, mock_env):
        """Default timeout should be 60 seconds."""
        client = LLMClient()
        assert client._timeout == 60.0
        await client.close()


class TestTC84RetryWithExponentialBackoff:
    """TC-8.4: API error (429, 500) triggers retry with exponential backoff (up to 3 attempts)."""

    @pytest.mark.asyncio
    async def test_rate_limit_429_triggers_retry(self, mock_env, sample_image_bytes):
        """429 rate limit error should trigger retry."""
        client = LLMClient(max_retries=3)

        mock_request = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429

        call_count = 0

        async def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise APIStatusError(
                    message="Rate limit exceeded",
                    response=mock_response,
                    body={"error": {"message": "Rate limit exceeded"}},
                )
            return create_mock_response('{"result": "success"}')

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(side_effect=side_effect_func)
            mock_get_client.return_value = mock_openai

            # Patch sleep to speed up tests
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.call_vision(sample_image_bytes, "Test")

            assert call_count == 3  # Should have retried
            assert result == {"result": "success"}

        await client.close()

    @pytest.mark.asyncio
    async def test_server_error_500_triggers_retry(self, mock_env, sample_image_bytes):
        """500 server error should trigger retry."""
        client = LLMClient(max_retries=3)

        mock_response = MagicMock()
        mock_response.status_code = 500

        call_count = 0

        async def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise APIStatusError(
                    message="Internal server error",
                    response=mock_response,
                    body={"error": {"message": "Internal server error"}},
                )
            return create_mock_response('{"result": "success"}')

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(side_effect=side_effect_func)
            mock_get_client.return_value = mock_openai

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.call_vision(sample_image_bytes, "Test")

            assert call_count == 2
            assert result == {"result": "success"}

        await client.close()

    @pytest.mark.asyncio
    async def test_max_retries_is_3_by_default(self, mock_env):
        """Default max retries should be 3."""
        client = LLMClient()
        assert client._max_retries == 3
        await client.close()

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_last_error(self, mock_env, sample_image_bytes):
        """After all retries exhausted, should raise the last error."""
        client = LLMClient(max_retries=3)

        mock_response = MagicMock()
        mock_response.status_code = 429

        call_count = 0

        async def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise APIStatusError(
                message="Rate limit exceeded",
                response=mock_response,
                body={"error": {"message": "Rate limit exceeded"}},
            )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(side_effect=side_effect_func)
            mock_get_client.return_value = mock_openai

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(LLMRateLimitError):
                    await client.call_vision(sample_image_bytes, "Test")

            assert call_count == 3  # All retries attempted

        await client.close()

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self, mock_env, sample_image_bytes):
        """Retry should use exponential backoff delays."""
        client = LLMClient(max_retries=3)

        mock_response = MagicMock()
        mock_response.status_code = 500

        sleep_times = []

        async def mock_sleep(delay):
            sleep_times.append(delay)

        async def side_effect_func(*args, **kwargs):
            raise APIStatusError(
                message="Server error",
                response=mock_response,
                body={"error": {"message": "Server error"}},
            )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(side_effect=side_effect_func)
            mock_get_client.return_value = mock_openai

            with patch("asyncio.sleep", side_effect=mock_sleep):
                with pytest.raises(LLMServerError):
                    await client.call_vision(sample_image_bytes, "Test")

            # Should have slept twice (between retries 1-2 and 2-3)
            assert len(sleep_times) == 2
            # Second delay should be larger than first (exponential)
            assert sleep_times[1] >= sleep_times[0]

        await client.close()

    @pytest.mark.asyncio
    async def test_non_retryable_error_does_not_retry(self, mock_env, sample_image_bytes):
        """4xx errors (except 429) should not trigger retry."""
        client = LLMClient(max_retries=3)

        mock_response = MagicMock()
        mock_response.status_code = 400  # Bad request

        call_count = 0

        async def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise APIStatusError(
                message="Bad request",
                response=mock_response,
                body={"error": {"message": "Bad request"}},
            )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(side_effect=side_effect_func)
            mock_get_client.return_value = mock_openai

            with pytest.raises(LLMAPIError):
                await client.call_vision(sample_image_bytes, "Test")

            # Should NOT retry for 400 errors
            assert call_count == 1

        await client.close()

    @pytest.mark.asyncio
    async def test_connection_error_triggers_retry(self, mock_env, sample_image_bytes):
        """Connection errors should trigger retry."""
        client = LLMClient(max_retries=2)

        call_count = 0

        async def side_effect_func(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise APIConnectionError(request=MagicMock())
            return create_mock_response('{"result": "success"}')

        with patch.object(client, "_get_client") as mock_get_client:
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(side_effect=side_effect_func)
            mock_get_client.return_value = mock_openai

            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.call_vision(sample_image_bytes, "Test")

            assert call_count == 2
            assert result == {"result": "success"}

        await client.close()


class TestLLMClientInitialization:
    """Tests for LLMClient initialization and configuration."""

    def test_client_uses_config_defaults(self, mock_env):
        """Client should use config values by default."""
        client = LLMClient()

        assert client._api_key == "sk-test-key"
        assert client._model == "gpt-4o"
        assert client._vision_model == "gpt-4o"

    def test_client_accepts_custom_values(self, mock_env):
        """Client should accept custom configuration."""
        client = LLMClient(
            api_key="custom-key",
            model="custom-model",
            vision_model="custom-vision",
            timeout=30.0,
            max_retries=5,
        )

        assert client._api_key == "custom-key"
        assert client._model == "custom-model"
        assert client._vision_model == "custom-vision"
        assert client._timeout == 30.0
        assert client._max_retries == 5

    @pytest.mark.asyncio
    async def test_client_close_releases_resources(self, mock_env):
        """close() should release client resources."""
        client = LLMClient()

        # Create the internal client
        _ = client._get_client()
        assert client._client is not None

        # Close should set client to None
        await client.close()
        assert client._client is None


class TestPromptBuilders:
    """Tests for prompt building functions."""

    def test_build_advice_prompt_includes_all_sections(self):
        """build_advice_prompt should include all deck sections."""
        from src.llm.prompts import build_advice_prompt

        main_deck = [
            {"name": "Card A", "rating": 4.0, "win_rate": 55.0, "cmc": 2},
        ]
        sideboard = [
            {"name": "Card B", "rating": 3.0, "win_rate": 50.0},
        ]
        analysis = {
            "total_score": 3.5,
            "estimated_win_rate": 52.0,
            "mana_curve": {1: 5, 2: 8, 3: 5},
            "color_distribution": {"U": 60, "W": 40},
        }

        prompt = build_advice_prompt(main_deck, sideboard, analysis)

        assert "Main Deck" in prompt
        assert "Sideboard" in prompt
        assert "Card A" in prompt
        assert "Card B" in prompt
        assert "3.5" in prompt  # total_score
        assert "52.0" in prompt  # win_rate

    def test_build_advice_prompt_handles_empty_sideboard(self):
        """build_advice_prompt should handle empty sideboard."""
        from src.llm.prompts import build_advice_prompt

        main_deck = [{"name": "Card A", "rating": 4.0, "cmc": 2}]
        sideboard = []
        analysis = {}

        prompt = build_advice_prompt(main_deck, sideboard, analysis)

        assert "Sideboard: empty" in prompt

    def test_build_vision_prompt_returns_base_prompt(self):
        """build_vision_prompt should return recognition prompt."""
        from src.llm.prompts import build_vision_prompt

        prompt = build_vision_prompt()

        assert "Magic: The Gathering" in prompt
        assert "main_deck" in prompt
        assert "sideboard" in prompt
        assert "detected_set" in prompt

    def test_build_vision_prompt_with_additional_context(self):
        """build_vision_prompt should append additional context."""
        from src.llm.prompts import build_vision_prompt

        prompt = build_vision_prompt(additional_context="Focus on Murders at Karlov Manor")

        assert "Additional context" in prompt
        assert "Murders at Karlov Manor" in prompt

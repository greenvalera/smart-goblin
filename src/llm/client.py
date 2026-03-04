"""
OpenAI client wrapper for Smart Goblin.

Provides vision and completion calls with retry logic and error handling.
"""

import asyncio
import base64
import json
import logging
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from src.config import get_settings
from src.llm.exceptions import (
    LLMAPIError,
    LLMParseError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
)
from src.llm.prompts import ADVICE_SYSTEM_PROMPT, CardRecognitionResult

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Async OpenAI client wrapper with retry logic.

    Provides methods for vision (image recognition) and completion (text generation)
    calls with exponential backoff retry for transient errors.
    """

    DEFAULT_TIMEOUT = 60.0  # seconds
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # seconds
    MAX_DELAY = 10.0  # seconds

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        """
        Initialize the LLM client.

        Args:
            api_key: OpenAI API key. Defaults to config value.
            model: Model for text generation. Defaults to config value.
            vision_model: Model for vision calls. Defaults to config value.
            timeout: Request timeout in seconds. Defaults to 60.
            max_retries: Maximum number of retry attempts. Defaults to 3.
        """
        settings = get_settings()
        self._api_key = api_key or settings.openai.api_key.get_secret_value()
        self._model = model or settings.openai.model
        self._vision_model = vision_model or settings.openai.vision_model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        """Get or create the OpenAI async client."""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the client and release resources."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _retry_with_backoff(
        self,
        coro_factory: callable,
        operation_name: str,
    ) -> Any:
        """
        Execute an async operation with exponential backoff retry.

        Args:
            coro_factory: A callable that returns a coroutine to execute.
            operation_name: Name of the operation for logging.

        Returns:
            The result of the coroutine.

        Raises:
            LLMTimeoutError: If all attempts time out.
            LLMRateLimitError: If rate limited after all retries.
            LLMServerError: If server error persists after all retries.
            LLMAPIError: For other API errors.
        """
        last_exception: Exception | None = None
        delay = self.BASE_DELAY

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug(f"{operation_name}: attempt {attempt}/{self._max_retries}")
                return await coro_factory()

            except APITimeoutError as e:
                last_exception = LLMTimeoutError(
                    f"{operation_name} timed out", timeout=self._timeout
                )
                logger.warning(
                    f"{operation_name}: timeout on attempt {attempt}/{self._max_retries}"
                )

            except APIStatusError as e:
                status_code = e.status_code
                error_msg = str(e.message) if hasattr(e, "message") else str(e)

                if status_code == 429:
                    last_exception = LLMRateLimitError(
                        f"{operation_name}: rate limit exceeded - {error_msg}"
                    )
                    logger.warning(
                        f"{operation_name}: rate limited on attempt {attempt}/{self._max_retries}"
                    )
                elif status_code >= 500:
                    last_exception = LLMServerError(
                        f"{operation_name}: server error - {error_msg}",
                        status_code=status_code,
                    )
                    logger.warning(
                        f"{operation_name}: server error {status_code} on attempt {attempt}/{self._max_retries}"
                    )
                else:
                    # Non-retryable error (4xx except 429)
                    raise LLMAPIError(
                        f"{operation_name}: API error - {error_msg}",
                        status_code=status_code,
                        retryable=False,
                    ) from e

            except APIConnectionError as e:
                last_exception = LLMAPIError(
                    f"{operation_name}: connection error - {e}",
                    retryable=True,
                )
                logger.warning(
                    f"{operation_name}: connection error on attempt {attempt}/{self._max_retries}"
                )

            # Wait before retrying (except on last attempt)
            if attempt < self._max_retries:
                logger.debug(f"{operation_name}: waiting {delay:.1f}s before retry")
                await asyncio.sleep(delay)
                # Exponential backoff with cap
                delay = min(delay * 2, self.MAX_DELAY)

        # All retries exhausted
        logger.error(f"{operation_name}: all {self._max_retries} attempts failed")
        raise last_exception

    async def call_vision(
        self,
        image: bytes | str,
        prompt: str,
    ) -> dict[str, Any]:
        """
        Call GPT-4o Vision to analyze an image.

        Args:
            image: Image as bytes or base64-encoded string.
            prompt: The prompt describing what to extract from the image.

        Returns:
            Parsed JSON response from the model.

        Raises:
            LLMTimeoutError: If request times out after all retries.
            LLMRateLimitError: If rate limited after all retries.
            LLMServerError: If server error persists.
            LLMAPIError: For other API errors.
            LLMParseError: If response cannot be parsed as JSON.
        """
        # Encode image to base64 if bytes
        if isinstance(image, bytes):
            image_b64 = base64.b64encode(image).decode("utf-8")
        else:
            image_b64 = image

        client = self._get_client()

        async def _make_request() -> Any:
            response = await client.chat.completions.create(
                model=self._vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=4096,
            )
            return response

        response = await self._retry_with_backoff(_make_request, "call_vision")

        # Extract and parse response
        content = response.choices[0].message.content
        if not content:
            raise LLMParseError("Empty response from vision model")

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse vision response: {content[:500]}")
            raise LLMParseError(f"Invalid JSON in vision response: {e}") from e

    async def call_completion(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> str:
        """
        Call GPT-4o for text completion.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            system_prompt: Optional system prompt. Defaults to advice prompt.

        Returns:
            The model's text response.

        Raises:
            LLMTimeoutError: If request times out after all retries.
            LLMRateLimitError: If rate limited after all retries.
            LLMServerError: If server error persists.
            LLMAPIError: For other API errors.
        """
        client = self._get_client()

        # Build message list with system prompt
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        else:
            full_messages.append({"role": "system", "content": ADVICE_SYSTEM_PROMPT})
        full_messages.extend(messages)

        async def _make_request() -> Any:
            response = await client.chat.completions.create(
                model=self._model,
                messages=full_messages,
                max_completion_tokens=2048,
            )
            return response

        response = await self._retry_with_backoff(_make_request, "call_completion")

        content = response.choices[0].message.content
        if not content:
            return ""

        return content

    async def recognize_cards(self, image: bytes | str) -> CardRecognitionResult:
        """
        Recognize MTG cards from an image.

        Convenience method that calls vision with the card recognition prompt.

        Args:
            image: Image as bytes or base64-encoded string.

        Returns:
            CardRecognitionResult with main_deck, sideboard, and detected_set.

        Raises:
            LLMTimeoutError: If request times out.
            LLMParseError: If response format is invalid.
        """
        from src.llm.prompts import build_vision_prompt

        prompt = build_vision_prompt()
        result = await self.call_vision(image, prompt)

        return CardRecognitionResult(
            main_deck=result.get("main_deck", []),
            sideboard=result.get("sideboard", []),
            detected_set=result.get("detected_set"),
        )

    async def generate_advice(
        self,
        main_deck: list[dict[str, Any]],
        sideboard: list[dict[str, Any]],
        analysis: dict[str, Any],
    ) -> str:
        """
        Generate deck advice in Ukrainian.

        Convenience method that builds the advice prompt and calls completion.

        Args:
            main_deck: List of card dicts with name, rating, win_rate, cmc.
            sideboard: List of card dicts with name, rating, win_rate.
            analysis: Dict with total_score, estimated_win_rate, mana_curve, colors.

        Returns:
            Advice text in Ukrainian.
        """
        from src.llm.prompts import build_advice_prompt

        prompt = build_advice_prompt(main_deck, sideboard, analysis)
        messages = [{"role": "user", "content": prompt}]

        return await self.call_completion(messages)


# Module-level client instance for convenience
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """
    Get a shared LLM client instance.

    Returns:
        Shared LLMClient instance.
    """
    global _client
    if _client is None:
        _client = LLMClient()
    return _client

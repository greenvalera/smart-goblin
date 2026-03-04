"""
LLM module for Smart Goblin.

Provides OpenAI client wrapper for vision and completion calls.
"""

from src.llm.client import LLMClient, get_llm_client
from src.llm.exceptions import (
    LLMAPIError,
    LLMError,
    LLMParseError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
)
from src.llm.prompts import (
    ADVICE_SYSTEM_PROMPT,
    CARD_RECOGNITION_PROMPT,
    CardRecognitionResult,
    build_advice_prompt,
    build_vision_prompt,
)

__all__ = [
    # Client
    "LLMClient",
    "get_llm_client",
    # Exceptions
    "LLMError",
    "LLMTimeoutError",
    "LLMAPIError",
    "LLMRateLimitError",
    "LLMServerError",
    "LLMParseError",
    # Prompts
    "CARD_RECOGNITION_PROMPT",
    "ADVICE_SYSTEM_PROMPT",
    "CardRecognitionResult",
    "build_advice_prompt",
    "build_vision_prompt",
]

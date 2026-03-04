"""
Custom exceptions for LLM module.

Provides specific exception types for different LLM-related errors.
"""


class LLMError(Exception):
    """Base exception for all LLM-related errors."""

    pass


class LLMTimeoutError(LLMError):
    """Raised when LLM call exceeds the timeout limit."""

    def __init__(self, message: str = "LLM request timed out", timeout: float = 60.0):
        self.timeout = timeout
        super().__init__(f"{message} (timeout: {timeout}s)")


class LLMAPIError(LLMError):
    """Raised when the LLM API returns an error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retryable: bool = False,
    ):
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


class LLMRateLimitError(LLMAPIError):
    """Raised when rate limited by the LLM API (HTTP 429)."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, status_code=429, retryable=True)


class LLMServerError(LLMAPIError):
    """Raised when LLM API returns a server error (5xx)."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code=status_code, retryable=True)


class LLMParseError(LLMError):
    """Raised when LLM response cannot be parsed as expected."""

    def __init__(self, message: str = "Failed to parse LLM response"):
        super().__init__(message)

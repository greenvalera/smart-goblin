---
last_mapped_commit: 8366eb8
---

# Coding Conventions

**Analysis Date:** 2026-09-23

## Naming Patterns

**Files:**
- Snake_case module names matching their primary responsibility: `src/core/analyzer.py`, `src/core/advisor.py`, `src/db/repository.py`, `src/vision/recognizer.py`, `src/vision/card_matcher.py`.
- One handler file per bot command/feature area under `src/bot/handlers/`: `analyze.py`, `draft.py`, `history.py`, `start.py`, `stats.py`.
- Test files mirror the module under test: `src/core/advisor.py` → `tests/test_core/test_advisor.py`. Cross-cutting/full-flow tests live in `tests/integration/`.

**Functions:**
- snake_case, verb-first: `get_by_code`, `get_or_create`, `upsert_cards`, `recommend_lands`.
- Private/internal helpers prefixed with a single underscore: `_calculate_score`, `_get_weight`, `_retry_with_backoff`, `_handle_single_card`, `_run_deck_pipeline` (`src/core/analyzer.py`, `src/bot/handlers/analyze.py`).
- Module-level singleton accessors use `get_<thing>` naming with a module-level `_<thing>` cache variable: `get_llm_client()` / `_client` in `src/llm/client.py`, `get_settings()` in `src/config.py`.

**Variables:**
- snake_case throughout. Constants are UPPER_SNAKE_CASE and declared near the top of the module: `DEFAULT_RATING`, `MIN_GAMES_HIGH_CONFIDENCE` (`src/core/analyzer.py`), `WEAK_CARD_THRESHOLD`, `STRONG_CARD_THRESHOLD` (`src/core/advisor.py`), `DEFAULT_TIMEOUT`, `MAX_RETRIES`, `BASE_DELAY`, `MAX_DELAY` (as class attributes in `src/llm/client.py`).

**Types:**
- PascalCase for classes, dataclasses, and SQLAlchemy models: `DeckAnalyzer`, `DeckAdvisor`, `CardInfo`, `Deck`, `DeckAnalysis` (`src/core/deck.py`), `LLMClient`, `Card`, `User`, `Analysis`, `Set`, `CardRating` (`src/db/models.py`).
- Repository classes are named `<Entity>Repository`: `SetRepository`, `CardRepository`, `UserRepository`, `AnalysisRepository` (`src/db/repository.py`).
- Data-transfer dataclasses named `<Entity>Data`: `CardData`, `RatingData` (`src/db/repository.py`).
- Custom exceptions are named `LLM<Reason>Error` and inherit a common base `LLMError` (`src/llm/exceptions.py`).

## Code Style

**Formatting:**
- No `.prettierrc`, `.eslintrc`, `ruff.toml`, `.flake8`, or `mypy.ini` found in the repo root. There is no enforced/automated linter or formatter — style consistency is maintained by convention/review only. Do not assume `ruff`/`black`/`mypy` gates exist in CI; check before adding tooling-dependent code.
- Consistent 4-space indentation, double-quoted strings, trailing commas in multi-line calls (typical `black`-style formatting) observed throughout `src/`, even though no formatter config is checked in.

**Type Hints:**
- All function signatures use type hints, including return types. Modern union syntax (`str | None`) is used in newer files (`src/llm/client.py`, `src/llm/exceptions.py`), while `Optional[X]` from `typing` is used in older/DB-adjacent files (`src/db/repository.py`, `src/core/analyzer.py`). Both styles coexist — match the surrounding file's style when editing, prefer `X | None` in new code.
- `requires-python = ">=3.11"` in `pyproject.toml`.

## Import Organization

**Order:**
1. Standard library (`import logging`, `from decimal import Decimal`, `from typing import Optional`).
2. Third-party packages (`from aiogram import ...`, `from sqlalchemy import ...`, `from openai import ...`).
3. First-party `src.*` imports, generally ordered by layer (`src.config`, then `src.db.*`, `src.core.*`, `src.llm.*`, `src.vision.*`, `src.reports.*`).
- Imports are alphabetized within each group (see `src/llm/client.py`, `src/bot/handlers/analyze.py`).
- Local/deferred imports are used inside functions to avoid import cycles, e.g. `from src.llm.prompts import build_vision_prompt` inside `LLMClient.recognize_cards` (`src/llm/client.py:295`).

**Path Aliases:**
- None — imports always use the fully qualified `src.` package path (no relative imports observed, no bundler-style aliases since this is a Python project).

## Error Handling

**Custom Exception Hierarchy:**
- Domain-specific exceptions extend a per-module base: `LLMError` → `LLMTimeoutError`, `LLMAPIError` → `LLMRateLimitError`/`LLMServerError`, `LLMParseError` (`src/llm/exceptions.py`). Exceptions carry structured metadata (`status_code`, `retryable`, `timeout`) as attributes, not just message strings.

**Retry Pattern:**
- Network/LLM calls use manual exponential backoff via a private helper (`LLMClient._retry_with_backoff` in `src/llm/client.py`): loop up to `MAX_RETRIES`, catch specific SDK exceptions (`APITimeoutError`, `APIStatusError`, `APIConnectionError`), translate each into a domain exception, `await asyncio.sleep(delay)` with `delay = min(delay * 2, MAX_DELAY)` between attempts, and `raise last_exception` when attempts are exhausted. Non-retryable 4xx errors (except 429) raise immediately via `raise LLMAPIError(...) from e`.

**Bot Handler Pattern:**
- Handlers wrap the main pipeline in `try/except` blocks that catch specific domain exceptions first, then a generic fallback (`src/bot/handlers/analyze.py`):
```python
try:
    ...
except LLMError:
    logger.exception("LLM error during analysis for user %d", db_user.telegram_id)
    await message.answer(format_error(...))
except Exception:
    logger.exception("Unexpected error ...")
    await message.answer(format_error(...))
```
- `logger.exception(...)` (not `logger.error`) is used inside `except` blocks so the traceback is always captured.
- External HTTP calls (e.g. card price lookups) catch narrower exceptions before the generic fallback: `except httpx.TimeoutException`, `except httpx.RequestError as exc`, then `except Exception` (`src/bot/handlers/analyze.py:691-700`).
- User-facing error messages always go through `src.bot.messages.format_error(...)` so Ukrainian error copy is centralized.

**General:**
- Prefer catching the narrowest known exception type first, only falling back to bare `except Exception` as the last branch, always paired with `logger.exception`/`logger.warning` for diagnostics.
- Repository/query methods return `Optional[X]` (or `None`) rather than raising for "not found" cases (e.g. `get_by_code`, `get_by_telegram_id` in `src/db/repository.py`); callers are expected to check for `None`.

## Logging

**Framework:** Standard library `logging`, one `logger = logging.getLogger(__name__)` per module (see `src/core/analyzer.py`, `src/llm/client.py`, `src/bot/handlers/analyze.py`).

**Patterns:**
- Mixed style: f-strings are used in `src/core/analyzer.py` and `src/llm/client.py` (`logger.info(f"Deck analysis: score={score}, ...")`), while `%`-style lazy formatting is used in bot handlers (`logger.info("Fuzzy matching corrected %d card names", total_corrections)`, `logger.exception("LLM error during analysis for user %d", db_user.telegram_id)` in `src/bot/handlers/analyze.py`). Prefer `%`-style lazy args for new logging calls in hot paths to avoid unnecessary string formatting.
- `logger.debug` for verbose per-attempt tracing, `logger.info` for normal lifecycle events, `logger.warning` for recoverable/expected failures (rate limit, timeout on a retryable attempt), `logger.exception` for caught errors surfaced to the user, `logger.error` for terminal/unrecoverable failures after retries exhausted (`src/llm/client.py:163`).

## Comments

**When to Comment:**
- Inline comments explain *why*, not *what* — e.g. `# Non-retryable error (4xx except 429)` (`src/llm/client.py:139`), `# must precede analyze_router (FSM priority)` (`src/bot/handlers/__init__.py:26`).
- Section-divider comments (`# ===== ... =====`) group related fixtures/helpers in larger files, e.g. `tests/conftest.py` (`# LLM Mocking Utilities`, `# Test Data Fixtures`).

**Docstrings:**
- Every module starts with a triple-quoted module docstring summarizing its purpose (1-3 lines), e.g. `src/core/analyzer.py:1-6`, `src/llm/exceptions.py:1-5`.
- Every public class and method has a Google-style docstring with `Args:`, `Returns:`, and (when applicable) `Raises:` sections. See `DeckAnalyzer.analyze` and `LLMClient.call_vision` for the canonical pattern.
- Private helper methods get a short one-line docstring at minimum (e.g. `_get_rating`, `_get_win_rate` in `src/core/analyzer.py`).
- Test module docstrings enumerate the test cases/acceptance criteria they cover using `TC-<id>` identifiers, e.g. `tests/test_core/test_advisor.py:1-9`, `tests/test_bot/test_analyze_photo_routing.py:1-11`. This traceability convention (test case ID → docstring → test class name) should be followed for new test files tied to acceptance criteria.

## Function Design

**Size:** Public entry-point methods (e.g. `DeckAnalyzer.analyze`) stay short and delegate to `_calculate_*` / `_get_*` private helpers — one responsibility per private method.

**Parameters:** Keyword-friendly signatures with typed optional parameters defaulting to `None`; multi-parameter functions/constructors use one parameter per line with trailing comma (`src/llm/client.py:41-48`, `src/db/repository.py:499-509`).

**Return Values:** Consistently typed return values; "not found" is represented as `None` (via `Optional[X]`) rather than exceptions. Bulk-fetch methods return `list[X]` (never `None`), defaulting to `[]`.

## Module Design

**Exports:** No `__all__` lists observed; modules export via plain top-level `class`/`def` definitions. Import consumers reference symbols directly (`from src.llm.exceptions import LLMAPIError, ...`).

**Barrel Files:** `src/bot/handlers/__init__.py` acts as a barrel that aggregates all per-feature routers into a single `get_handlers_router()` — this is the only aggregation pattern in the codebase; other packages (`src/core`, `src/db`, `src/llm`) do not use barrel re-exports, consumers import directly from the concrete submodule.

**Module-level singletons:** A small number of modules keep a private module-level cache variable plus a `get_<x>()` accessor for shared instances that should not be reconstructed per call: `_client` / `get_llm_client()` in `src/llm/client.py`. Use this pattern sparingly and only for stateless/service-like clients.

## Language

All user-facing strings (`src/bot/messages.py`, prompts in `src/llm/prompts.py`, advice output) are in Ukrainian. Code, comments, docstrings, and log messages are in English. When writing new user-facing copy or LLM prompt output, use Ukrainian; keep all developer-facing text in English.

---

*Convention analysis: 2026-09-23*

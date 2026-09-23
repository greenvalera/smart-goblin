# Coding Conventions

**Mapped:** 2026-09-23

## Style
- PEP 8, 4-space indent; no formatter or linter is configured, so style is by convention
- Every module opens with a docstring explaining its purpose; public functions/classes use Google-style docstrings (`Args:` / `Returns:` / `Raises:`)
- Type hints throughout, modern syntax (`list[str]`, `X | None`); `Optional[...]` also common — both styles coexist
- `from __future__ import annotations` is not used; forward refs use strings (`"DeckAnalysis"  # noqa: F821`)
- Money/score values use `Decimal`, not float (ratings, win rates, CMC)

## Language
- **All user-facing text is Ukrainian** (messages, errors, button labels, LLM advice prompts)
- Code, identifiers, logs and docstrings are English (some inline comments in Ukrainian)
- Test-case IDs from specs appear in docstrings/comments, e.g. `TC-P4-1.4`, `TC-P4-3.7`

## Structure patterns
- **Repository pattern**: one class per aggregate, constructed with an `AsyncSession`; handlers open `async with get_session() as session:` per unit of work (commit on exit)
- **Dataclasses** for DTOs between layers (`Deck`, `CardInfo`, `RecognitionResult`, `CardData`, `RatingData`, `DeckReport`)
- **Lazy module singletons** for expensive clients: `get_settings()` (`lru_cache`), `get_engine()`, `get_llm_client()`
- Dependency injection via optional constructor args with shared-instance fallback (`CardRecognizer(llm_client=None)`) — this is what tests hook into
- aiogram: each handler module exposes `router`; the middleware injects `db_user: User` into handler kwargs
- Module-level constants in `UPPER_SNAKE` with a comment explaining the number (thresholds, embargo days, grade offsets)

## Error handling
- Custom exception hierarchies per layer: `LLMError` (`llm/exceptions.py`), `ParserError` / `NetworkError` / `RateLimitError` / `NotFoundError` (`parsers/base.py`)
- Handlers: `try` → `except LLMError` (friendly LLM error) → `except Exception` (`logger.exception` + generic error). Users always get a Ukrainian message, never a traceback
- Background jobs log and continue; they never crash the bot

## Logging
- `logger = logging.getLogger(__name__)` per module
- Mostly %-style lazy args (`logger.info("... %s", x)`); some f-strings in `llm/client.py` and `vision/`
- Log user by `telegram_id`, not username

## Comments
- Comments explain *why*, especially around external data quirks (17lands early-access dates, DFC naming, bonus sheets, embargo). Keep that density when touching parsers

## Git / workflow (from `CLAUDE.md`)
- Tasks tracked in Linear (team `SMA`); use Linear's `gitBranchName`
- Branch off `main` → PR into `main` → deploy to staging via `scripts/deploy-stage.*` → merge after staging passes (auto-deploys prod)

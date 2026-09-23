---
last_mapped_commit: 8366eb8
---
<!-- refreshed: 2026-09-23 -->
# Architecture

**Analysis Date:** 2026-09-23

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Interface Layer                  │
├──────────────────┬──────────────────┬───────────────────────┤
│  Handlers         │  Middlewares     │  Keyboards/Messages   │
│ `src/bot/handlers`│`src/bot/middlewares.py`│`src/bot/keyboards.py`│
│                   │                  │ `src/bot/messages.py` │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                     Business Logic (Core)                    │
│   Deck model / analyzer / advisor / land recommendation      │
│              `src/core/`                                     │
└────────┬─────────────────────────────────┬────────────────────┘
         │                                 │
         ▼                                 ▼
┌────────────────────────┐      ┌───────────────────────────────┐
│  Vision recognition     │      │   LLM client (OpenAI wrapper)  │
│  `src/vision/`          │◄─────┤   `src/llm/`                   │
└────────────────────────┘      └───────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│         Reports (Telegram markdown / HTML rendering)          │
│              `src/reports/`                                   │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│   Data Layer: SQLAlchemy async models + repositories          │
│              `src/db/`  (PostgreSQL)                           │
└─────────────────────────────────────────────────────────────┘
         ▲
         │ (daily cron, independent of Telegram flow)
┌─────────────────────────────────────────────────────────────┐
│   Parsers: Scryfall (cards) + 17lands (ratings) + validator    │
│              `src/parsers/`                                   │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Handlers | Telegram command/photo/callback routing, FSM state control, orchestration of the analyze pipeline | `src/bot/handlers/analyze.py`, `src/bot/handlers/draft.py`, `src/bot/handlers/history.py`, `src/bot/handlers/stats.py`, `src/bot/handlers/start.py` |
| Middleware | Auto-registers Telegram users into DB, injects `db_user` into handler data | `src/bot/middlewares.py` |
| Keyboards/Messages | Inline keyboard builders and Ukrainian UI text/formatting helpers | `src/bot/keyboards.py`, `src/bot/messages.py` |
| Vision recognition | Calls GPT-4o Vision to extract card names from an image, detects layout (Arena screenshot vs physical photo) | `src/vision/recognizer.py`, `src/vision/layouts.py`, `src/vision/prompts.py` |
| Card matcher | Fuzzy-matches recognized (possibly misspelled) card names against known DB card names | `src/vision/card_matcher.py` |
| LLM client | Thin async OpenAI wrapper with retry/backoff and typed exceptions, shared across vision and advisor | `src/llm/client.py`, `src/llm/exceptions.py`, `src/llm/prompts.py` |
| Deck analysis | Pure calculation of deck score, win rate, mana curve, and color distribution from `CardInfo` data (no I/O) | `src/core/analyzer.py`, `src/core/deck.py` |
| Land recommendation | Computes suggested basic-land mix by color-pip weighting | `src/core/lands.py` |
| Advisor | Builds GPT-4o text-advice prompts from a `DeckReport` and calls the LLM client | `src/core/advisor.py` |
| Report building/rendering | Converts analysis + card data into a `DeckReport` and renders it as Telegram Markdown or HTML | `src/reports/models.py`, `src/reports/telegram.py`, `src/reports/html.py` |
| Data access | SQLAlchemy 2.x async ORM models and repository classes (one repo per aggregate) | `src/db/models.py`, `src/db/repository.py`, `src/db/session.py` |
| Parsers | Fetch card metadata (Scryfall) and draft ratings (17lands), upsert into DB, validate freshly stored grades | `src/parsers/scryfall.py`, `src/parsers/seventeen_lands.py`, `src/parsers/base.py`, `src/parsers/grade_validator.py`, `src/parsers/scheduler.py` |
| Configuration | Typed settings loaded from environment via pydantic-settings, cached singleton | `src/config.py` |
| Entry point | Wires bot, DB, scheduler, signal handling, graceful shutdown | `src/main.py` |

## Pattern Overview

**Overall:** Layered architecture with an interface-agnostic core, following a "clean-ish" separation: Telegram-specific code lives only in `src/bot/`; `src/core/` contains pure business logic with zero aiogram/Telegram imports; data access is isolated behind the repository pattern in `src/db/repository.py`.

**Key Characteristics:**
- Fully async (asyncio + aiogram 3.x + SQLAlchemy 2.x async engine + httpx async clients)
- Repository pattern hides SQLAlchemy session/query details from handlers and core logic
- Dataclass-based value objects (`CardInfo`, `Deck`, `DeckAnalysis`, `RecognitionResult`, `CardData`, `RatingData`) move data between layers without leaking ORM models past the DB layer (ORM `Card`/`User` objects are converted to `CardInfo` immediately after fetch — see `_card_to_card_info` in `src/bot/handlers/analyze.py:52` and `src/bot/handlers/draft.py`)
- Scheduler (APScheduler) runs independently of the Telegram polling loop, sharing only the DB session factory and parser modules
- Report generation is decoupled from analysis: `DeckReport.build()` (`src/reports/models.py`) assembles a renderer-agnostic report object that `TelegramRenderer` or an HTML renderer can format independently

## Layers

**Telegram Interface (`src/bot/`):**
- Purpose: Parse Telegram updates, manage FSM state, format user-facing Ukrainian text, invoke core/vision/db layers, send responses
- Location: `src/bot/handlers/`, `src/bot/middlewares.py`, `src/bot/keyboards.py`, `src/bot/messages.py`
- Contains: aiogram Routers, FSM `StatesGroup` classes, callback-query handlers, keyboard builders
- Depends on: `src/core/`, `src/db/`, `src/vision/`, `src/llm/`, `src/reports/`
- Used by: `src/main.py` (via `get_handlers_router()`)

**Business Logic (`src/core/`):**
- Purpose: Deck scoring, win-rate estimation, mana curve, land recommendation, advice-prompt orchestration
- Location: `src/core/analyzer.py`, `src/core/deck.py`, `src/core/lands.py`, `src/core/advisor.py`
- Contains: Pure functions/classes operating on dataclasses; `DeckAdvisor` is the one core class with an external dependency (LLM client)
- Depends on: `src/llm/` (advisor only); otherwise dependency-free
- Used by: `src/bot/handlers/`

**Vision (`src/vision/`):**
- Purpose: Recognize MTG card names from user-submitted images
- Location: `src/vision/recognizer.py`, `src/vision/layouts.py`, `src/vision/prompts.py`, `src/vision/card_matcher.py`
- Contains: Layout detection heuristics, GPT-4o Vision prompt templates, fuzzy name matching against DB card lists
- Depends on: `src/llm/`
- Used by: `src/bot/handlers/analyze.py`, `src/bot/handlers/draft.py`

**LLM (`src/llm/`):**
- Purpose: Single point of contact with OpenAI API (both vision and text completions)
- Location: `src/llm/client.py`, `src/llm/prompts.py`, `src/llm/exceptions.py`
- Contains: `LLMClient` with retry/backoff, `get_llm_client()` shared-singleton accessor, typed `LLMError` hierarchy
- Depends on: `src/config.py` for API key/model settings
- Used by: `src/vision/recognizer.py`, `src/core/advisor.py`

**Data (`src/db/`):**
- Purpose: Schema definition and all persistence operations
- Location: `src/db/models.py` (5 SQLAlchemy models: `Set`, `Card`, `CardRating`, `User`, `Analysis`), `src/db/repository.py` (`SetRepository`, `CardRepository`, `UserRepository`, `AnalysisRepository`), `src/db/session.py` (engine/session factory, `get_session()` async context manager)
- Contains: ORM models, repository classes, upsert helpers, connection URL normalization (Railway `postgres://` → `postgresql+asyncpg://`, `.railway.internal` → public URL fallback for local `railway run`)
- Depends on: PostgreSQL via asyncpg
- Used by: every other layer except `src/vision/` and `src/llm/`

**Parsers (`src/parsers/`):**
- Purpose: Populate and refresh `sets`/`cards`/`card_ratings` from external sources on a daily cron
- Location: `src/parsers/base.py` (abstract `BaseParser`, shared dataclasses, exception hierarchy), `src/parsers/scryfall.py`, `src/parsers/seventeen_lands.py`, `src/parsers/grade_validator.py`, `src/parsers/scheduler.py`
- Contains: HTTP clients (httpx), APScheduler cron job (`create_scheduler()`), a post-update grade-validation pass that re-fetches 17lands and diffs against freshly stored DB grades (logs mismatches, never raises)
- Depends on: `src/db/`, external Scryfall/17lands HTTP APIs
- Used by: `src/main.py` (scheduler wiring), `scripts/add_set.py` (manual seeding), CLI invocation (`python -m src.parsers.scheduler --strict`)

**Reports (`src/reports/`):**
- Purpose: Transform analysis results into user-facing output
- Location: `src/reports/models.py` (`DeckReport`, `CardSummary`, `rating_to_grade()`), `src/reports/telegram.py` (`TelegramRenderer`), `src/reports/html.py`
- Depends on: `src/core/deck.py` dataclasses
- Used by: `src/bot/handlers/analyze.py`, `src/bot/handlers/draft.py`

## Data Flow

### Primary Request Path (`/analyze` + photo)

1. User sends `/analyze` with a photo → routed to `src/bot/handlers/analyze.py` (`router`)
2. `UserRegistrationMiddleware` (`src/bot/middlewares.py:19`) auto-creates/fetches the `User` row and injects `db_user`
3. Image bytes downloaded via `httpx`, passed to `CardRecognizer.recognize_cards()` (`src/vision/recognizer.py:54`) which calls GPT-4o Vision through `src/llm/client.py`
4. Recognized (possibly fuzzy) names passed through `fuzzy_match_cards()` (`src/vision/card_matcher.py`) against the active set's known card names
5. `_run_deck_pipeline()` (`src/bot/handlers/analyze.py:123`) builds a `Deck`, calls `_enrich_cards()` (`analyze.py:91`) to fetch `Card`+`CardRating` rows via `CardRepository.get_cards_with_ratings()` and converts ORM rows to `CardInfo` dataclasses (`_card_to_card_info`, `analyze.py:52`)
6. `DeckAnalyzer.analyze()` (`src/core/analyzer.py:34`) computes score/win-rate/mana-curve/color-distribution (pure, no I/O)
7. `recommend_lands()` (`src/core/lands.py`) computes basic-land suggestion
8. Result persisted via `AnalysisRepository.create()` (`src/db/repository.py`) — advice is `None` at this point (generated later, on demand)
9. `DeckReport.build()` (`src/reports/models.py`) assembles the report; `TelegramRenderer.render()` (`src/reports/telegram.py`) formats Markdown
10. Response sent by editing the "processing" message; an inline keyboard offers an "Отримати поради" (get advice) callback

### Advice-on-Demand Flow

1. User taps "Отримати поради" callback button → callback handler in `analyze.py`/`draft.py`
2. `AnalysisRepository` loads the saved `Analysis` row
3. `DeckAdvisor` (`src/core/advisor.py:37`) builds a prompt from the `DeckReport` and calls `src/llm/client.py` for GPT-4o text completion
4. Advice text is saved back onto the `Analysis` row and re-rendered into the message

### Draft Mode Flow (`/draft`)

1. `/draft` starts an aiogram FSM session (`DraftState`, `src/bot/handlers/draft.py:47`): `waiting_main` → `waiting_sideboard` → `chatting`
2. Main-deck photo recognized/enriched/analyzed the same way as `/analyze`; sideboard photo (or skip) merged in
3. In `chatting` state, free-text messages are answered by the LLM in deck context, capped at `_MAX_CHAT_EXCHANGES = 10` (`draft.py:44`)

### Daily Data Refresh Flow (independent of user requests)

1. `create_scheduler()` (`src/parsers/scheduler.py:173`) registers an APScheduler `CronTrigger` (default 03:00 UTC, configurable via `PARSER_SCHEDULE_HOUR`) started from `src/main.py` only when `PARSER_SCHEDULE_ENABLED=true`
2. `run_updates()` (`scheduler.py:34`) iterates every `Set` row in the DB, fetches card metadata from `ScryfallParser` and ratings from `SeventeenLandsParser`, upserts via `CardRepository`
3. `validate_set_grades()` (`src/parsers/grade_validator.py`) re-fetches 17lands and compares against freshly-persisted DB grades; mismatches logged as warnings only
4. Manual invocation: `python -m src.parsers.scheduler --strict` exits non-zero if any mismatches found (used as a post-deploy gate — see `CLAUDE.md` Railway workflow)
5. New sets are seeded manually via `scripts/add_set.py <CODE>`, not by the scheduler (scheduler only refreshes sets already in the DB)

**State Management:**
- Conversation-level state (multi-photo draft flow, chat mode) lives in aiogram's FSM (`FSMContext`), not in the DB
- Persistent state (users, analyses, card ratings) lives entirely in PostgreSQL via `src/db/models.py`
- No in-memory caching layer; `get_settings()` (`src/config.py:145`) is the only process-wide cached singleton (`lru_cache`)

## Key Abstractions

**Dataclass value objects (core/report boundary):**
- Purpose: Carry data between layers without exposing SQLAlchemy ORM instances outside `src/db/`
- Examples: `CardInfo`, `Deck`, `DeckAnalysis` (`src/core/deck.py`); `RecognitionResult` (`src/vision/recognizer.py:19`); `CardData`, `RatingData` (`src/parsers/base.py` and duplicated as `RepoCardData`/`RepoRatingData` in `src/db/repository.py`)
- Pattern: ORM rows are converted to dataclasses immediately after fetch (see `_card_to_card_info` helpers duplicated in `analyze.py` and `draft.py`)

**Repository pattern:**
- Purpose: One repository class per aggregate root, encapsulating all queries/upserts for that table
- Examples: `SetRepository`, `CardRepository`, `UserRepository`, `AnalysisRepository` in `src/db/repository.py`
- Pattern: Repositories take an `AsyncSession` in their constructor; callers always open sessions via `async with get_session() as session:` (`src/db/session.py:85`)

**Parser abstract base:**
- Purpose: Common interface for external data sources
- Examples: `BaseParser(ABC)` (`src/parsers/base.py:52`), implemented by `ScryfallParser` and `SeventeenLandsParser`
- Pattern: Each parser exposes async fetch methods returning shared dataclasses (`CardData`, `SetData`, `RatingData`); errors raise a typed hierarchy (`ParserError`, `RateLimitError`, `NetworkError`, `NotFoundError`)

**FSM state machines:**
- Purpose: Model multi-step Telegram conversations
- Examples: `DraftState(StatesGroup)` (`src/bot/handlers/draft.py:47`)
- Pattern: States gate which handlers fire; router registration order matters (`draft_router` before `analyze_router` in `src/bot/handlers/__init__.py:26`) so FSM-scoped handlers take priority over generic photo handlers

## Entry Points

**Telegram bot (main process):**
- Location: `src/main.py`
- Triggers: `python -m src.main`
- Responsibilities: Load settings, verify DB connectivity, construct `Bot`/`Dispatcher`, register `UserRegistrationMiddleware`, include the aggregated handler router (`get_handlers_router()`, `src/bot/handlers/__init__.py:17`), conditionally start the APScheduler, register Telegram bot-command menu, run `dp.start_polling(bot)`, handle graceful shutdown (SIGTERM on non-Windows, engine/bot session close in `finally`)

**Manual parser run:**
- Location: `src/parsers/scheduler.py` (`if __name__ == "__main__":` block, line 199)
- Triggers: `python -m src.parsers.scheduler [--strict]`
- Responsibilities: One-shot data refresh outside the bot process; `--strict` mode is used as a production post-deploy validation gate (see `CLAUDE.md`)

**Set seeding script:**
- Location: `scripts/add_set.py`
- Triggers: `python -m scripts.add_set <SET_CODE>`
- Responsibilities: Pulls a new set's cards from Scryfall and ratings from 17lands into a fresh/target DB (used to seed staging Postgres, which the scheduler will not populate on its own)

**Health check script:**
- Location: `scripts/healthcheck.py`
- Triggers: Invoked by deployment tooling (Railway) to verify container health

**Alembic migrations:**
- Location: `migrations/env.py`, `migrations/versions/`
- Triggers: `python -m alembic upgrade head` / `alembic revision --autogenerate`

## Architectural Constraints

- **Threading:** Single-threaded asyncio event loop for the whole bot process; APScheduler's `AsyncIOScheduler` runs jobs on the same event loop (no separate worker threads/processes)
- **Global state:** Two lazily-initialized module-level singletons in `src/db/session.py` — `_engine` and `_session_factory` (lines 23-24) — plus a cached `Settings` singleton via `@lru_cache` in `src/config.py:145`. No other cross-request shared mutable state observed.
- **Circular imports:** None observed; dependency direction is strictly `bot → core/vision/llm/reports → db`, with `parsers → db` as a separate branch not depended on by `bot`
- **Duplicated conversion logic:** `_card_to_card_info()` is defined independently in both `src/bot/handlers/analyze.py:52` and `src/bot/handlers/draft.py` — near-identical ORM-to-dataclass mapping duplicated across two handler modules rather than factored into `src/core/` or `src/db/`
- **Session-per-operation:** Handlers open a fresh `async with get_session() as session:` block for each logical DB operation (enrich, then later save) rather than a single request-scoped session; this is intentional to keep write commits granular but means a deck's read and write happen in separate transactions

## Anti-Patterns

### Duplicated ORM-to-dataclass mapping

**What happens:** `_card_to_card_info()` is copy-pasted (not imported) between `src/bot/handlers/analyze.py` and `src/bot/handlers/draft.py`.
**Why it's wrong:** Any change to `CardInfo` construction (e.g., new field, new rating-selection logic) must be applied in two places or they silently diverge.
**Do this instead:** Move the conversion into `src/core/deck.py` as a classmethod/factory (e.g., `CardInfo.from_card(card: Card)`) or into `src/db/repository.py`, and import it from both handlers.

### Business rules embedded in handler module

**What happens:** Land-type classification helpers (`_is_basic_land`, `_is_nonbasic_land`) live directly in `src/bot/handlers/analyze.py:78-88` rather than in `src/core/`.
**Why it's wrong:** `src/core/` is documented (and largely followed) as the Telegram-independent business-logic layer; leaking these predicates into the handler couples deck-composition logic to the bot layer and makes it untestable without aiogram context.
**Do this instead:** Move `_is_basic_land`/`_is_nonbasic_land` into `src/core/lands.py`, alongside `BASIC_LANDS` and `recommend_lands()`, which already owns land logic.

---

## Error Handling

**Strategy:** Typed exception hierarchies per external boundary, caught at the layer that talks to that boundary; user-facing errors are translated to Ukrainian text via `format_error()` (`src/bot/messages.py`).

**Patterns:**
- LLM errors: `LLMError` hierarchy (`src/llm/exceptions.py`) raised by `src/llm/client.py`, caught in handlers to show a friendly Ukrainian error message
- Parser errors: `ParserError`/`RateLimitError`/`NetworkError`/`NotFoundError` (`src/parsers/base.py:101-119`) caught individually per-set in `run_updates()` (`src/parsers/scheduler.py:106-109`, `142-145`) so one set's failure doesn't abort the whole daily run
- DB session errors: `get_session()` (`src/db/session.py:85`) rolls back on any exception and re-raises — callers do not need their own try/except around session blocks for rollback purposes

## Cross-Cutting Concerns

**Logging:** Standard library `logging`, configured once in `src/main.py:setup_logging()` with a consistent format (`%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`); third-party loggers (`apscheduler`, `httpx`) silenced to WARNING. `LOG_LEVEL` env var controls global level and also toggles SQLAlchemy `echo=True` in `src/db/session.py:58`.

**Validation:** Pydantic (via `pydantic-settings`) validates environment configuration at startup (`src/config.py`); DB-level `CheckConstraint`/`UniqueConstraint` enforce data integrity (`src/db/models.py`); a dedicated post-update grade validator (`src/parsers/grade_validator.py`) cross-checks parser output against persisted data.

**Authentication:** No user authentication beyond Telegram's own identity (`telegram_id`); `UserRegistrationMiddleware` auto-provisions users on first contact. No admin/role system observed.

---

*Architecture analysis: 2026-09-23*

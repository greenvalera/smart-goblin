---
last_mapped_commit: 8366eb8
---
# Codebase Structure

**Analysis Date:** 2026-09-23

## Directory Layout

```
smart-goblin/
├── src/                        # Application source (all business/interface code)
│   ├── main.py                 # Entry point: python -m src.main
│   ├── config.py               # pydantic-settings configuration (Settings, get_settings())
│   ├── bot/                    # Telegram interface layer (aiogram 3.x)
│   │   ├── handlers/           # Command/photo/callback routers, one file per feature
│   │   │   ├── __init__.py     # get_handlers_router() — aggregates + orders sub-routers
│   │   │   ├── analyze.py      # /analyze + bare-photo pipeline (largest handler)
│   │   │   ├── draft.py        # /draft multi-photo FSM flow + chat mode
│   │   │   ├── history.py      # /history — past analyses
│   │   │   ├── stats.py        # /stats <card name>
│   │   │   └── start.py        # /start, /help, /set
│   │   ├── middlewares.py      # UserRegistrationMiddleware
│   │   ├── keyboards.py        # Inline keyboard builders
│   │   └── messages.py         # Ukrainian UI text templates, format_error()
│   ├── core/                   # Telegram-independent business logic
│   │   ├── deck.py             # CardInfo, Deck, DeckAnalysis dataclasses
│   │   ├── analyzer.py         # DeckAnalyzer — score/win-rate/mana-curve/colors
│   │   ├── advisor.py          # DeckAdvisor — LLM-backed text advice
│   │   └── lands.py            # BASIC_LANDS, recommend_lands()
│   ├── vision/                 # GPT-4o Vision card recognition
│   │   ├── recognizer.py       # CardRecognizer, RecognitionResult
│   │   ├── layouts.py          # LayoutType detection (Arena screenshot vs photo)
│   │   ├── prompts.py          # Vision prompt templates
│   │   └── card_matcher.py     # fuzzy_match_cards() against known DB names
│   ├── llm/                    # OpenAI client wrapper
│   │   ├── client.py           # LLMClient, get_llm_client() (shared singleton)
│   │   ├── prompts.py          # Text-advice / chat prompt templates
│   │   └── exceptions.py       # LLMError hierarchy
│   ├── parsers/                # External data ingestion (Scryfall + 17lands)
│   │   ├── base.py             # BaseParser(ABC), shared dataclasses, ParserError hierarchy
│   │   ├── scryfall.py         # ScryfallParser — card metadata
│   │   ├── seventeen_lands.py  # SeventeenLandsParser — draft ratings
│   │   ├── grade_validator.py  # Post-update grade cross-check (validate_set_grades)
│   │   └── scheduler.py        # APScheduler cron wiring + run_updates() + CLI entry
│   ├── db/                     # Persistence layer
│   │   ├── models.py           # SQLAlchemy 2.x models: Set, Card, CardRating, User, Analysis
│   │   ├── repository.py       # SetRepository, CardRepository, UserRepository, AnalysisRepository
│   │   └── session.py          # get_engine(), get_session_factory(), get_session(), close_engine()
│   └── reports/                # Output formatting
│       ├── models.py           # DeckReport, CardSummary, rating_to_grade()
│       ├── telegram.py         # TelegramRenderer (Markdown)
│       └── html.py             # HTML renderer
├── tests/                      # pytest test suite, mirrors src/ layout
│   ├── conftest.py             # Shared fixtures (testcontainers Postgres, LLM mocks)
│   ├── fixtures/                # Static test fixture data
│   ├── integration/             # Cross-layer integration tests
│   ├── test_bot/                # Tests for src/bot/
│   ├── test_core/                # Tests for src/core/
│   ├── test_db/                  # Tests for src/db/
│   ├── test_llm/                 # Tests for src/llm/
│   ├── test_parsers/              # Tests for src/parsers/
│   ├── test_scripts/              # Tests for scripts/
│   └── test_vision/               # Tests for src/vision/
├── scripts/                    # Standalone operational scripts (not part of src package)
│   ├── add_set.py               # Seed a new set (python -m scripts.add_set <CODE>)
│   ├── healthcheck.py           # Deployment health check
│   ├── dev-db.ps1 / dev-db.sh    # Local Postgres dev container management
│   ├── deploy-stage.ps1 / .sh    # One-command staging deploy (force-push to `stage`)
│   └── start.sh                  # Container startup script (must be LF line endings)
├── migrations/                  # Alembic migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                 # One file per migration
├── doc/                          # Design docs (ARCHITECTURE.md, CONCEPT.md) — not task tracking
├── .planning/codebase/            # GSD-generated codebase maps (this document's home)
└── .venv/                         # Python virtual environment (Windows: run via powershell.exe)
```

## Directory Purposes

**`src/bot/`:**
- Purpose: Everything that touches Telegram/aiogram directly
- Contains: Routers, FSM state groups, middleware, keyboard builders, UI text
- Key files: `src/bot/handlers/__init__.py` (router aggregation/ordering), `src/bot/handlers/analyze.py` (main pipeline, ~719 lines — largest file in the codebase)

**`src/core/`:**
- Purpose: Pure business logic with no Telegram or HTTP dependencies (except `advisor.py`, which calls the LLM client)
- Contains: Dataclasses and calculation classes
- Key files: `src/core/deck.py` (shared value objects used across bot/vision/reports)

**`src/vision/`:**
- Purpose: Turn an image into a list of card names
- Contains: Prompt templates, layout heuristics, fuzzy matching
- Key files: `src/vision/recognizer.py`

**`src/llm/`:**
- Purpose: Single shared OpenAI integration point for both vision and text generation
- Contains: Retrying async client, typed exceptions
- Key files: `src/llm/client.py`

**`src/parsers/`:**
- Purpose: Keep `cards`/`card_ratings` tables fresh from Scryfall and 17lands
- Contains: HTTP-fetching parser classes, APScheduler cron setup, CLI entry point
- Key files: `src/parsers/scheduler.py` (also runnable standalone), `src/parsers/base.py` (shared abstractions)

**`src/db/`:**
- Purpose: All schema definitions and query/upsert logic
- Contains: ORM models, repositories, session/engine management
- Key files: `src/db/models.py`, `src/db/repository.py`

**`src/reports/`:**
- Purpose: Turn analysis results into user-facing text/markup
- Contains: Report dataclasses, renderers (Telegram Markdown, HTML)
- Key files: `src/reports/models.py`

**`tests/`:**
- Purpose: pytest suite, directory structure mirrors `src/` (`test_bot/` ↔ `src/bot/`, etc.)
- Contains: Unit and integration tests; uses real PostgreSQL via testcontainers (no DB mocking)
- Key files: `tests/conftest.py` (fixtures: `db_session`, `clean_session`, `sample_deck_data`, `create_mock_vision_response()`, `create_mock_advice_response()`)

**`scripts/`:**
- Purpose: Operational tooling run outside the bot process (seeding, deployment, health checks)
- Contains: Python scripts (run as `python -m scripts.<name>`) and PowerShell/bash deployment scripts
- Key files: `scripts/add_set.py`, `scripts/deploy-stage.ps1`/`scripts/deploy-stage.sh`

**`migrations/`:**
- Purpose: Alembic schema migration history
- Contains: One versioned migration file per schema change under `migrations/versions/`
- Generated: `versions/` files generated by `alembic revision --autogenerate`, committed to git

**`doc/`:**
- Purpose: Static human-authored design docs (`ARCHITECTURE.md`, `CONCEPT.md`), predates the GSD codebase-map system
- Note: Task tracking has moved to Notion per `CLAUDE.md`; do not add task files here

**`.planning/codebase/`:**
- Purpose: GSD-generated, regenerable codebase maps (this file and its siblings STACK.md, INTEGRATIONS.md, CONVENTIONS.md, TESTING.md, CONCERNS.md when present)

## Key File Locations

**Entry Points:**
- `src/main.py`: Bot process entry point (`python -m src.main`)
- `src/parsers/scheduler.py`: Manual/standalone parser run (`python -m src.parsers.scheduler [--strict]`)
- `scripts/add_set.py`: New-set seeding (`python -m scripts.add_set <CODE>`)

**Configuration:**
- `src/config.py`: All typed settings (`Settings`, `DatabaseSettings`, `TelegramSettings`, `OpenAISettings`, `ParserSettings`)
- `.env` (not committed): Local environment variables — see `.env.example` for the documented shape
- `migrations/env.py`: Alembic environment config

**Core Logic:**
- `src/core/analyzer.py`: Deck scoring algorithm
- `src/core/advisor.py`: LLM advice generation
- `src/bot/handlers/analyze.py`: Main orchestration pipeline (recognize → enrich → analyze → save → render)

**Testing:**
- `tests/conftest.py`: Shared fixtures
- `tests/integration/`: Cross-layer flows
- `tests/test_<module>/`: Mirrors each `src/<module>/` directory 1:1

## Naming Conventions

**Files:**
- Snake_case Python module names matching their primary responsibility (`grade_validator.py`, `card_matcher.py`, `seventeen_lands.py`)
- Test files: `test_<module_under_test>.py`, placed under `tests/test_<package>/` mirroring `src/<package>/`

**Directories:**
- `src/<layer>/` — one directory per architectural layer, named after its responsibility (`bot`, `core`, `vision`, `llm`, `parsers`, `db`, `reports`)
- `src/bot/handlers/` — one file per Telegram command/feature area, not per model

**Classes:**
- PascalCase, suffixed by role: `*Repository` (data access), `*Parser` (external fetchers), `*Renderer` (output formatting), `*Analyzer`/`*Advisor`/`*Recognizer` (core operations), `*Settings` (config), `*Error`/`*Exception` (exceptions), `*State`/`StatesGroup` (FSM)

**Functions:**
- snake_case; private/module-internal helpers prefixed with a single underscore (`_card_to_card_info`, `_enrich_cards`, `_is_basic_land`)
- Async functions use the same snake_case convention; no special `async_` prefix

**Dataclasses:**
- PascalCase nouns representing a single record shape crossing a layer boundary (`CardInfo`, `CardData`, `RatingData`, `RecognitionResult`, `DeckReport`, `CardSummary`)

## Where to Add New Code

**New Telegram command/feature:**
- Handler: new file in `src/bot/handlers/<feature>.py` exposing a module-level `router = Router()`, then register it in `get_handlers_router()` in `src/bot/handlers/__init__.py` (mind ordering if the feature uses FSM state — FSM-scoped routers must precede generic photo/text handlers)
- If the feature needs new business rules, add them to `src/core/` (not inline in the handler) so they stay Telegram-independent and unit-testable
- Tests: `tests/test_bot/test_<feature>.py`

**New external data source (parser):**
- Implementation: new file in `src/parsers/`, subclassing `BaseParser` (`src/parsers/base.py:52`) and returning the shared `CardData`/`RatingData`/`SetData` dataclasses
- Wire into `run_updates()` in `src/parsers/scheduler.py` if it should run on the daily cron
- Tests: `tests/test_parsers/`

**New DB table/model:**
- Model: add to `src/db/models.py`, following the existing `Mapped[...]`/`mapped_column` style with explicit `__table_args__` for constraints/indexes
- Repository: add a new `<Entity>Repository` class in `src/db/repository.py` (constructor takes `AsyncSession`); do not query the ORM directly from handlers or core
- Migration: `alembic revision --autogenerate -m "description"`, review the generated file under `migrations/versions/` before committing
- Tests: `tests/test_db/`

**New report format:**
- Add a new renderer module in `src/reports/` (parallel to `telegram.py`/`html.py`) consuming the existing `DeckReport` dataclass from `src/reports/models.py` — do not add format-specific fields to `DeckReport` itself

**Shared/cross-cutting utilities:**
- Genuinely cross-layer helpers (e.g., dataclass-conversion helpers currently duplicated between `analyze.py` and `draft.py`) belong in `src/core/deck.py` or as classmethods on the relevant dataclass, not copy-pasted per handler

**Operational scripts:**
- Add to `scripts/` as a standalone module runnable via `python -m scripts.<name>`; keep DB/API access going through `src/db/` and `src/parsers/` rather than reimplementing

## Special Directories

**`migrations/versions/`:**
- Purpose: Alembic-generated migration scripts, one per schema change
- Generated: Yes (via `alembic revision --autogenerate`)
- Committed: Yes

**`__pycache__/` (throughout `src/`, `tests/`, `scripts/`, `migrations/`):**
- Purpose: Python bytecode cache
- Generated: Yes
- Committed: No

**`.venv/`:**
- Purpose: Project virtual environment; all Python/pytest/alembic commands must run through it via `powershell.exe -Command` on Windows (see `CLAUDE.md`)
- Generated: Yes (via `python -m venv`)
- Committed: No

**`.pytest_cache/`:**
- Purpose: pytest's internal cache
- Generated: Yes
- Committed: No

**`.claude/`:**
- Purpose: Claude Code project configuration (agents, commands, GSD workflow tooling)
- Generated: Partially (GSD scaffolding); tracked in git per current status (untracked at time of writing)
- Committed: Project-dependent — check `.gitignore` before assuming

---

*Structure analysis: 2026-09-23*

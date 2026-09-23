# Architecture

**Mapped:** 2026-09-23

## Pattern
Layered async monolith, single process. One `python -m src.main` process runs:
1. aiogram long-polling dispatcher (user traffic)
2. APScheduler `AsyncIOScheduler` on the same event loop (daily data refresh)

```
Telegram ──► bot/ (handlers, middleware, keyboards, messages)
               │
               ├─► vision/  (CardRecognizer, fuzzy card_matcher) ──► llm/ (OpenAI)
               ├─► core/    (DeckAnalyzer, DeckAdvisor, lands)    ──► llm/
               ├─► reports/ (DeckReport → TelegramRenderer / HTMLRenderer)
               └─► db/      (repositories over async SQLAlchemy)
                               ▲
parsers/scheduler (cron) ──────┘  Scryfall + 17lands → sets/cards/card_ratings
```

`core/` has no Telegram imports; handlers are the orchestration layer. In practice much of the orchestration (set resolution, fuzzy matching, land recommendation, persistence) lives in the handler modules rather than a service layer.

## Entry points
- `src/main.py` — bot + scheduler; verifies DB (`SELECT 1`), registers `UserRegistrationMiddleware` on messages and callbacks, sets bot commands, handles SIGTERM
- `src/parsers/scheduler.py` — also runnable as `python -m src.parsers.scheduler [--strict]`
- `scripts/add_set.py` — seed a set
- `scripts/start.sh` — migrations then bot

## Request flows

### `/analyze` + photo (`bot/handlers/analyze.py::_run_analysis`)
1. Download largest photo
2. Resolve set: command arg → FSM `set_override` → `users.active_set_code` → vision-detected set
3. If set known: load card names (`CardRepository.get_card_names_by_set`, includes child bonus sets + DFC front faces) to constrain the vision prompt
4. `CardRecognizer.recognize_cards()` → one GPT-4o vision call returning JSON (`main_deck`, `sideboard`, `detected_set`, `layout_detected`, `lands_visible`)
5. `fuzzy_match_cards()` (difflib, cutoff 0.75) corrects names against the known list
6. `_run_deck_pipeline`: enrich from DB (`get_cards_with_ratings`) → `DeckAnalyzer.analyze()` → `recommend_lands()` → `AnalysisRepository.create()` (advice empty) → `DeckReport.build()` → `TelegramRenderer.render()` → edit the "processing" message
7. Advice is **on demand**: `get_advice:{id}` callback → `DeckAdvisor.generate_advice()` → cached in `analyses.advice`

### Bare photo (`handle_photo_without_command`)
Smart routing: 1 card and no sideboard → single-card stats (grade, WR, CMC, variant via Scryfall, price button); 3+ cards → full deck pipeline; otherwise ask the user to clarify.

### `/draft` (FSM, `bot/handlers/draft.py`)
`waiting_main` (photo) → `waiting_sideboard` (photo or "skip") → report + advice → `chatting` (free-text Q&A with deck context in the system prompt, history capped at 10 exchanges, stored in FSM data). `draft_router` is registered before `analyze_router` so FSM-state photo handlers win over the generic photo handler.

### Other commands
- `/history` — list, detail, delete analyses (`history.py`)
- `/stats <name>` — card grade/WR lookup (`stats.py`)
- `/set <CODE|reset>` — writes both FSM `set_override` and `users.active_set_code`

### Daily refresh (`scheduler.run_updates`)
For every row in `sets`: Scryfall cards upsert → (skip if under 12-day embargo) → 17lands ratings → seed bonus-sheet cards found only in 17lands feed → upsert ratings → `validate_set_grades` report. Errors are logged per set, never raised.

## Key abstractions
| Abstraction | Location | Notes |
|---|---|---|
| `Settings` (+ sub-settings) | `src/config.py` | `lru_cache`d `get_settings()` |
| Engine / session | `src/db/session.py` | lazy globals; `get_session()` async CM auto-commits / rolls back |
| Repositories | `src/db/repository.py` | `SetRepository`, `CardRepository`, `UserRepository`, `AnalysisRepository`; take an `AsyncSession` |
| `LLMClient` | `src/llm/client.py` | module singleton `get_llm_client()` |
| `CardRecognizer`, `RecognitionResult` | `src/vision/recognizer.py` | prompt built in `vision/prompts.py` by layout / single-card mode |
| `Deck`, `CardInfo`, `DeckAnalysis` | `src/core/deck.py` | plain dataclasses passed between layers |
| `DeckAnalyzer` | `src/core/analyzer.py` | games-played-weighted average rating/WR; defaults 3.0 / 50% for unrated |
| `DeckAdvisor` | `src/core/advisor.py` | pre-computes weak cards, strong SB cards, curve warnings, land rec → Ukrainian LLM prompt |
| `recommend_lands` | `src/core/lands.py` | pip counting (incl. hybrid / Phyrexian) → basic land split for 40-card deck |
| `DeckReport` / renderers | `src/reports/` | `rating_to_grade` shared by Telegram + HTML output |
| Parsers | `src/parsers/base.py` | `BaseParser`, `CardData`, `SetData`, `RatingData`, `ParserError` hierarchy |

## Data model (`src/db/models.py`)
- `sets` (code unique, `parent_set_code` self-FK for bonus sheets like SOA → SOS)
- `cards` (unique `name`+`set_id`; DFC/split cards stored as `"Front // Back"`)
- `card_ratings` (unique `card_id`+`source`+`format`; rating on a 0–5 scale mapped from letter grades)
- `users` (`telegram_id`, `active_set_code`, `language` default `uk`)
- `analyses` (JSONB `main_deck`/`sideboard`, score, WR, cached `advice`)

Migrations: 3 Alembic revisions (initial schema, `active_set_code`, `parent_set_code`).

## Cross-cutting
- **Logging**: stdlib `logging`, format set in `main.setup_logging`; module-level `logger = logging.getLogger(__name__)`
- **Errors**: handlers catch `LLMError` → `format_error("llm")`, and `Exception` → `format_error("general")`; parser/scheduler swallow and log
- **i18n**: none — Ukrainian strings are inline in handlers, `bot/messages.py`, and prompts
- **Name normalisation**: `normalize_card_name` in `parsers/seventeen_lands.py` is reused by `vision/card_matcher.py`

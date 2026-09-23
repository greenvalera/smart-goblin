# Concerns & Technical Debt

**Mapped:** 2026-09-23

Ordered roughly by impact. File refs are `path:line` at the time of mapping.

## Bugs / likely-broken behaviour
1. **Dead "repeat" button**: `src/bot/keyboards.py:155` emits `callback_data="repeat:{id}"`, but no handler matches `repeat:`. Pressing it leaves the Telegram spinner running until it times out.
2. **FSM set override is wiped before it is read**: `handle_analyze_with_photo` calls `state.clear()` (`analyze.py:~440`) and then `_run_analysis` reads `fsm_data.get("set_override")`. So the FSM tier of the documented priority order never applies. `/set` also persists to `users.active_set_code`, which hides the problem.
3. **FSM state lives in memory**: `Dispatcher()` is built without a storage, so aiogram's `MemoryStorage` is used. Every deploy or restart drops in-progress `/draft` sessions and chat history.
4. **Parse-mode mismatch**: the bot defaults to `ParseMode.HTML` (`main.py`), while handlers send legacy `Markdown`. LLM advice and draft-chat replies go out as `parse_mode="Markdown"` without escaping (`analyze.py` `_send_advice`, `draft.py` chat). A stray `_`, `*` or `[` from the model makes Telegram reject the edit, and the user gets the generic error.
5. **Ambiguous "best" rating**: `_card_to_card_info` takes `card.ratings[0]`, but the relationship has no `order_by`. With more than one source/format, the rating it picks is arbitrary.
6. **`ilike` built from recognised names**: `Card.name.ilike(f"{name} // %")` (`repository.py`) doesn't escape `%` or `_`. It's harmless for real card names, but a garbled vision output could match the wrong card.
7. **Foil/variant price is ignored**: `_fetch_card_price` has TODOs (`analyze.py:730-732`). The price shown is always the default printing's.

## Duplication
- `_card_to_card_info` and `_is_basic_land` are copied between `bot/handlers/analyze.py` and `bot/handlers/draft.py`. The recognise → fuzzy-match → enrich → analyse → land-rec → save → render pipeline is also implemented twice.
- `DATABASE_URL` normalisation happens in both `config.DatabaseSettings.validate_url` and `db/session._get_database_url`. `session.py` reads `os.getenv` directly and bypasses `Settings`, and only `session.py` has the `DATABASE_PUBLIC_URL` fallback.
- There are two vision prompt stacks. `llm/prompts.build_vision_prompt` plus `LLMClient.recognize_cards` / `generate_advice` are unused by production code, which uses `vision/prompts.py` and `DeckAdvisor`.
- There are two grade tables: `GRADE_TO_RATING` (`parsers/seventeen_lands.py`) and `_GRADE_THRESHOLDS` (`reports/models.py`). A comment says they must stay aligned, but no test enforces it.

## Dead / unused code
- `beautifulsoup4` and `lxml` are in requirements but never imported.
- `CardRecognizer.recognize_cards_two_pass` and `detect_layout` aren't called from any handler.
- `HTMLRenderer` is exported but not used by the bot.
- `DeckAnalysis.score` is documented as "1.0-5.0", but ratings are on a 0–5 scale (F = 0.0). Only the docstring is wrong.

## Architecture / maintainability
- **Fat handlers**: `bot/handlers/analyze.py` is about 840 lines and mixes Telegram I/O, set resolution, fuzzy matching, DB writes, Scryfall HTTP and formatting. Pulling out an interface-agnostic `core` service would fix the duplication above and make the "interface-agnostic core" claim true.
- **Scheduler shares the bot's event loop**: a slow 17lands or Scryfall refresh at 03:00 UTC runs in the same process as user traffic. The whole refresh also runs inside **one DB session/transaction** (`scheduler.run_updates`), so a late failure can roll back earlier sets' upserts.
- **Hardcoded Scryfall URL** in `parsers/scryfall_variants.py` ignores `SCRYFALL_API_BASE`. `_fetch_card_price` and `get_card_variants` create a new `httpx.AsyncClient` per call.
- **Grade formula reverse-engineered from the 17lands frontend** (`_GRADE_OFFSET = 11/6`, `MIN_CARDS_FOR_STATS = 15`). It will silently drift if 17lands changes its bundle; `grade_validator` logs mismatches but only fails under `--strict`.
- **Unpinned dependencies** with no lockfile. The Docker build takes whatever is latest (the OpenAI SDK and aiogram majors are the main risk).
- `python-dotenv` is imported directly but only installed transitively.

## Tooling / process gaps
- No CI pipeline, linter, formatter or type checker.
- Tests build the schema with `Base.metadata.create_all`, not Alembic, so a model change without a migration would pass tests and fail in production.
- `AGENTS.md` is a hand-maintained near-copy of `CLAUDE.md`, and the two have already started to diverge (task tracker section).
- The Windows-only command examples in `CLAUDE.md` don't apply to Linux/cloud sessions.

## Security / cost
- There's no per-user rate limit on photo analysis or draft chat. Every photo is a `detail: high` GPT-4o vision call, and every chat message is a completion, so one user can run up OpenAI spend.
- `/set` accepts any string as a set code and stores it without checking it against `sets`. It's harmless, but it leads to confusing "card not found" replies.
- Draft chat forwards arbitrary user text to the LLM with the deck in the system prompt. The prompt-injection impact is low because there are no tools or secrets in context.

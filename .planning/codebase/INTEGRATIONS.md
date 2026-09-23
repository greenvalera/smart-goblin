# External Integrations

**Mapped:** 2026-09-23

## Telegram Bot API (aiogram)
- Long polling (`dp.start_polling`) — one consumer per token, hence separate staging bot
- Default parse mode set to `HTML` in `src/main.py`, but most handlers pass `parse_mode="Markdown"` explicitly
- Commands registered at startup: `/start /help /analyze /draft /history /stats /set`
- Photos downloaded via `bot.get_file` + `bot.download_file` (largest size)
- FSM uses aiogram's default **in-memory storage** (no Redis) — draft sessions and `/set` FSM overrides are lost on restart
- Callback data prefixes: `get_advice:`, `view_advice:`, `card_price:`, `history:`, `details:`, `delete:`, `skip_sideboard`, `repeat:` (no handler — see CONCERNS)

## OpenAI
- Wrapper: `src/llm/client.py` (`LLMClient`, shared via `get_llm_client()`)
- Models from env: `OPENAI_MODEL` (text, default `gpt-4o`), `OPENAI_VISION_MODEL` (default `gpt-4o`)
- Vision: base64 `data:image/jpeg` URL, `detail: high`, `response_format=json_object`, `max_completion_tokens=4096`
- Completion: `max_completion_tokens=2048`, default system prompt `ADVICE_SYSTEM_PROMPT`
- Retry: 3 attempts, exponential backoff 1s → 10s cap, on timeout / 429 / 5xx / connection errors; other 4xx fail fast
- Errors mapped to `src/llm/exceptions.py` (`LLMError` hierarchy)
- Used by: `vision/recognizer.py`, `vision/layouts.py`, `core/advisor.py`, draft chat in `bot/handlers/draft.py`

## Scryfall (`https://api.scryfall.com`)
- `src/parsers/scryfall.py` — `ScryfallParser`: set info, paginated set cards, card by id/name, search; client-side rate limiter (10 req/s)
- `src/parsers/scryfall_variants.py` — frame-variant lookup (`/cards/search`) to resolve showcase/borderless/etc.; **hardcoded base URL**, ignores `SCRYFALL_API_BASE`
- `bot/handlers/analyze.py::_fetch_card_price` — `/cards/named?exact=&set=` for live prices; creates a fresh `httpx.AsyncClient` per call
- `scheduler.py` pulls bonus-sheet cards by the Scryfall UUID embedded in 17lands image URLs

## 17lands (`https://www.17lands.com`)
- `src/parsers/seventeen_lands.py` — `SeventeenLandsParser.fetch_ratings(set_code, main_set_card_names=...)`
- Grades computed locally by reproducing 17lands' frontend z-score → letter-grade formula (`z_score_to_grade`, `_GRADE_OFFSET = 11/6`)
- **Embargo**: no ratings fetched for the first 12 days after Scryfall release date (`EMBARGO_DAYS`, per 17lands usage guidelines)
- "Starved feed" guard: if the response has cards but no win rates, the upsert is skipped to keep existing ratings
- `grade_validator.py` re-fetches after each upsert and logs DB vs 17lands grade mismatches (WARNING only; `--strict` CLI gates exit code)

## PostgreSQL
- `DATABASE_URL` normalised from `postgres://` / `postgresql://` to `postgresql+asyncpg://` (both in `config.py` and `db/session.py`)
- `db/session.py` swaps to `DATABASE_PUBLIC_URL` when the URL points at `*.railway.internal` (for `railway run` locally)
- Railway provides a separate Postgres plugin per environment

## Railway
- CLI (`railway`) used for logs, ssh, deploy polling; see `CLAUDE.md` for workflow
- Staging deploy = force-push to `stage` branch via `scripts/deploy-stage.*`

## Environment variables
| Var | Required | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | |
| `OPENAI_API_KEY` | yes | |
| `DATABASE_URL` | yes | read by both pydantic settings and raw `os.getenv` |
| `DATABASE_PUBLIC_URL` | no | fallback for `.railway.internal` |
| `OPENAI_MODEL`, `OPENAI_VISION_MODEL` | no | default `gpt-4o` |
| `LOG_LEVEL` | no | `DEBUG` also enables SQLAlchemy echo |
| `SCRYFALL_API_BASE`, `SEVENTEENLANDS_BASE` | no | |
| `PARSER_SCHEDULE_ENABLED`, `PARSER_SCHEDULE_HOUR` | no | default on, 03:00 UTC |

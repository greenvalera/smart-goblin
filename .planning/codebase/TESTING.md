# Testing

**Mapped:** 2026-09-23

## Framework
- `pytest` + `pytest-asyncio` in **auto** mode; loop scope is `session` for both fixtures and tests (`pyproject.toml`)
- Real **PostgreSQL 15** via `testcontainers` (`postgres:15-alpine`) — **Docker must be available**; the DB is not mocked
- Coverage: `pytest --cov=src --cov-report=html`

## Layout
```
tests/
├── conftest.py
├── fixtures/                 # real deck screenshots (ecl_deck.jpg, ecl_sideboard.jpg)
├── integration/              # multi-layer flows with mocked LLM/HTTP, real DB
├── test_bot/                 # handler behaviour (routing, draft FSM, advice indicator, prices, fallbacks, messages)
├── test_core/                # advisor, lands
├── test_db/                  # parent_set_code behaviour
├── test_llm/                 # retry/backoff/error mapping
├── test_parsers/             # 17lands grade math, scryfall variants, grade validator
├── test_scripts/             # add_set --parent
├── test_vision/              # recognizer, fuzzy matcher, foil/variant detection
└── test_config.py
```
23 test modules, roughly 10k lines; the biggest are `test_vision/test_recognizer.py`, `integration/test_photo_analysis.py`, `test_bot/test_draft_handler.py`.

## Key fixtures (`tests/conftest.py`)
| Fixture | Scope | Purpose |
|---|---|---|
| `postgres_container`, `database_url` | session | container + asyncpg URL |
| `mock_env_session` | session | patches `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `DATABASE_URL`, etc. |
| `db_engine` | session | `Base.metadata.create_all` (**not** Alembic) and `drop_all` at the end |
| `session_factory` | session | |
| `db_session` | function | session rolled back after the test |
| `clean_session` | function | truncates all tables first |
| `mock_env` | function | env vars without DB |
| `sample_card_names`, `sample_deck_data`, `sample_image_bytes` | function | data |
| `create_mock_vision_response()`, `create_mock_advice_response()` | helpers | build fake OpenAI payloads |

A custom `event_loop` fixture is still defined; newer pytest-asyncio versions deprecate it.

## Mocking style
- `unittest.mock` (`patch`, `AsyncMock`, `MagicMock`), about 400 usages; no `respx`/`pytest-httpx`
- LLM mocked at the `LLMClient.call_vision` / `call_completion` level or by injecting a mock client into `CardRecognizer` / `DeckAdvisor`
- aiogram `Message` / `CallbackQuery` / `FSMContext` are mocked; handlers are called directly as coroutines
- Handlers that call `get_session()` get it patched to yield the test session
- `pytest.mark.parametrize` is rarely used; tests are mostly explicit functions/classes

## Running
```bash
# Windows (per CLAUDE.md)
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest"
# Linux / cloud
python -m pytest tests/ -v
```

## Gaps
- **No CI** — there is no `.github/workflows` or other pipeline, so tests only run when someone runs them locally
- Schema is created with `create_all`, so migration drift from `models.py` isn't caught
- No test for the `repeat:` callback (it has no handler), `HTMLRenderer` wiring, or `scheduler.create_scheduler`
- `test_core` covers advisor and lands; `DeckAnalyzer` is only covered indirectly via integration tests

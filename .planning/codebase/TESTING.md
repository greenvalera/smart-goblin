---
last_mapped_commit: 8366eb8
---

# Testing Patterns

**Analysis Date:** 2026-09-23

## Test Framework

**Runner:**
- `pytest>=8.0` with `pytest-asyncio>=0.23`. Config lives in `[tool.pytest.ini_options]` inside `pyproject.toml` (no separate `pytest.ini`).
- `asyncio_mode = "auto"` — async `def test_*` functions do NOT need `@pytest.mark.asyncio` for auto-detection to work, but the codebase still applies `@pytest.mark.asyncio` explicitly in most files (e.g. `tests/test_core/test_advisor.py`) — follow existing per-file convention when adding tests to that file.
- `asyncio_default_fixture_loop_scope = "session"` and `asyncio_default_test_loop_scope = "session"` — async fixtures/tests share one session-scoped event loop by default.
- `testpaths = ["tests"]`, `python_files = ["test_*.py"]`, `python_functions = ["test_*"]`.

**Assertion Library:** Plain `assert` statements (pytest's assertion rewriting); no separate assertion library.

**Test Database:** Real PostgreSQL via `testcontainers>=4.0` (`testcontainers.postgres.PostgresContainer("postgres:15-alpine")`) — the DB layer is never mocked. Container is spun up once per test session (`tests/conftest.py:postgres_container`, session-scoped).

**Run Commands (per CLAUDE.md, run through the project venv on Windows):**
```bash
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest"
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest --cov=src --cov-report=html"
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest tests/test_vision/test_recognizer.py"
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest tests/ -v"
```
Note: the full suite spins up a real PostgreSQL container via testcontainers (requires Docker running locally). Do not run the suite as part of codebase mapping/analysis tasks — read test files instead.

## Test File Organization

**Location:** Separate `tests/` tree mirroring `src/` package structure — not co-located with source.

**Naming:** `test_<module_under_test>.py`, one file per source module in most cases (`src/core/advisor.py` → `tests/test_core/test_advisor.py`). Some modules combine multiple related test files per feature slice, e.g. `tests/test_bot/test_analyze_photo_routing.py`, `tests/test_bot/test_card_price.py`, `tests/test_bot/test_advice_indicator.py`, `tests/test_bot/test_draft_handler.py`, `tests/test_bot/test_messages.py` all test different aspects of `src/bot/handlers/analyze.py` and related bot code.

**Structure:**
```
tests/
├── conftest.py                  # shared fixtures (db, env, LLM mock helpers, sample data)
├── fixtures/                    # (package, currently just __init__.py — add shared static fixture data here)
├── integration/                 # cross-module / full-flow tests (real DB, multiple layers)
│   ├── test_e2e_flow.py
│   ├── test_photo_analysis.py
│   ├── test_parser_integration.py
│   ├── test_dfc_card_lookup.py
│   └── test_parent_set_code_flow.py
├── test_bot/                    # aiogram handler unit tests (mocked Message/FSMContext/DB)
├── test_core/                   # pure business logic unit tests (DeckAnalyzer, DeckAdvisor, lands)
├── test_db/                     # repository / query behavior against real Postgres
├── test_llm/                    # LLMClient unit tests (OpenAI SDK mocked)
├── test_parsers/                # Scryfall/17lands parser + grade validation tests
├── test_scripts/                # tests for one-off scripts (e.g. scripts/add_set.py)
├── test_vision/                 # card recognition + fuzzy matcher tests
└── test_config.py               # settings/env loading tests
```

## Test Structure

**Suite Organization:** Tests are grouped into `Test<Something>` classes named after acceptance-criteria IDs when the test traces to a tracked task, e.g. `tests/test_core/test_advisor.py`:
```python
class TestTC111AdviceContainsCardNames:
    """TC-11.1: Advice contains specific card names for replacement (min 2 if weak cards exist)."""

    @pytest.mark.asyncio
    async def test_prompt_includes_weak_card_names(self, advisor, llm_client):
        ...
```
The module docstring at the top of the file lists every `TC-<id>` covered, and each `Test<TCID><Name>` class maps 1:1 to one acceptance criterion. New tests tied to a tracked task/PR should follow this `TC-<id>` traceability pattern.

**Patterns:**
- Module-level `pytest.fixture` functions build reusable test doubles (`mock_env`, `llm_client`, `advisor` in `tests/test_core/test_advisor.py`); fixtures are layered (`advisor` depends on `llm_client` depends on `mock_env`).
- Plain (non-fixture) module-level helper functions build complex test data, prefixed `make_` / `build_` / `_make_`: `make_card_info(...)`, `build_deck_with_weak_and_strong()` (`tests/test_core/test_advisor.py`), `_make_message()`, `_make_state()`, `_make_db_user()`, `_make_recognition()`, `_make_db_card()` (`tests/test_bot/test_analyze_photo_routing.py`).
- No explicit teardown blocks in unit tests; DB-touching fixtures (`db_session`) handle cleanup via rollback (see Fixtures section below).

## Mocking

**Framework:** `unittest.mock` (`Mock`, `MagicMock`, `AsyncMock`, `patch`, `patch.object`) — no `pytest-mock` dependency.

**Patterns:**
- LLM calls are mocked by patching the specific client method with an async function via `side_effect`, capturing call arguments in a list for later assertions:
```python
captured_messages = []

async def mock_completion(messages, system_prompt=None):
    captured_messages.extend(messages)
    return "Порада."

with patch.object(llm_client, "call_completion", side_effect=mock_completion):
    advice = await advisor.generate_advice(deck, card_infos, analysis)
```
(`tests/test_core/test_advisor.py`)
- aiogram objects (`Message`, `FSMContext`, `CallbackQuery`) are hand-built `MagicMock`/`AsyncMock` trees rather than using aiogram test utilities — async methods (`msg.answer`, `state.get_data`) are explicitly wrapped in `AsyncMock(return_value=...)`:
```python
def _make_message() -> MagicMock:
    msg = MagicMock()
    msg.from_user = MagicMock(id=12345)
    msg.bot = AsyncMock()
    msg.bot.get_file = AsyncMock(return_value=file_obj)
    msg.answer = AsyncMock(return_value=reply)
    return msg
```
(`tests/test_bot/test_analyze_photo_routing.py`)
- Internal handler functions/classes are patched at the point of use with `@patch("src.bot.handlers.analyze.CardRecognizer")` / `@patch("src.bot.handlers.analyze._handle_single_card", new_callable=AsyncMock)` decorators stacked on the test method (bottom-up = first positional mock arg).
- `mock.patch.dict(os.environ, env_vars, clear=True/False)` is the standard way to control environment/settings in tests (`tests/conftest.py: mock_env`, `mock_env_session`).

**What to Mock:**
- The OpenAI/LLM boundary (`LLMClient.call_completion`, `LLMClient.call_vision`) — never make real API calls in tests.
- aiogram `Message`, `CallbackQuery`, `FSMContext`, and `bot` objects in handler unit tests (`tests/test_bot/`).
- External HTTP calls (e.g. card price lookups via `httpx`).

**What NOT to Mock:**
- The database. Repository and integration tests run against a real PostgreSQL instance via testcontainers (`db_session`/`clean_session` fixtures) — SQL correctness (joins, upserts, constraints) is verified against real Postgres, not an in-memory substitute.
- Core business logic (`DeckAnalyzer`, `DeckAdvisor`, `recommend_lands`) is tested directly with plain constructed dataclasses (`CardInfo`, `Deck`, `DeckAnalysis`), not mocked.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def sample_deck_data() -> dict[str, Any]:
    return {
        "main_deck": ["Lightning Bolt", "Lightning Bolt", "Counterspell", ...],
        "sideboard": ["Negate", "Disenchant"],
        "set_code": "TST",
    }
```
(`tests/conftest.py`)

**Location:** Shared/global fixtures live in `tests/conftest.py`: `postgres_container`, `database_url`, `mock_env_session`, `db_engine`, `session_factory`, `db_session`, `clean_session`, `mock_env`, plus LLM response builders `create_mock_vision_response()` / `create_mock_advice_response()` and sample data fixtures (`sample_card_names`, `sample_deck_data`, `sample_image_bytes`). Test-file-local fixtures/factories (e.g. `make_card_info`, `advisor`) live at the top of their respective test module when only used there.

**Key DB Fixtures:**
- `db_session` — per-test session; rolls back after the test (no persistent writes), use for tests that should not leave data behind.
- `clean_session` — truncates all tables (`Base.metadata.sorted_tables`, reverse order) before yielding, then commits after the test; use for integration tests that need a known-empty starting state and want changes to persist within the test.

## Coverage

**Requirements:** No coverage threshold enforced in `pyproject.toml` or CI config found — `pytest-cov` is available as a dev dependency but no `--cov-fail-under` gate exists.

**View Coverage:**
```bash
powershell.exe -Command "cd C:\dev\smart-goblin; .\.venv\Scripts\python.exe -m pytest --cov=src --cov-report=html"
```

## Test Types

**Unit Tests:** Majority of the suite. Test one module/class in isolation with all external boundaries (LLM, Telegram objects, HTTP) mocked. Located in `tests/test_core/`, `tests/test_llm/`, `tests/test_vision/`, `tests/test_bot/`, `tests/test_parsers/`.

**Integration Tests:** `tests/integration/` — exercise multiple layers together (vision → analyzer → advisor → repository) against the real testcontainer Postgres, e.g. `tests/integration/test_e2e_flow.py`, `tests/integration/test_photo_analysis.py`, `tests/integration/test_parser_integration.py`. DB-layer tests in `tests/test_db/` also hit the real database (repository correctness), even though they live outside the `integration/` folder.

**E2E Tests:** No browser/Telegram-live E2E framework; `test_e2e_flow.py` is the closest equivalent, driving the pipeline in-process (mocked LLM, real DB) rather than through a live Telegram bot.

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_prompt_includes_weak_card_names(self, advisor, llm_client):
    ...
    with patch.object(llm_client, "call_completion", side_effect=mock_completion):
        advice = await advisor.generate_advice(deck, card_infos, analysis)
```

**Error/Exception Testing:**
- Domain exceptions from `src/llm/exceptions.py` (`LLMTimeoutError`, `LLMRateLimitError`, etc.) are tested by mocking the underlying OpenAI SDK to raise the SDK-level exception (`APITimeoutError`, `APIStatusError`) and asserting the wrapped domain exception is raised — see `tests/test_llm/test_client.py`.
- Handler-level error paths are tested by making a mocked collaborator (e.g. `CardRecognizer`) raise, then asserting the correct Ukrainian error message was sent via `message.answer(...)`.

**Test Case Traceability:** When a test corresponds to a tracked task/acceptance criterion, name the test class `Test<TC-ID><ShortName>` and reference the `TC-<id>` in both the module docstring and the test's own docstring/description, matching the pattern in `tests/test_core/test_advisor.py` and `tests/test_bot/test_analyze_photo_routing.py`.

---

*Testing analysis: 2026-09-23*

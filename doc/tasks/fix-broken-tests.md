# Task: Fix broken tests

## Status
Open. Pre-existing failures, unrelated to the 17lands grading rewrite.

## Background
While running the full test suite during the 17lands global-stats rewrite,
7 tests were already failing on `main` (verified by stashing the new changes
and re-running — same failures). They split into two clusters.

## Failing tests

### Cluster A — Ukrainian-text assertions vs English prompts (5 failures)
Tests assert that LLM system prompts contain specific Ukrainian phrases
(e.g., `"заміни"`, `"порожній"`), but the actual prompts in the codebase
are written in English (with a final `"Write in Ukrainian"` instruction
to the LLM). The tests have drifted from the implementation.

- `tests/test_bot/test_draft_handler.py::TestTC_P4_3_9_SystemPromptContent::test_system_prompt_contains_ukrainian_instruction`
- `tests/test_bot/test_draft_handler.py::TestTC_P4_3_9_SystemPromptContent::test_system_prompt_contains_deck_context_instruction`
- `tests/test_core/test_advisor.py::TestTC112EmptySideboardNoSection::test_empty_sideboard_no_add_section`
- `tests/test_core/test_advisor.py::TestTC113UkrainianNoJargon::test_system_prompt_requests_ukrainian`
- `tests/test_core/test_advisor.py::TestP37SessionMode::test_session_mode_prompt_contains_swap_instructions`
- `tests/test_llm/test_client.py::TestPromptBuilders::test_build_advice_prompt_handles_empty_sideboard`

**Resolution options:**
1. Update tests to assert against the current English prompt text + the
   "Write in Ukrainian" instruction.
2. OR translate the prompts in `src/llm/prompts.py` and `src/core/advisor.py`
   to Ukrainian (which CLAUDE.md says is the user-facing language convention).

Pick whichever matches product intent — the user-visible LLM output is
already Ukrainian, so option 1 is the lower-risk path.

### Cluster B — Real env vars leaking into mocked test (1 failure)
`tests/test_llm/test_client.py::TestLLMClientInitialization::test_client_uses_config_defaults`
expects the `mock_env` fixture to provide `OPENAI_API_KEY=sk-test-key`,
but the real `.env` value is being read instead. The fixture isn't
overriding cached `Settings`.

**Resolution:** Make the `mock_env` fixture clear `get_settings.cache_clear()`
before patching, or use `monkeypatch.setenv` plus `Settings()`-instantiation
inside the test rather than `get_settings()`.

## Acceptance criteria
- All 7 tests pass.
- Full `pytest --ignore=tests/integration` is green.
- No production code regressions (other tests still pass).

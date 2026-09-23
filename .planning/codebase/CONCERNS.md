---
last_mapped_commit: 8366eb8
---

# Codebase Concerns

**Analysis Date:** 2026-09-23

## Tech Debt

**FSM state stored in in-memory storage (no persistence):**
- Issue: `Dispatcher()` in `src/main.py:60` is constructed without an explicit `storage=` argument, so aiogram defaults to `MemoryStorage`. All `/draft` FSM state (`waiting_main`, `waiting_sideboard`, `chatting`, plus the whole conversation history saved via `state.update_data(...)`) lives only in process memory.
- Files: `src/main.py`, `src/bot/handlers/draft.py`
- Impact: Any deploy, crash, or restart (which happens routinely via Railway auto-deploy on merge to `main`) silently drops all users' in-progress draft sessions and ongoing chat conversations with no user-facing warning beyond a stale FSM state that no longer matches actual bot behavior.
- Fix approach: Introduce `RedisStorage` (or a DB-backed aiogram storage) for FSM state so sessions survive restarts, or at minimum detect stale states and prompt the user to restart `/draft` after a deploy.

**No per-user request throttling around expensive OpenAI calls:**
- Issue: There is no throttling/cooldown middleware in `src/bot/middlewares.py` (only `UserRegistrationMiddleware`) and no `Semaphore`/`cooldown` guard in the analyze/draft handlers.
- Files: `src/bot/middlewares.py`, `src/bot/handlers/analyze.py`, `src/bot/handlers/draft.py`
- Impact: A user can spam `/analyze` with photos or rapid chat messages, generating unbounded GPT-4o Vision + text completion calls (billed per-token). No protection against runaway cost from a single abusive or buggy client.
- Fix approach: Add a per-user rate-limit/cooldown middleware (e.g. minimum interval between photo submissions, max daily analyses) enforced before dispatching to `analyze.py`/`draft.py` handlers.

**Widespread bare `except Exception` swallowing without differentiated handling:**
- Issue: Broad `except Exception:` blocks appear throughout the bot layer and elsewhere, several with no logging at all (silent `pass`).
- Files: `src/bot/handlers/analyze.py:357,474,575,595,699,718`, `src/bot/handlers/draft.py:273,324,365,470`, `src/db/session.py:102`, `src/vision/layouts.py:74`
- Impact: Two of these (`analyze.py:575`, `analyze.py:719`) are `except Exception: pass  # message may be too old to edit` — intentional and acceptable, but the pattern is copy-pasted without narrowing to the specific Telegram "message not modified"/"message to edit not found" errors, so it will also silently swallow unrelated bugs (e.g. a typo in a keyword arg) during keyboard/message edits.
- Fix approach: Catch aiogram's specific `TelegramBadRequest` (with message substring check) instead of blanket `Exception` for the "message may be too old" cases; keep broad catches only at the top-level handler boundary where they already log via `logger.exception(...)`.

**Large, monolithic handler files mixing FSM orchestration, formatting, and business calls:**
- Issue: `src/bot/handlers/analyze.py` (719 lines) and `src/bot/handlers/draft.py` (473 lines) each combine multiple command/callback handlers, private pipeline helpers (`_run_deck_pipeline`), and inline formatting logic in one module.
- Files: `src/bot/handlers/analyze.py`, `src/bot/handlers/draft.py`
- Impact: High cognitive load per change; a small tweak to one flow (e.g. sideboard skip) risks touching shared helpers used by unrelated flows. Makes targeted testing harder — `tests/test_bot/test_draft_handler.py` and `tests/test_bot/test_analyze_photo_routing.py` must exercise large call graphs to hit small branches.
- Fix approach: Extract the shared deck-analysis pipeline (recognition → matching → analysis → advice → save → render) into a `src/core/` or `src/bot/pipeline.py` service used by both `analyze.py` and `draft.py`, leaving handlers as thin adapters.

**No `TODO`/`FIXME` markers found, but scheduler mixes 3 independent unit-of-work steps in one nested try block:**
- Issue: `run_scheduled_update` in `src/parsers/scheduler.py` (lines ~90-165) nests three sequential `try/except Exception` blocks (Scryfall fetch, 17lands fetch, grade validation) inside an outer `try/except Exception` that also catches everything. A failure in the outer scope (e.g. DB session setup) is logged generically with no per-set detail.
- Files: `src/parsers/scheduler.py`
- Impact: Debugging a partial failure (e.g. why ratings for one set silently didn't update) requires reading nested log lines across ~70 lines of code; no metrics/counters are aggregated for alerting.
- Fix approach: Extract each step into its own named function returning a result/error object; aggregate a per-run summary object for structured logging or future alerting.

## Known Bugs

**None identified as confirmed open bugs during this pass.** No `TODO`/`FIXME`/`HACK`/`XXX` markers exist anywhere under `src/`, suggesting either a very clean backlog or that known issues are tracked exclusively in the Notion tracker (per `CLAUDE.md`) rather than in-code — cross-check the Notion "Smart Goblin → Tasks Tracker" board for currently known bugs not reflected here.

## Security Considerations

**Secrets on disk in `.env` (expected, but verify exclusion):**
- Risk: `.env` exists at the repo root (`C:\dev\smart-goblin\.env`) alongside `.env.example`.
- Files: `.env` (contents not read/quoted — presence only), `.gitignore`
- Current mitigation: `.gitignore` explicitly lists `.env`, `.env.local`, `.env.*.local` (`.gitignore:2-4`), so the working `.env` should not be tracked by git.
- Recommendations: Periodically confirm with `git ls-files | grep -i '\.env'` (should return nothing) that no historical commit ever added `.env`; if it was ever committed, treat all contained keys (Telegram bot token, OpenAI key, DB URL) as compromised and rotate them.

**Telegram bot token and OpenAI key handled via `SecretStr` — good, but exposed at call sites:**
- Risk: `src/config.py` wraps `DATABASE_URL`/tokens in pydantic `SecretStr`, but `src/main.py:56` calls `.get_secret_value()` to pass the raw token to `Bot(token=...)`. This is required for aiogram to function, but any future `logger.debug(settings)` or exception traceback that captures local variables at that call site could leak the token in production logs (`LOG_LEVEL=DEBUG` is used on staging per `CLAUDE.md`).
- Files: `src/main.py`, `src/config.py`
- Current mitigation: `Settings.__str__`/repr appears to avoid printing secrets directly (only model names are interpolated, per `src/config.py:140`).
- Recommendations: Avoid ever logging the `Bot` object or raw exception context at DEBUG level near token usage; confirm no `except Exception as e: logger.debug(e.__dict__)`-style capture exists near `src/main.py:56`.

**No input sanitization/size cap on Telegram photo uploads before sending to GPT-4o Vision:**
- Risk: `src/vision/recognizer.py` and its callers do not show any explicit max-file-size or dimension check before forwarding image bytes to OpenAI's vision endpoint.
- Files: `src/vision/recognizer.py`, `src/bot/handlers/analyze.py`, `src/bot/handlers/draft.py`
- Current mitigation: Telegram itself caps photo message size, providing an implicit upper bound.
- Recommendations: Add an explicit size/dimension guard before calling the LLM client to fail fast with a friendly Ukrainian error message instead of relying solely on Telegram's limits and OpenAI's own rejection behavior.

## Performance Bottlenecks

**Sequential (non-concurrent) per-set processing in the scheduler:**
- Problem: `run_scheduled_update` in `src/parsers/scheduler.py` iterates sets one at a time, awaiting the Scryfall fetch, then the 17lands fetch, then validation, for each set in turn (no `asyncio.gather`).
- Files: `src/parsers/scheduler.py`
- Cause: Straightforward sequential loop, likely intentional to keep the two rate-limited external APIs (Scryfall: 10 req/s, 17lands: unspecified) from being hit concurrently across sets, but this means total runtime scales linearly with number of active sets.
- Improvement path: Bound concurrency with a small `asyncio.Semaphore` (e.g. 2-3 concurrent sets) while still respecting each parser's internal rate limiter (`RateLimiter` in `src/parsers/scryfall.py:33`), to speed up nightly refresh as the number of tracked sets grows.

**No caching layer for repeated card/rating lookups within a single analysis:**
- Problem: Each `/analyze` or `/draft` run queries card + rating rows fresh from Postgres via `CardRepository` (`src/db/repository.py`); popular cards (e.g. commons appearing in many users' decks the same day) are re-fetched on every request with no in-process or Redis cache.
- Files: `src/db/repository.py`, `src/core/analyzer.py`
- Cause: Repository methods always issue a new `SELECT` with eager-loaded ratings (`selectinload`/`joinedload`) per call; acceptable at current scale but adds DB round-trips linearly with concurrent users.
- Improvement path: Not urgent at current traffic; if user volume grows, add a short-TTL in-memory cache keyed by `(set_code, card_name)` for `get_by_name`/`get_cards_with_ratings`.

## Fragile Areas

**`src/bot/handlers/analyze.py` (719 lines) — largest file in the codebase:**
- Files: `src/bot/handlers/analyze.py`
- Why fragile: Combines command parsing, FSM state, deck pipeline orchestration (`_run_deck_pipeline`), Telegram message editing with fallback `except Exception: pass` patterns, and inline text truncation logic (`text[:3980] + "\n\n_...скорочено_"` duplicated near line 568 and similar spots). Any refactor of the shared pipeline risks breaking one of several callback/command entry points that all funnel through it.
- Safe modification: Before changing shared helpers (`_run_deck_pipeline` and similar), grep all call sites in both `analyze.py` and `draft.py` since deck-analysis logic is duplicated/near-duplicated between the two handler modules.
- Test coverage: `tests/test_bot/test_analyze_photo_routing.py`, `tests/test_bot/test_advice_indicator.py`, `tests/integration/test_photo_analysis.py`, `tests/integration/test_e2e_flow.py` cover key flows, but no dedicated unit tests appear to target the message-length truncation or the `except Exception: pass` edit-fallback branches directly.

**Grade validation is best-effort and non-blocking:**
- Files: `src/parsers/grade_validator.py`, `src/parsers/scheduler.py`
- Why fragile: `validate_set_grades` failures are caught and logged as warnings only (`run_scheduled_update`'s validation `try/except Exception` at `src/parsers/scheduler.py` around line 155-163); a systematic validation failure (e.g. 17lands API schema change) would produce log noise every night but never halt or alert, per `CLAUDE.md`'s note that `--strict` mode "runs the post-update grade validation hook" — the non-strict default path used by the scheduled job does not appear to escalate failures.
- Safe modification: When changing `grade_validator.py`'s comparison logic, manually run `railway ssh python -m src.parsers.scheduler --strict` against staging (per `CLAUDE.md`) to confirm validation still triggers correctly, since the automated schedule alone won't surface regressions loudly.
- Test coverage: `tests/test_parsers/test_grade_validator.py` exists and covers core logic directly.

**Duplicated deck-pipeline logic between `analyze.py` and `draft.py`:**
- Files: `src/bot/handlers/analyze.py`, `src/bot/handlers/draft.py`
- Why fragile: Both modules independently call `DeckAnalyzer`, `CardRecognizer`, `fuzzy_match_cards`, `TelegramRenderer`, and repository saves. A bug fix or behavior change (e.g. new advice formatting) must be manually mirrored in both files, and it's easy to update one without the other.
- Safe modification: When fixing a bug in the recognition→analysis→advice pipeline, check both handler files, not just the one where the bug was reported.
- Test coverage: Each handler has its own test file (`test_analyze_photo_routing.py`, `test_draft_handler.py`) but there's no shared pipeline-level unit test that would catch divergence between the two implementations.

## Scaling Limits

**Single-process aiogram long-polling with in-memory FSM storage:**
- Current capacity: One bot process per environment (production/staging), long-polling Telegram's `getUpdates`. `MemoryStorage` (see Tech Debt above) implicitly limits the bot to a single running instance — the "separate bot token per environment" constraint documented in `CLAUDE.md` already reflects that only one poller can hold a token's `getUpdates` lease at a time.
- Limit: Cannot horizontally scale to multiple bot workers without switching both the update-consumption model (polling → webhook) and FSM storage (memory → Redis/DB-backed).
- Scaling path: If load grows, migrate to Telegram webhooks behind a small HTTP server plus `RedisStorage` for FSM, enabling multiple stateless bot workers.

**Scheduler and bot share one process/event loop:**
- Current capacity: `src/main.py` starts the APScheduler-based parser scheduler in the same process as the Telegram bot when `PARSER_SCHEDULE_ENABLED=true` (production only, per `CLAUDE.md`'s environment table).
- Limit: A long-running or hanging parser job (e.g. 17lands API slowness) shares the same event loop as live user-facing bot handlers; a poorly-behaved blocking call in the parser path could stall bot responsiveness during the nightly 03:00 UTC run.
- Scaling path: If nightly runs start impacting bot latency, split the scheduler into a separate worker process/Railway service rather than co-hosting it with the bot.

## Dependencies at Risk

**Tight coupling to 17lands' unofficial/undocumented data feed:**
- Risk: `src/parsers/seventeen_lands.py` scrapes/calls 17lands' card-rating data, which is a third-party site with no formal SLA or versioned API contract (the scheduler's grade-validation logic, `src/parsers/grade_validator.py`, exists specifically to catch when 17lands' underlying grades drift or its response shape changes).
- Impact: A 17lands site change (structure, auth, rate limiting) breaks nightly rating refreshes for all sets; production data (`card_ratings` table) would silently go stale until noticed via logs or the validation report.
- Migration plan: No alternative rating source is integrated; document a runbook step for manually inspecting `railway logs` after 17lands changes, and consider caching last-known-good ratings with an explicit "stale since" flag so degraded data is visible.

## Missing Critical Features

**No structured monitoring/alerting on parser or bot failures:**
- Problem: All error surfaces (scheduler failures, LLM errors, DB errors) go to stdout logs consumed via `railway logs`; there is no external alerting (e.g. Sentry, PagerDuty, or a Telegram admin notification) when the nightly scheduler fails or grade validation reports a mismatch.
- Blocks: Silent degradation — a broken nightly update or a spike in `LLMError`/`format_error("general")` responses to users would only be noticed by someone manually tailing logs or a user complaint.

## Test Coverage Gaps

**No dedicated tests for `src/bot/handlers/history.py`, `start.py`, `stats.py`:**
- What's not tested: `tests/test_bot/` contains `test_advice_indicator.py`, `test_analyze_photo_routing.py`, `test_card_price.py`, `test_draft_handler.py`, `test_messages.py` — no `test_history_handler.py`, `test_start_handler.py`, or `test_stats_handler.py`.
- Files: `src/bot/handlers/history.py`, `src/bot/handlers/start.py`, `src/bot/handlers/stats.py`
- Risk: Regressions in `/start`, `/history`, `/stats` commands would not be caught by the test suite.
- Priority: Medium — these are simpler commands than `/analyze`/`/draft`, but `/history` in particular touches `AnalysisRepository` pagination logic (`src/db/repository.py:458-499`) which is untested at the handler level.

**No tests for `src/parsers/scheduler.py` orchestration logic:**
- What's not tested: `tests/test_parsers/` covers `test_grade_validator.py` and `test_seventeen_lands.py` directly, but there's no test exercising `run_scheduled_update`'s control flow (partial failure handling across Scryfall/17lands/validation steps).
- Files: `src/parsers/scheduler.py`
- Risk: The nested try/except structure noted under Tech Debt could regress (e.g. an exception in one set's processing silently aborting the whole loop) without any test catching it.
- Priority: Medium-High — this logic runs unattended in production nightly; a regression here degrades card data quality bot-wide without immediate user-facing symptoms.

**No middleware test for `UserRegistrationMiddleware`:**
- What's not tested: `src/bot/middlewares.py` has no corresponding `tests/test_bot/test_middlewares.py`.
- Files: `src/bot/middlewares.py`
- Risk: This middleware runs on every single incoming update; a regression (e.g. failing to inject `db_user`, or double-creating users on races) would silently break all handlers that depend on `data["db_user"]`.
- Priority: Medium — indirectly exercised via every handler test that relies on a `db_user` fixture, but no test isolates middleware behavior (e.g. concurrent first-message races, username-change handling).

---

*Concerns audit: 2026-09-23*

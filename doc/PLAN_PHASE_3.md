# Smart Goblin — Phase 3: E2E Tests, Persistent Set, Multi-Photo Session & HTML Reports

## How to Use
Mark completed tasks by changing `[ ]` to `[x]`.

---

## Task P3-1: E2E Integration Test — Real LLM Validation
- [x] **Done**

**Description:**
Переписати `test_photo_with_real_llm` → `test_e2e_real_llm_full_validation`. Використовує `clean_session` (testcontainers PostgreSQL), real OpenAI API, `tests/fixtures/ecl_deck.jpg`. Повний пайплайн через існуючий `run_analysis_pipeline()`. Валідація: main_deck не порожній, всі карти з win_rate мають grade не "?", друкує повний рендер у stdout. Skip якщо немає API key або фото.

**Acceptance Criteria:**
- [x] TC-P3-1.1: Тест пропускається (`pytest.skip`) якщо `OPENAI_API_KEY` не знайдено або є `sk-test`.
- [x] TC-P3-1.2: Тест пропускається якщо `tests/fixtures/ecl_deck.jpg` не існує.
- [x] TC-P3-1.3: Після реального розпізнавання `assert len(recognition.main_deck) > 0`.
- [x] TC-P3-1.4: Для кожної карти з `win_rate is not None` перевіряється що `grade not in ("?", "N/A")`.
- [x] TC-P3-1.5: `pytest tests/integration/test_photo_analysis.py -k real_llm` запускає тільки цей тест.
- [x] TC-P3-1.6: Тест друкує повний рендер звіту в stdout (для ручної перевірки розробником).
- [x] TC-P3-1.7: Тест не використовує ручних фікстур — метадані карт та рейтинги завантажуються з реальних Scryfall та 17lands API через `_seed_from_apis()`. Сет задається через `E2E_SET_CODE` у `.env` або env var; без нього тест пропускається.

---

## Task P3-2: User Model — Persistent Active Set
- [x] **Done**

**Description:**
Додати `active_set_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)` до моделі `User` у `src/db/models.py`. Оновити `UserRepository` у `src/db/repository.py` — додати метод `update_active_set(telegram_id, set_code)`.

**Acceptance Criteria:**
- [x] TC-P3-2.1: `User` має поле `active_set_code: Mapped[Optional[str]]` типу `String(10)`, nullable.
- [x] TC-P3-2.2: `UserRepository.update_active_set(telegram_id, "MKM")` зберігає значення у БД.
- [x] TC-P3-2.3: `UserRepository.update_active_set(telegram_id, None)` очищає значення (встановлює `NULL`).
- [x] TC-P3-2.4: Існуючі поля `username` та `language` не зачіпаються.

---

## Task P3-3: Alembic Migration — active_set_code Column
- [x] **Done**

**Description:**
Згенерувати Alembic міграцію для додавання колонки `active_set_code` до таблиці `users`. Міграція повинна мати `upgrade()` (додає колонку) та `downgrade()` (видаляє колонку).

**Acceptance Criteria:**
- [x] TC-P3-3.1: Файл міграції існує у `migrations/versions/` з описовою назвою.
- [x] TC-P3-3.2: `alembic upgrade head` виконується без помилок.
- [x] TC-P3-3.3: `alembic downgrade -1` коректно видаляє колонку.

---

## Task P3-4: /set Handler — Persist to DB
- [x] **Done**

**Description:**
Оновити `handle_set()` у `src/bot/handlers/stats.py`: при встановленні сету (`/set MKM`) зберігати значення в `users.active_set_code` через `UserRepository.update_active_set()` на додаток до FSM state. При скиданні (`/set reset`) очищати `active_set_code=None` у БД. При відображенні поточного сету — читати з `db_user.active_set_code`.

**Acceptance Criteria:**
- [x] TC-P3-4.1: `/set MKM` зберігає `"MKM"` в `users.active_set_code` у БД.
- [x] TC-P3-4.2: `/set reset` встановлює `active_set_code = NULL` у БД.
- [x] TC-P3-4.3: Після перезапуску бота `/set` (без аргументів) показує раніше збережений сет з БД.
- [x] TC-P3-4.4: FSM state оновлюється разом із БД для зворотної сумісності.

---

## Task P3-5: /analyze — Read Active Set from DB
- [x] **Done**

**Description:**
Оновити `_run_analysis()` у `src/bot/handlers/analyze.py`: пріоритет set_override: (1) аргумент команди → (2) FSM state → (3) `db_user.active_set_code` → (4) auto-detect з розпізнавання. Мінімальна зміна.

**Acceptance Criteria:**
- [x] TC-P3-5.1: Якщо FSM state порожній але `db_user.active_set_code = "MKM"`, аналіз використовує `"MKM"`.
- [x] TC-P3-5.2: Аргумент команди (`/analyze OTJ`) перевизначає `active_set_code`.
- [x] TC-P3-5.3: Аналіз без жодного набору (`active_set_code=NULL`, без FSM, без auto-detect) працює без збоїв.

---

## Task P3-6: /draft — Multi-Photo Session
- [x] **Done**

**Description:**
Реалізувати багатокрокову сесію аналізу. Нова команда `/draft`:
1. FSM `DraftState.waiting_main` → бот просить фото main deck
2. Фото → розпізнавання → "Розпізнано N карт. Надішліть sideboard або Пропустити"
3. FSM `DraftState.waiting_sideboard`
4. Фото sideboard АБО кнопка "Пропустити" → повний звіт з окремими секціями

Зберігати main_deck recognition у FSM data між кроками. Кнопка "Пропустити sideboard" у keyboards.py.

**Acceptance Criteria:**
- [x] TC-P3-6.1: `/draft` переводить FSM у стан `waiting_main` і відповідає проханням надіслати фото main deck.
- [x] TC-P3-6.2: Фото у стані `waiting_main` розпізнається, кількість карт підтверджується повідомленням.
- [x] TC-P3-6.3: FSM переходить у `waiting_sideboard` після успішного розпізнавання main deck.
- [x] TC-P3-6.4: Фото у стані `waiting_sideboard` розпізнається і генерується повний звіт.
- [x] TC-P3-6.5: Кнопка "Пропустити sideboard" генерує звіт з порожнім sideboard.
- [x] TC-P3-6.6: Звіт після `/draft` містить окремі секції main deck та sideboard.
- [x] TC-P3-6.7: Якщо розпізнавання main deck повертає порожній список, FSM скидається і надсилається повідомлення про помилку.

---

## Task P3-7: Session Advisor — Sideboard Swap Recommendations
- [x] **Done**

**Description:**
Оновити `DeckAdvisor.generate_advice()` у `src/core/advisor.py` та `build_advice_prompt()` у `src/llm/prompts.py` для підтримки режиму `session_mode=True`. У цьому режимі промпт фокусується на конкретних замінах sideboard → main deck: які карти з sideboard мають замінити які карти з main deck, з поясненнями чому. Fallback на стандартний промпт якщо sideboard порожній.

**Acceptance Criteria:**
- [x] TC-P3-7.1: `generate_advice()` приймає параметр `session_mode: bool = False`.
- [x] TC-P3-7.2: При `session_mode=True` та непустому sideboard промпт містить інструкцію фокусуватися на замінах.
- [x] TC-P3-7.3: При `session_mode=True` та порожньому sideboard промпт аналогічний звичайному.
- [x] TC-P3-7.4: Тест перевіряє що промпт з `session_mode=True` містить ключові слова про заміни.

---

## Execution Order

```
Task P3-1 (E2E Test)          ← незалежний

Task P3-2 (User Model)
    ↓
Task P3-3 (Migration)
    ↓
┌───────────────────┬──────────────────┐
│                   │                  │
Task P3-4 (/set DB)  Task P3-5 (/analyze DB set)
│                   │                  │
└────────┬──────────┴────────┬─────────┘
         ↓                   ↓
    Task P3-6 (/draft Multi-Photo)
         ↓
    Task P3-7 (Session Advisor)
```

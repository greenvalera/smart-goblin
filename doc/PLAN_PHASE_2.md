# Smart Goblin — Phase 2: Compact Card List & On-Demand Advice

## How to Use
Mark completed tasks by changing `[ ]` to `[x]`.

---

## Task P2-1: Land Calculator
- [x] **Done**

**Description:**
Створити `src/core/lands.py` з калькулятором рекомендованих земель. Підрахунок кольорових піпів з mana_cost карт, пропорційний розподіл 17 земель. Fallback на colors поле якщо mana_cost відсутній.

**Acceptance Criteria:**
- [x] TC-P2-1.1: `recommend_lands()` для 2-кольорової колоди (W/U) повертає правильний розподіл Plains + Island.
- [x] TC-P2-1.2: `count_color_pips("{2}{W}{W}{U}")` повертає `{"W": 2, "U": 1}`.
- [x] TC-P2-1.3: Mono-color колода отримує всі 17 земель одного кольору.
- [x] TC-P2-1.4: Colorless колода (без кольорових піпів) повертає порожній lands dict.

---

## Task P2-2: DeckReport Model Update
- [x] **Done**

**Description:**
Додати `land_recommendation` поле до `DeckReport`. Оновити `DeckReport.build()` для прийому land recommendation. Зробити `advice` параметр опціональним.

**Acceptance Criteria:**
- [x] TC-P2-2.1: `DeckReport` має поле `land_recommendation: Optional[LandRecommendation]`.
- [x] TC-P2-2.2: `DeckReport.build()` працює без `advice` параметра.

---

## Task P2-3: Telegram Renderer Rewrite
- [x] **Done**

**Description:**
Переписати `TelegramRenderer.render()` для нового формату: компактний заголовок зі статистикою, грейдований список карт (дедуплікація, сортування за грейдом), рекомендовані землі. Прибрати секцію порад.

**Acceptance Criteria:**
- [x] TC-P2-3.1: Render містить список карт з грейдами (A+, B, C...) та win rate.
- [x] TC-P2-3.2: Дупльовані карти показуються як `Card Name x2` замість окремих рядків.
- [x] TC-P2-3.3: Секція "Рекомендації" відсутня у рендері.
- [x] TC-P2-3.4: Секція "Землі" показує кількість земель кожного кольору.
- [x] TC-P2-3.5: Повідомлення не перевищує 4000 символів.

---

## Task P2-4: Keyboard & Advice Button
- [x] **Done**

**Description:**
Додати кнопку "Отримати поради" до клавіатури аналізу. Реалізувати callback handlers для генерації та перегляду порад на вимогу.

**Acceptance Criteria:**
- [x] TC-P2-4.1: Клавіатура містить кнопку "💡 Отримати поради" після аналізу.
- [x] TC-P2-4.2: Натискання кнопки генерує поради та надсилає окремим повідомленням.
- [x] TC-P2-4.3: Після генерації кнопка змінюється на "💡 Переглянути поради".
- [x] TC-P2-4.4: Повторне натискання показує збережені поради без повторного виклику LLM.

---

## Task P2-5: Analyze Handler Refactor
- [x] **Done**

**Description:**
Прибрати автоматичний виклик LLM advisor з `_run_analysis()`. Додати виклик land calculator. Зберігати аналіз без порад. Додати helper для відтворення card_infos з збережених даних.

**Acceptance Criteria:**
- [x] TC-P2-5.1: `/analyze` не викликає LLM для генерації порад (тільки vision call).
- [x] TC-P2-5.2: Рекомендовані землі включені у відповідь.
- [x] TC-P2-5.3: Analysis зберігається в БД з `advice=None`.

---

## Task P2-6: Vision Prompts Update
- [x] **Done**

**Description:**
Оновити промпти розпізнавання для кращої обробки відсутніх земель. Додати `lands_visible` поле до JSON відповіді та `RecognitionResult`.

**Acceptance Criteria:**
- [x] TC-P2-6.1: Промпти містять інструкцію не додавати земель якщо їх не видно.
- [x] TC-P2-6.2: `RecognitionResult` має поле `lands_visible: bool | None`.
- [x] TC-P2-6.3: `_build_result()` парсить `lands_visible` з LLM відповіді.

---

## Task P2-7: History & HTML Updates
- [x] **Done**

**Description:**
Оновити history detail view — прибрати inline advice, додати кнопку порад. Оновити HTML renderer для відображення рекомендованих земель.

**Acceptance Criteria:**
- [x] TC-P2-7.1: History detail не показує advice inline.
- [x] TC-P2-7.2: HTML renderer показує секцію рекомендованих земель.

---

## Task P2-8: Tests & Verification
- [x] **Done**

**Description:**
Додати тести для land calculator. Оновити існуючі тести що зламалися через зміни формату. Запустити повний test suite.

**Acceptance Criteria:**
- [x] TC-P2-8.1: `pytest` проходить без помилок.
- [x] TC-P2-8.2: Land calculator тести покривають основні сценарії.

---

## Execution Order

```
Task P2-1 (Land Calculator)
    ↓
Task P2-2 (DeckReport Model)
    ↓
Task P2-3 (Telegram Renderer)
    ↓
┌───────────────────┬────────────────────┐
│                   │                    │
Task P2-4 (Keyboard) Task P2-5 (Handler)
│                   │                    │
└────────┬──────────┴──────────┬─────────┘
         ↓                     ↓
    Task P2-6 (Vision)
         ↓
    Task P2-7 (History & HTML)
         ↓
    Task P2-8 (Tests)
```

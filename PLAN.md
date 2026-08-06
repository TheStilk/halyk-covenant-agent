# Halyk AI Challenge — Master Plan & Agent Specification

**Дата:** 6 августа 2026  
**Цель:** Построить полностью автономного AI-агента, который читает «грязные» финансовые PDF и точно определяет соблюдение / нарушение кредитных ковенантов.

---

## 1. Суть задачи

У каждого заёмщика есть кредитный договор с 3 финансовыми ковенантами (пункты 6.1, 6.2, 6.3).

Для **каждого ковенанта каждого заёмщика** агент должен вернуть:

| Поле | Описание | Правила |
|------|----------|---------|
| `status` | `COMPLIANT` или `BREACH` | Только заглавными, точное совпадение |
| `actual` | Фактическое значение показателя | Положительное число, 2 знака после запятой |
| `evidence_txn_id` | ID транзакции-улики или `null` | Только если именно эта транзакция определяет вердикт |

### Формат сдачи

Один файл `submission.json`:

```json
{
  "team": "your-team-name",
  "contact_email": "you@example.com",
  "model": "qwen3.8-max + gemini-3.6-flash",
  "answers": {
    "P1": {
      "6.1": { "status": "BREACH", "actual": 0.46, "evidence_txn_id": null },
      "6.2": { "status": "BREACH", "actual": 6842117.53, "evidence_txn_id": null },
      "6.3": { "status": "COMPLIANT", "actual": 283664.18, "evidence_txn_id": null }
    },
    ...
  }
}
```

**Важно:** ключи уже есть в `submission_template.json`. Нельзя добавлять, удалять или переименовывать ключи.

---

## 2. Система оценки (критично понимать)

Каждая ячейка оценивается от 0 до 1:

| Компонент | Баллы | Условие |
|-----------|-------|---------|
| `status` | **0.50** | Точное совпадение с эталоном |
| `actual` | **0.30** | Шкала: `0.30 × max(0, 1 − e/0.05)`, где `e = |ваше − эталон| / |эталон|` |
| `evidence_txn_id` | **0.20** | Точное совпадение. Если в эталоне `null` — баллы убывают вместе с `actual` |

**Критические правила:**
- Если `status` неверный → **вся ячейка = 0**
- Ошибка `actual` ≥ 5% → теряется 0.30 (и 0.20, если evidence = null)
- Пустая ячейка = 0
- Повреждённый JSON = 0 по затронутым ячейкам

---

## 3. Датасет

### Структура

| Файл / папка | Содержание |
|--------------|------------|
| `master_ledger_2025.csv` | Все транзакции всех заёмщиков (txn_id, date, account_id, counterparty, description, amount, currency) |
| `documents/` | Все PDF (имена — непрозрачные хеши). Тип и принадлежность определяются только по содержимому |
| `submission_template.json` | Готовые пустые ячейки |
| `ground_truth.json` | Правильные ответы (только для открытого датасета) |

### Связь account_id → scenario_id

В леджере `txn_id` всегда начинается с `scenario_id`:

```
TXN-P1-0007  → scenario_id = P1, account_id = ACC-7801
TXN-B1-0019  → scenario_id = B1, account_id = ACC-7201
TXN-B4-0039  → scenario_id = B4, account_id = ACC-7204
```

Маппинг (открытый датасет):

| account_id | scenario_id |
|------------|-------------|
| ACC-7801   | P1          |
| ACC-7802   | P2          |
| ACC-7803   | P3          |
| ACC-7804   | P4          |
| ACC-7805   | P5          |
| ACC-7806   | P6          |
| ACC-7807   | P7          |
| ACC-7808   | P8          |
| ACC-7809   | P9          |
| ACC-7810   | P10         |
| ACC-7201   | B1          |
| ACC-7204   | B4          |

### Типы документов (по содержимому)

- **Кредитный договор** (Loan Agreement) — содержит Article 6 / Статья 6 с ковенантами
- **Примечания к финансовой отчётности** (Notes) — содержат Revenue, EBITDA, Capex, Related-party и т.д.
- **KYC / Compliance dossier** — связанные стороны, account_id
- **Мусор** (внутренние регламенты, пресс-релизы, уведомления АХО и т.д.) — игнорировать

### Примеры ковенантов (из реального договора)

**Пункт 6.1** — Минимальная скорректированная рентабельность по EBITDA  
(отношение Adjusted EBITDA / Revenue ≥ 0.28x)

**Пункт 6.2** — Максимальные расходы по категории (например Capex ≤ $1,800,000)

**Пункт 6.3** — Максимальные платежи связанным сторонам как доля от выручки (≤ 0.04x)

Ковенанты **разные у разных заёмщиков**. Текст всегда нужно извлекать из договора.

---

## 4. Архитектура агента

### Модели (только две)

| Модель | Роль | Когда использовать |
|--------|------|--------------------|
| **Qwen 3.8-Max** | Reasoning, расчёты, structured output, reflection | Анализ ковенанта, вычисление actual, reflection |
| **Gemini 3.6 Flash** | Скорость + массовая обработка | Классификация PDF, первичная экстракция, фильтрация |

### Высокоуровневый пайплайн

```
START
  │
  ▼
[1. Load Ledger] → строится словарь account_id → scenario_id + все транзакции по account
  │
  ▼
[2. Classify & Route Documents]
  │   - читаем все PDF
  │   - классифицируем (loan / notes / kyc / junk)
  │   - извлекаем account_id / company name
  │   - привязываем к scenario_id
  │
  ▼
[3. Extract Covenants] (из loan agreements)
  │   - находим Article 6 / Статья 6
  │   - извлекаем текст пунктов 6.1, 6.2, 6.3
  │
  ▼
[4. Extract Financial Metrics] (из notes + ledger)
  │   - Revenue, EBITDA, Capex, Related-party payments и т.д.
  │
  ▼
[5. Fan-out по ковенантам]
  │
  ├──► [Analyze Covenant] ← Qwen 3.8-Max
  │         │
  │         ▼
  │    (confidence < 0.85?)
  │         │ да
  │         ▼
  │    [Reflect] ← Qwen 3.8-Max
  │
  ▼
[6. Collect & Format]
  │
  ▼
[7. Write submission.json]
  │
  ▼
END
```

### State (LangGraph)

```python
class AgentState(TypedDict):
    # Глобальные
    ledger: pd.DataFrame
    account_to_scenario: Dict[str, str]
    
    # По заёмщику
    scenario_id: str
    account_id: str
    documents: Dict[str, Any]          # path → extracted content
    covenants: Dict[str, str]          # "6.1" → полный текст ковенанта
    metrics: Dict[str, float]          # extracted financial numbers
    transactions: List[Dict]           # транзакции этого account_id
    
    # Результаты
    results: Annotated[List[FinalCovenantResult], operator.add]
    
    stage: str
    error: Optional[str]
```

---

## 5. Ключевые технические решения

### 5.1 Кэширование документов

```python
from diskcache import Cache
import hashlib
from pathlib import Path

doc_cache = Cache("./doc_cache")

def get_file_key(file_path: str) -> str:
    path = Path(file_path)
    stat = path.stat()
    key = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.md5(key.encode()).hexdigest()

def read_pdf_with_cache(file_path: str) -> dict:
    key = get_file_key(file_path)
    if key in doc_cache:
        return doc_cache[key]
    
    # pdfplumber + vision fallback
    result = extract_pdf(file_path)
    doc_cache[key] = result
    return result
```

### 5.2 Prompt Caching (Qwen 3.8-Max)

Стабильный системный промпт всегда в начале + `cache_control: {"type": "ephemeral"}`.

Цены Qwen3.8-Max (август 2026):
- Input: $2.00 / 1M
- Explicit cache read: ~$0.17–0.25 / 1M (в 8–12 раз дешевле)
- Minimum для explicit cache: 1024 токена
- TTL: 5 минут (сбрасывается при hit)

### 5.3 Structured Output

Всегда использовать Pydantic + `with_structured_output`:

```python
class CovenantVerdict(BaseModel):
    status: Literal["COMPLIANT", "BREACH"]
    actual: float
    evidence_txn_id: Optional[str]
    reasoning: str
    confidence: float
```

### 5.4 Параллелизм

- Fan-out по ковенантам через `Send` API LangGraph
- Параллельная обработка заёмщиков через `asyncio.gather` + `max_concurrency=6–8`
- На боевом прогоне: `durability="exit"`

---

## 6. Боевые промпты

### 6.1 Системный промпт (Stable — кэшируется)

```text
You are a highly precise Financial Covenant Monitoring Agent specializing in loan agreements, financial ratios, and transaction analysis.

Your sole mission is to determine for each covenant whether it is COMPLIANT or BREACH, provide the exact supporting numerical value (actual), and identify the evidence transaction ID when the breach is determined by a single transaction.

Hard rules (must follow strictly):
1. Use ONLY the data explicitly provided in the documents and ledger. Never invent numbers or transactions.
2. Show all calculations step-by-step before the final verdict.
3. If data is missing or ambiguous — set confidence ≤ 0.6 and explain.
4. Arithmetic must be exact. Double-check every calculation.
5. actual is ALWAYS a positive number (absolute value for expenses). Two decimal places.
6. evidence_txn_id is the single transaction that DETERMINES the result (removing it would change the verdict). Otherwise null.
7. Output MUST be valid JSON matching the schema. No markdown, no extra text.

Required schema:
{
  "status": "COMPLIANT" | "BREACH",
  "actual": number,
  "evidence_txn_id": string | null,
  "reasoning": string,
  "confidence": number
}

Reasoning process (mandatory):
1. PLAN — list exact formulas and steps
2. SOLVE — perform calculations with intermediate results
3. CHECK — verify arithmetic and data sources
4. OUTPUT — return only the final JSON
```

### 6.2 User-промпт для анализа ковенанта

```text
Scenario ID: {scenario_id}
Account ID: {account_id}

Covenant {covenant_id} text:
"""
{covenant_text}
"""

Extracted financial metrics:
{metrics}

Relevant transactions (from ledger):
{transactions}

Task:
Analyze the covenant strictly according to the rules.
Follow PLAN → SOLVE → CHECK → OUTPUT.
Return only the JSON object.
```

### 6.3 Reflection-промпт

```text
You previously produced this verdict:
{previous_json}

Original covenant:
"""
{covenant_text}
"""

Metrics and transactions:
{data}

Task:
Re-examine the previous answer carefully.
- Verify every number against source data
- Check formula application
- Confirm evidence_txn_id is truly the determining transaction

If correct — return unchanged.
If errors found — return corrected JSON.
Output only the final JSON.
```

### 6.4 Классификация документа

```text
Classify this document. Return only one label:

- loan_agreement   (contains Article 6 / financial covenants)
- financial_notes  (contains revenue, EBITDA, adjustments, related-party disclosures)
- kyc              (contains account_id, beneficial ownership, related parties)
- junk             (internal procedures, press releases, facility notices, etc.)

Document text (first 3000 chars):
{text}
```

---

## 7. Детальный алгоритм работы агента

### Шаг 1. Построение маппинга

```python
def build_account_to_scenario(ledger: pd.DataFrame) -> dict:
    mapping = {}
    for _, row in ledger.iterrows():
        txn_id = row["txn_id"]          # TXN-P1-0007
        account = row["account_id"]     # ACC-7801
        scenario = txn_id.split("-")[1] # P1
        mapping[account] = scenario
    return mapping
```

### Шаг 2. Классификация и привязка документов

Для каждого PDF:
1. Извлечь текст (pdfplumber + OCR/vision fallback)
2. Классифицировать (Gemini Flash)
3. Найти `account_id` или название компании
4. Привязать к `scenario_id`

### Шаг 3. Извлечение ковенантов

Из `loan_agreement`:
- Найти блок «Статья 6» / «Article 6» / «Финансовые ковенанты»
- Разделить на пункты 6.1, 6.2, 6.3
- Сохранить полный текст каждого пункта

### Шаг 4. Извлечение метрик

Из `financial_notes` + ledger:
- Revenue
- Adjusted EBITDA (с учётом add-backs)
- Capex / категория расходов
- Related-party payments
- Любые другие показатели, упомянутые в ковенанте

**Важно:** числа часто находятся в таблицах или картинках → нужен vision / хороший table extraction.

### Шаг 5. Анализ ковенанта (Qwen)

1. Прочитать текст ковенанта
2. Понять формулу и порог
3. Подставить извлечённые метрики
4. Посчитать `actual`
5. Сравнить с порогом → `status`
6. Если нарушение определяется одной транзакцией — найти `evidence_txn_id`

### Шаг 6. Reflection (при low confidence)

Повторный проход с тем же контекстом + предыдущим ответом.

### Шаг 7. Сборка submission.json

Заполнить все 36 ячеек строго по шаблону.  
Заполнить `team`, `contact_email`, `model`.

---

## 8. Правила evidence_txn_id

`evidence_txn_id` — это **единственная** транзакция, которая **определяет** результат:

- Убери её → вердикт изменится
- Обычный вклад в сумму (даже самый крупный) — **не** evidence
- Для коэффициентных и агрегатных ковенантов почти всегда `null`

Примеры, когда evidence нужен:
- Одна транзакция была неправильно классифицирована / включена / исключена
- Одна транзакция связанной стороны превысила лимит

---

## 9. План разработки (открытый датасет → боевой)

### Фаза 1 — Фундамент (сейчас)

1. Парсинг леджера + маппинг account → scenario
2. Кэш документов
3. Классификатор PDF
4. Извлечение Article 6
5. Базовый structured output

### Фаза 2 — Расчёты

1. Извлечение ключевых метрик из notes
2. Реализация 3–5 типовых формул ковенантов
3. Сверка с `ground_truth.json`
4. Отладка edge-cases

### Фаза 3 — Надёжность

1. Reflection-цикл
2. Обработка отсутствующих данных
3. Параллельный запуск по заёмщикам
4. Замер времени на полном открытом сете

### Фаза 4 — Боевой день (9 августа)

- 11:00 — получение приватного датасета
- 11:00–11:20 — быстрый осмотр + запуск экстракции
- 11:20–13:20 — основной прогон
- 13:20–13:50 — проверка проблемных ячеек
- 13:50–14:00 — финальная сборка и сдача

---

## 10. Ограничения хакатона (обязательно соблюдать)

- **Запрещено** получать ответы вручную или через готовые агенты (Claude Code, Codex и т.д.) для финальных ответов
- Можно использовать любые модели и библиотеки для **разработки** пайплайна
- Все ответы должен сгенерировать **ваш собственный агент**
- Нарушение = дисквалификация

---

## 11. Рекомендуемый стек

```text
langgraph
langchain-openai          # Qwen через OpenAI-compatible API
langchain-google-genai    # Gemini 3.6 Flash
pdfplumber / pymupdf
diskcache
pydantic
pandas
asyncio
```

---

## 12. Критерии успеха

- Все 36 ячеек заполнены
- `status` совпадает с эталоном на ≥ 90%
- `actual` в пределах 2.5% ошибки на большинстве ячеек
- `evidence_txn_id` правильный там, где он не null
- Пайплайн успевает обработать весь датасет за < 2.5 часа

---

## 13. Следующие конкретные шаги для агента-исполнителя

1. Создать структуру проекта
2. Реализовать `build_account_to_scenario()`
3. Реализовать кэш + чтение PDF
4. Реализовать классификатор документов
5. Реализовать извлечение Article 6
6. Реализовать State + Graph (LangGraph)
7. Вставить боевые промпты
8. Сделать первый прогон на 1–2 заёмщиках и сверить с ground_truth

---

**Этот документ — единственный источник правды для построения агента.**  
Все решения по архитектуре, промптам, кэшированию и оценке зафиксированы выше.

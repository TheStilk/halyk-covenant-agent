# Датасет и система оценки

## Open dataset layout

```
agentic-bank-public/
├── master_ledger_2025.csv
├── documents/                 # ~200 PDF, имена = opaque hashes
├── submission_template.json
├── ground_truth.json          # только open set
├── CASE.ru.md / CASE.kz.md
└── ...
```

На боевом дне структура та же; `ground_truth.json` отсутствует.

---

## Ledger

Колонки:

`txn_id, date, account_id, counterparty, description, amount, currency`

- Расходы **отрицательные**, поступления **положительные**.  
- Категории **нет** — классификация по `description` / reclass AUP.  
- `actual` всегда **модуль** суммы (положительный).  
- Валюты смешанные; на open set face-value часто в USD (см. notes по FX).

### account_id → scenario_id

`txn_id` всегда начинается с `scenario_id` заёмщика:

| txn_id | scenario | account (пример) |
|--------|----------|------------------|
| `TXN-P1-0007` | P1 | ACC-7801 |
| `TXN-P10-0062` | P10 | ACC-7810 |
| `TXN-B1-0019` | B1 | ACC-7201 |
| `TXN-B4-0039` | B4 | ACC-7204 |

Реализация: `scenario = txn_id.split("-")[1]` → `build_account_to_scenario()`.

В леджере тысячи «шумных» ACC-9xxx; в submission попадают только сценарии из шаблона:

**P1–P10, B1, B4** → **12 заёмщиков × 3 ковенанта = 36 ячеек**.

---

## Типы документов (по содержимому)

| Тип | Содержание | Использование |
|-----|------------|----------------|
| Loan agreement | Article 6 / ковенанты 6.1–6.3 | текст ковенанта, пороги, формулы |
| Financial notes | Revenue policy, reclass, cut-off, AUP | корректировки метрик |
| Consolidated FS | PPE rollforward, segment note | **Group Capex** |
| KYC | ownership %, related parties, subsidiary pledge | RP payments, unrestricted subs |
| Junk | брендбуки, АХО, IT, superseded loan | игнор |

Имена файлов **не** кодируют тип/заёмщика.

---

## Связь документов с scenario

1. Найти `ACC-XXXX` в тексте (в т.ч. spaced OCR).  
2. `account_to_scenario[ACC]` → scenario.  
3. Fallback: company name `… JSC` из loan/KYC.  
4. Consolidated FS: segment «through {Borrower} JSC».

---

## Ковенанты

Всегда три пункта в Article 6: **6.1, 6.2, 6.3** — но **формулировки разные** у разных заёмщиков.

Примеры (open set):

| scenario | 6.1 (тип) | 6.2 | 6.3 |
|----------|-----------|-----|-----|
| P1 | Capital intensity Capex/(OpEx+Lease) | Min revenue | Max RP absolute |
| P5 | **Group Capex / EBITDA** | Min revenue | Max RP absolute |
| B1 | Interest coverage EBITDA/Interest | Max overhead line | Max RP absolute |
| P9 | Unrestricted asset transfers / Capex | Min revenue | Max RP absolute |
| P10 | Insurance/(Lease+Util) | Rev − max(Payroll,Tax) | RP / Revenue |

Текст ковенанта — **единственный** источник формулы и порога; нельзя хардкодить «у всех 6.1 = margin».

---

## Related parties

Из KYC:

```
Организация, в которой Группа владеет X% и более → related
```

Парсер учитывает:

- `"Turan Capital" LLP 28.8%`  
- `Atyrau Holding Group L.L.P. 37.9%`  
- OCR image-страниц  

Платежи: negative amounts на related counterparties (часто `Management advisory retainer`).

**Unrestricted subsidiaries** (для transfers): доля активов в залоге **ниже 50%** → вне обеспечения → учитываются в числителе assets-transferred.

---

## Auditor reclass / cut-off

| Документ | Действие |
|----------|----------|
| Final AUP «Отчёт о выполнении согласованных процедур» | **применять** reclass |
| «ПРОЕКТ — ПРОМЕЖУТОЧНАЯ ВЕДОМОСТЬ» | **игнорировать** |
| Notes: «операция TXN-… относится к 2026» | cut-off **exclude** |

Пример B1: advisory → interest expenses → evidence `TXN-B1-0020` (без неё coverage ≥ 2.0 → COMPLIANT).

---

## Group Capex

Когда ковенант ссылается на «капитальные затраты **Группы**» / consolidated parent:

1. Найти Consolidated Financial Statements.  
2. Note PPE:

   - NBV beginning  
   - Depreciation charge  
   - NBV end  
   - «no disposals» → disposals = 0  

3. `group_capex = end − begin + depreciation`  
4. `actual = group_capex / borrower_EBITDA`  

Пример P5: Sarybel Energy Holding → segment Ekibastuz Power Services → ratio **9.45**.

---

## Формат submission

Шаблон **нельзя** менять по ключам: только заполнять `status`, `actual`, `evidence_txn_id`.

```json
{
  "team": "halyk-covenant-agent",
  "contact_email": "you@example.com",
  "model": "qwen3.8-max + gemini-3.6-flash",
  "answers": {
    "P1": {
      "6.1": { "status": "BREACH", "actual": 0.46, "evidence_txn_id": null },
      "6.2": { "status": "BREACH", "actual": 6842117.53, "evidence_txn_id": null },
      "6.3": { "status": "COMPLIANT", "actual": 283664.18, "evidence_txn_id": null }
    }
  }
}
```

Правила полей:

- `status` — только `COMPLIANT` / `BREACH`  
- `actual` — **всегда &gt; 0** (модуль), 2 знака; и при breach, и при compliant  
- `evidence_txn_id` — только если **одна** txn определяет вердикт; иначе `null`  

---

## Система оценки (Master Plan §2)

Каждая ячейка ∈ [0, 1]:

| Компонент | Баллы | Условие |
|-----------|-------|---------|
| status | **0.50** | exact match |
| actual | **0.30** | `0.30 × max(0, 1 − e/0.05)`, `e = \|pred−true\| / \|true\|` |
| evidence | **0.20** | exact match; если GT `null` — evidence-баллы **масштабируются** как actual |

Критично:

- **status неверный → вся ячейка = 0**  
- ошибка actual ≥ 5% → 0 за actual (и 0 за evidence, если GT evidence null)  
- пустая / битый JSON → 0  

36 ячеек → max score **36.0**.  
Относительный score: `total / 36`.

### Пример

| | pred | true | pts |
|--|------|------|-----|
| status | BREACH | BREACH | 0.50 |
| actual | 9.45 | 9.45 | 0.30 |
| evidence | null | null | 0.20 |
| **total** | | | **1.00** |

При `status` ok, actual error 2.5%: actual = 0.15, evidence(null) = 0.10 → cell = 0.75.

---

## Open-set ground truth

`ground_truth.json`:

```json
{
  "scenarios": {
    "P5": {
      "covenants": {
        "6.1": { "status": "BREACH", "actual": 9.45, "evidence_txn_id": null },
        ...
      }
    }
  },
  "seed": 42,
  "version": "v1"
}
```

Использовать **только** для локальной отладки; на private set недоступен.

---

## Целевые метрики (проект)

| Метрика | Фаза 2 | Фаза 3 (текущее) |
|---------|--------|------------------|
| Hackathon score | ~76% | **~90%** |
| Status accuracy | ~86% | **~92%** |
| Evidence (non-null) | ~44% | **100%** |

Известные hard cells (open set): P3/6.1 springing leverage, P4/6.3 RP ratio edge, P7/6.1 tax+util/EBITDA.

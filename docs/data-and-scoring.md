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
- Категории **нет** — `classify_txn_category(description, amount)` + reclass AUP.  
- `actual` всегда **модуль** (положительный).  
- `amount` может быть **NaN** — fill из notes/treasury.  
- Non-USD → конвертация по курсу из notes при наличии.

### Taxonomy (ledger)

| Категория | Примеры description |
|-----------|---------------------|
| `revenue` | sales settlement, capacity, stevedoring |
| `interest` | loan interest, **overdraft**, **capitalised interest**, true-up, interest income/rebate |
| `lease` | land/warehouse lease, **storage unit rent**, rent free, lease deposit/incentive |
| `insurance` | premium, broker rebate, experience refund, claim reimbursement |
| `tax` | tax, excise, **VAT refund/reclaim**, tax credit |
| `utilities` | electric, water/sewer levy, overbilling refund |
| `marketing` | media buy, volume rebate, unused ad budget |
| `payroll` | salary, wage, overfunding returned |
| `capex` / `opex` / `financing` / `transfer` | purchase of equipment, operating cost, drawdown, transfer of assets |
| `other_*` | остаток ~**0.6%** rows (было ~28%); one-time works (flood/berth silt) остаются other для Adj EBITDA |

Expense aggregates суммируют только **outflows**; inflows в family (refunds) не ломают open-set totals.

### account_id → scenario_id

| txn_id | scenario | account (пример) |
|--------|----------|------------------|
| `TXN-P1-0007` | P1 | ACC-7801 |
| `TXN-P10-0062` | P10 | ACC-7810 |
| `TXN-B1-0019` | B1 | ACC-7201 |
| `TXN-B4-0039` | B4 | ACC-7204 |

`scenario = txn_id.split("-")[1]` → `build_account_to_scenario()`.

Borrower pick: **не** хардкод `ACC-7*` — prefer non-noise (`ACC-9*` = open-set noise) / mapping.

**Open set:** P1–P10, B1, B4 → **12 × 3 = 36 ячеек** (ids из `submission_template.json`).

---

## Типы документов

| Тип | Использование |
|-----|----------------|
| Loan agreement | тексты ковенантов (template ids), пороги, формулы |
| Financial notes / AUP | reclass, cut-off, missing amounts, FX, EBITDA add-backs |
| Consolidated FS | **Group Capex** (PPE rollforward) |
| KYC | related parties, unrestricted subsidiaries |
| Treasury memo | NaN fills (налоги, payroll) |
| Junk | игнор (в т.ч. superseded loan, draft AUP); bad extract flagged |

Все **PDF** в `documents/` прогоняются (quality + classify); CSV/TXT в папке PDF-пайплайн не читает.

---

## Ковенанты

Ids **из template** (per scenario), не хардкод. Open set = 6.1 / 6.2 / 6.3.

Формулировки **разные** у заёмщиков. Примеры open set:

| scenario | 6.1 | 6.2 | 6.3 |
|----------|-----|-----|-----|
| P1 | Capital intensity | Min revenue | Max RP absolute |
| P4 | **Adj EBITDA / Revenue** | Max capex | RP / Revenue |
| P5 | **Group Capex / EBITDA** | Min revenue | Max RP absolute |
| B1 | Interest coverage | Max overhead line | Max RP absolute |
| P3 | Financing / EBITDA (springing) | Min revenue | Max RP absolute |
| P7 | (Tax+Util) / EBITDA | Min revenue | Max RP absolute |
| P8 | Payroll total | Max capex | RP / Revenue |
| P9 | Unrestricted transfers / Capex | Min revenue | Max RP absolute |
| P10 | Insurance/(Lease+Util) | Rev − max(Payroll,Tax) | RP / Revenue |

---

## Ключевые расчётные кейсы (open set)

### Group Capex (P5 6.1)

Consolidated FS Sarybel Energy Holding → segment Ekibastuz Power Services:

```
group_capex = end − begin + depreciation = 21,847,362.55
EBITDA = Rev − OpEx = 2,312,216.15
actual = 9.45  BREACH (thr 9.00)
```

### Adjusted EBITDA margin (P4 6.1)

```
one-time: dredge 251k (<300k), demurrage 343k, flood 481k
AdjEBITDA = Rev − OpEx − non_qual = 2,321,317.34
actual = 0.33  COMPLIANT (thr 0.28)
```

### NaN tax (P7 6.1)

`TXN-P7-0033` amount NaN → treasury: $486,204.19 mineral tax  
`(tax + util) / EBITDA = 0.36` BREACH.

### FX opex (P3 6.1)

EUR catalyst servicing × rate 1.16 → opex;  
`financing / EBITDA = 1.71` BREACH (springing, fin &gt; $4M).

### Interest coverage + reclass (B1 6.1)

Final AUP: advisory → interest; evidence `TXN-B1-0020`.

---

## Related parties

KYC: «Группа владеет X% и более» → related.  
OCR для image-таблиц; поддержка `"Name" LLP`, `L.L.P.`.

**Unrestricted subsidiaries:** pledge &lt; 50% → учитываются в assets-transferred.

---

## Auditor reclass / cut-off

| Документ | Действие |
|----------|----------|
| Final AUP | применять reclass |
| «ПРОЕКТ — ПРОМЕЖУТОЧНАЯ» | **игнорировать** |
| Notes cut-off / exclude period | exclude txn |

---

## Формат submission

Нельзя менять ключи шаблона — только заполнять поля ячеек.  
`status` / `actual` **не могут быть null** (pipeline sanitize + validate hard-fail).

```json
{
  "team": "Сычуанский Соус",
  "contact_email": "serkebaevmadiyar09@gmail.com, zhenis415@gmail.com",
  "model": "<from MODEL_LABEL or LLM_MODEL>",
  "answers": {
    "P1": {
      "6.1": { "status": "BREACH", "actual": 0.46, "evidence_txn_id": null },
      "6.2": { "status": "BREACH", "actual": 6842117.53, "evidence_txn_id": null },
      "6.3": { "status": "COMPLIANT", "actual": 283664.18, "evidence_txn_id": null }
    }
  }
}
```

Перед сдачей: `uv run python main.py validate`.

---

## Система оценки

Каждая ячейка ∈ [0, 1]:

| Компонент | Баллы | Условие |
|-----------|-------|---------|
| status | **0.50** | exact; иначе вся ячейка 0 |
| actual | **0.30** | `0.30 × max(0, 1 − e/0.05)` |
| evidence | **0.20** | exact; GT null → scale with actual |

36 ячеек → max **36.0**.

### Open-set результат (текущий)

| Метрика | Значение |
|---------|----------|
| Hackathon score | **36.0 / 36.0 (100%)** |
| Status accuracy | **36/36 (100%)** |
| Evidence (non-null) | **9/9 (100%)** |
| Mean / max rel error | **0%** |

Проверка: `uv run python scripts/eval_phase2.py`.

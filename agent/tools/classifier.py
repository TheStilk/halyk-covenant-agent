"""PDF document classifier: loan_agreement / financial_notes / kyc / junk.

Primary path is a fast rule-based classifier (deterministic, free).
Optional Gemini Flash path when CLASSIFY_USE_LLM=true or rules are ambiguous.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from agent.config import CLASSIFY_USE_LLM, PDF_TEXT_PREVIEW_CHARS
from agent.models import DocClassification, DocType
from agent.tools.pdf_extract import find_account_ids, find_company_names

# ---------------------------------------------------------------------------
# Strong signal patterns (order matters for scoring)
# ---------------------------------------------------------------------------

_LOAN_STRONG = [
    re.compile(r"ДОГОВОР\s+БАНКОВСКОГО\s+ЗАЙМА", re.I),
    re.compile(r"LOAN\s+AGREEMENT", re.I),
    re.compile(r"Статья\s+6\s*[—\-–]\s*Финансовые\s+ковенанты", re.I),
    re.compile(r"Article\s+6\s*[—\-–].{0,40}[Cc]ovenant", re.I),
    re.compile(r"Пункт\s+6\.1", re.I),
    re.compile(r"старший\s+обеспеченный\s+заём", re.I),
]

_LOAN_WEAK = [
    re.compile(r"финансовые\s+ковенанты", re.I),
    re.compile(r"financial\s+covenant", re.I),
    re.compile(r"Кредитор", re.I),
    re.compile(r"Заёмщик", re.I),
]

_NOTES_STRONG = [
    re.compile(r"Примечания\s+к\s+финансовой\s+отчётности", re.I),
    re.compile(r"Notes\s+to\s+the\s+Financial\s+Statements", re.I),
    re.compile(r"АУДИТОРСКОЕ\s+ДЕЛО", re.I),
    re.compile(r"согласованных\s+процедур", re.I),
    re.compile(r"Agreed[-\s]?Upon\s+Procedures", re.I),
    re.compile(r"Скорректированная\s+EBITDA", re.I),
    re.compile(r"Adjusted\s+EBITDA", re.I),
    re.compile(r"Consolidated\s+Financial\s+Statements", re.I),
    re.compile(r"CONSOLIDATED\s+ANNUAL\s+REPORT", re.I),
    re.compile(r"Net book value at the beginning of the year", re.I),
    re.compile(r"Property,\s*plant\s+and\s+equipment", re.I),
]

_NOTES_WEAK = [
    re.compile(r"\bEBITDA\b", re.I),
    re.compile(r"Выручка", re.I),
    re.compile(r"\bRevenue\b", re.I),
    re.compile(r"Капитальные\s+затраты", re.I),
    re.compile(r"\bCapex\b", re.I),
    re.compile(r"связанн\w+\s+сторон", re.I),
    re.compile(r"related[-\s]?party", re.I),
    re.compile(r"Независимый\s+аудитор", re.I),
]

_KYC_STRONG = [
    re.compile(r"Досье\s*[«\"]?Знай\s+своего\s+клиента", re.I),
    re.compile(r"НАДЛЕЖАЩАЯ\s+ПРОВЕРКА\s+КЛИЕНТА", re.I),
    re.compile(r"Know\s+Your\s+Customer", re.I),
    re.compile(r"Проверка\s+связанных\s+сторон\s*[·•\.]", re.I),
    re.compile(r"beneficial\s+owner", re.I),
    re.compile(r"бенефициарн\w+\s+владель", re.I),
    re.compile(r"ФИНАНСОВЫЙ\s+МОНИТОРИНГ\s+И\s+КОМПЛАЕНС", re.I),
]

# Weak KYC signals alone are NOT enough (internal "KYC procedure" manuals are junk)
_KYC_WEAK = [
    re.compile(r"\bKYC\b"),
    re.compile(r"связанных\s+сторон", re.I),
    re.compile(r"комплаенс", re.I),
]

_JUNK_STRONG = [
    re.compile(r"пресс[-\s]?релиз", re.I),
    re.compile(r"press\s+release", re.I),
    re.compile(r"Уведомление\s+АХО", re.I),
    re.compile(r"ИТ[-\s]?инцидент", re.I),
    re.compile(r"Политика\s+удалённой", re.I),
    re.compile(r"Руководство\s+по\s+бренду", re.I),
    re.compile(r"чек[-\s]?лист\s+адаптации", re.I),
    re.compile(r"внутренн\w+\s+регламент", re.I),
    re.compile(r"НЕДЕЙСТВУЮЩАЯ\s+РЕДАКЦИЯ", re.I),
    re.compile(r"график\s+аренды", re.I),
    re.compile(r"INC-\d+", re.I),
    re.compile(r"методическое\s+руководство", re.I),
    re.compile(r"не\s+является\s+клиентским\s+досье", re.I),
    re.compile(r"не\s+содержит\s+заключений\s+о\s+каком-либо\s+конкретном", re.I),
    re.compile(r"Процедура\s+комплаенса", re.I),
    re.compile(r"Периодическое\s+обновление\s+KYC", re.I),
    re.compile(r"Единое\s+руководство\s+по\s+внутренним", re.I),
    re.compile(r"Контролируемый\s+документ", re.I),
]

# Superseded / draft loan versions must not be treated as active agreements
_SUPERSEDED = re.compile(
    r"НЕДЕЙСТВУЮЩАЯ\s+РЕДАКЦИЯ|Заменена\s+и\s+изложена\s+в\s+новой\s+редакции|"
    r"НЕ\s+ПРИМЕНЯЕТСЯ|superseded|DRAFT\s*[—\-–]\s*NOT\s+EXECUTED",
    re.I,
)

# Draft AUP / intermediate audit working papers (still useful but lower priority)
_DRAFT_NOTES = re.compile(
    r"ПРОЕКТ\s*[—\-–]\s*ПРОМЕЖУТОЧНАЯ|НЕ\s+ЯВЛЯЕТСЯ\s+ОКОНЧАТЕЛЬНОЙ\s+ПОЗИЦИЕЙ",
    re.I,
)


def _score(patterns: list[re.Pattern[str]], text: str, weight: float = 1.0) -> float:
    return sum(weight for p in patterns if p.search(text))


def _pick_account(
    accounts: list[str],
    account_to_scenario: Optional[dict[str, str]],
) -> Optional[str]:
    """Choose the borrower account among all ids mentioned in a document.

    A document naming several accounts (borrower + counterparties) belongs to
    the one the submission asks about. Falling back to the "ACC-7" prefix, as
    the previous version did, encodes a numbering quirk of the public dataset
    rather than a rule of the task (audit finding C4).
    """
    if not accounts:
        return None
    if account_to_scenario:
        for acc in accounts:
            if acc in account_to_scenario:
                return acc
    return accounts[0]


def classify_text_rules(
    text: str,
    path: str = "",
    *,
    account_to_scenario: Optional[dict[str, str]] = None,
) -> DocClassification:
    """Rule-based document classification from full or partial text."""
    head = text[:12000]  # enough for headers + early body
    head_lower_zone = text[:4000]

    loan_score = _score(_LOAN_STRONG, head, 3.0) + _score(_LOAN_WEAK, head, 0.5)
    notes_score = _score(_NOTES_STRONG, head, 3.0) + _score(_NOTES_WEAK, head, 0.4)
    kyc_score = _score(_KYC_STRONG, head, 3.0) + _score(_KYC_WEAK, head, 0.3)
    junk_score = _score(_JUNK_STRONG, head_lower_zone, 2.5)

    # Superseded loan → junk (do not use old covenants)
    if _SUPERSEDED.search(head_lower_zone) and loan_score > 0:
        loan_score = 0.0
        junk_score += 4.0

    # Generic internal procedure mentioning KYC is still junk
    if junk_score >= 2.5 and kyc_score < 6.0:
        kyc_score = min(kyc_score, 1.0)

    # Draft intermediate AUP still counts as financial_notes but lower conf later
    is_draft_notes = bool(_DRAFT_NOTES.search(head_lower_zone))

    scores = {
        DocType.LOAN_AGREEMENT: loan_score,
        DocType.FINANCIAL_NOTES: notes_score,
        DocType.KYC: kyc_score,
        DocType.JUNK: junk_score,
    }
    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_type]

    # Default to junk if nothing fires
    if best_score < 1.0:
        best_type = DocType.JUNK
        confidence = 0.55
    else:
        second = sorted(scores.values(), reverse=True)[1]
        # high confidence when clear winner
        if best_score >= 3.0 and best_score - second >= 2.0:
            confidence = 0.95
        elif best_score >= 3.0:
            confidence = 0.85
        else:
            confidence = 0.7

    if best_type == DocType.FINANCIAL_NOTES and is_draft_notes:
        confidence = min(confidence, 0.75)

    accounts = find_account_ids(text)
    companies = find_company_names(text)
    account_id = _pick_account(accounts, account_to_scenario)

    return DocClassification(
        path=path,
        doc_type=best_type,
        account_id=account_id,
        company_name=companies[0] if companies else None,
        confidence=confidence,
        method="rules",
        preview=text[:PDF_TEXT_PREVIEW_CHARS],
    )


def classify_document(
    text: str,
    path: str = "",
    *,
    use_llm: Optional[bool] = None,
    account_to_scenario: Optional[dict[str, str]] = None,
) -> DocClassification:
    """Classify a document; optionally fall back to Gemini for low confidence."""
    result = classify_text_rules(text, path=path, account_to_scenario=account_to_scenario)

    if account_to_scenario and result.account_id:
        result.scenario_id = account_to_scenario.get(result.account_id)

    should_llm = CLASSIFY_USE_LLM if use_llm is None else use_llm
    ambiguous = result.confidence < 0.75 or (
        result.doc_type == DocType.JUNK and len(text.strip()) > 500 and "EBITDA" in text
    )

    if should_llm and ambiguous:
        try:
            llm_result = classify_text_llm(text, path=path)
            # Keep entity extraction from rules; take type from LLM
            result.doc_type = llm_result.doc_type
            result.confidence = llm_result.confidence
            result.method = "llm"
            if not result.account_id and llm_result.account_id:
                result.account_id = llm_result.account_id
            if not result.company_name and llm_result.company_name:
                result.company_name = llm_result.company_name
            if account_to_scenario and result.account_id:
                result.scenario_id = account_to_scenario.get(result.account_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[classifier] LLM fallback failed for {Path(path).name}: {exc}")

    return result


def classify_text_llm(text: str, path: str = "") -> DocClassification:
    """Gemini Flash classification (Master Plan §6.4)."""
    from agent.prompts.system import DOC_CLASSIFY_PROMPT
    from agent.tools.llm import get_gemini

    preview = text[:PDF_TEXT_PREVIEW_CHARS]
    prompt = DOC_CLASSIFY_PROMPT.format(text=preview)
    llm = get_gemini(temperature=0.0)
    raw = llm.invoke(prompt)
    content = raw.content if hasattr(raw, "content") else str(raw)
    label = str(content).strip().lower()

    # Normalize free-form model output to a single label
    mapping = {
        "loan_agreement": DocType.LOAN_AGREEMENT,
        "financial_notes": DocType.FINANCIAL_NOTES,
        "kyc": DocType.KYC,
        "junk": DocType.JUNK,
    }
    doc_type = DocType.JUNK
    for key, val in mapping.items():
        if key in label.replace(" ", "_").replace("-", "_"):
            doc_type = val
            break

    accounts = find_account_ids(text)
    companies = find_company_names(text)
    account_id = _pick_account(accounts, None)

    return DocClassification(
        path=path,
        doc_type=doc_type,
        account_id=account_id,
        company_name=companies[0] if companies else None,
        confidence=0.8,
        method="llm",
        preview=preview,
    )

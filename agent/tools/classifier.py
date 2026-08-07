"""PDF document classifier: loan_agreement / financial_notes / kyc / junk.

Primary path is a fast rule-based classifier (deterministic, free).
Optional LLM path when CLASSIFY_USE_LLM=true or rules are ambiguous.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from agent.config import CLASSIFY_USE_LLM, PDF_TEXT_PREVIEW_CHARS
from agent.models import DocClassification, DocType
from agent.tools.pdf_extract import (
    find_account_ids,
    find_company_names,
    prefer_borrower_account,
)

# ---------------------------------------------------------------------------
# Strong signal patterns (order matters for scoring)
# ---------------------------------------------------------------------------

# OCR / RU often drops ё → е; allow both via [её].
# KZ (қазақ): bank/legal titles for Halyk private set + subjective KZ readiness.
_LOAN_STRONG = [
    re.compile(r"ДОГОВОР\s+БАНКОВСКОГО\s+ЗАЙМА", re.I),
    re.compile(r"LOAN\s+AGREEMENT", re.I),
    re.compile(r"Договор\s+об\s+открытии\s+кредитн\w*\s+лин", re.I),
    re.compile(r"Статья\s+6\s*[—\-–]\s*Финансовые\s+ковенанты", re.I),
    re.compile(r"Article\s+6\s*[—\-–].{0,40}[Cc]ovenant", re.I),
    # bare "Пункт 6.1" is NOT strong — too many non-loan docs use clause numbers
    re.compile(r"старший\s+обеспеченный\s+за[её]м", re.I),
    # Kazakh
    re.compile(r"Банк\s+несие\s+шарты", re.I),
    re.compile(r"Несие\s+шарты", re.I),
    re.compile(r"Қарыз\s+шарты", re.I),
    re.compile(r"Қарыз\s+келісім(?:\-?шарты|шарт)", re.I),
    re.compile(r"Бап\s+6\s*[—\-–:]\s*Қаржылық\s+ковенант", re.I),
    re.compile(r"Қаржылық\s+ковенанттар", re.I),
]

_LOAN_WEAK = [
    re.compile(r"финансовые\s+ковенанты", re.I),
    re.compile(r"financial\s+covenant", re.I),
    re.compile(r"кредитн\w*\s+лин\w*", re.I),
    re.compile(r"credit\s+facilit(?:y|ies)", re.I),
    re.compile(r"Кредитор", re.I),
    re.compile(r"За[её]мщик", re.I),
    re.compile(r"Пункт\s+6\.\d+", re.I),  # weak only — needs other loan signals
    # Kazakh
    re.compile(r"несие\s+беруші", re.I),
    re.compile(r"қарыз\s+алушы", re.I),
    re.compile(r"қаржылық\s+ковенант", re.I),
    re.compile(r"Тармақ\s+6\.\d+", re.I),
    re.compile(r"несие\s+желісі", re.I),
]

_NOTES_STRONG = [
    re.compile(r"Примечания\s+к\s+финансовой\s+отч[её]тности", re.I),
    re.compile(r"Notes\s+to\s+the\s+Financial\s+Statements", re.I),
    re.compile(r"АУДИТОРСКОЕ\s+ДЕЛО", re.I),
    re.compile(r"Аудиторск\w+\s+заключен", re.I),
    re.compile(r"Independent\s+Auditor.?s\s+Report", re.I),
    re.compile(r"согласованных\s+процедур", re.I),
    re.compile(r"Agreed[-\s]?Upon\s+Procedures", re.I),
    re.compile(r"Скорректированная\s+EBITDA", re.I),
    re.compile(r"Adjusted\s+EBITDA", re.I),
    re.compile(r"Consolidated\s+Financial\s+Statements", re.I),
    re.compile(r"CONSOLIDATED\s+ANNUAL\s+REPORT", re.I),
    re.compile(r"Net book value at the beginning of the year", re.I),
    re.compile(r"Property,\s*plant\s+and\s+equipment", re.I),
    # Kazakh
    re.compile(r"Қаржылық\s+есептілікке\s+ескертпе", re.I),
    re.compile(r"Қаржылық\s+есеп\s+беруге\s+ескертпе", re.I),
    re.compile(r"Аудиторлық\s+қорытынды", re.I),
    re.compile(r"Аудиторлық\s+іс", re.I),
    re.compile(r"келісілген\s+рәсімдер", re.I),
    re.compile(r"Түзетілген\s+EBITDA", re.I),
]

_NOTES_WEAK = [
    re.compile(r"\bEBITDA\b", re.I),
    re.compile(r"Выручка", re.I),
    re.compile(r"\bRevenue\b", re.I),
    re.compile(r"капитальн\w*\s+затрат", re.I),  # any case: капитальных затрат
    re.compile(r"\bCapex\b", re.I),
    re.compile(r"связанн\w+\s+сторон", re.I),
    re.compile(r"related[-\s]?party", re.I),
    re.compile(r"Независимый\s+аудитор", re.I),
    # Kazakh
    re.compile(r"түсім", re.I),
    re.compile(r"кіріс", re.I),
    re.compile(r"капиталдық\s+шығын", re.I),
    re.compile(r"байланысты\s+тарап", re.I),
    re.compile(r"тәуелсіз\s+аудитор", re.I),
]

_KYC_STRONG = [
    re.compile(r"Досье\s*[«\"]?Знай\s+своего\s+клиента", re.I),
    re.compile(r"НАДЛЕЖАЩАЯ\s+ПРОВЕРКА\s+КЛИЕНТА", re.I),
    re.compile(r"Know\s+Your\s+Customer", re.I),
    re.compile(r"Customer\s+Due\s+Diligence", re.I),
    re.compile(r"\bCDD\b"),
    re.compile(r"Проверка\s+связанных\s+сторон\s*[·•\.]", re.I),
    re.compile(r"beneficial\s+owner", re.I),
    re.compile(r"бенефициарн\w+\s+владель", re.I),
    re.compile(r"ФИНАНСОВЫЙ\s+МОНИТОРИНГ\s+И\s+КОМПЛАЕНС", re.I),
    # Kazakh
    re.compile(r"Клиентті\s+тиісінше\s+тексеру", re.I),
    re.compile(r"Өз\s+клиентіңді\s+біл", re.I),
    re.compile(r"Клиентті\s+біл", re.I),
    re.compile(r"бенефициарлық\s+меншік\s+иесі", re.I),
    re.compile(r"Қаржылық\s+мониторинг", re.I),
]

# Weak KYC signals alone are NOT enough (internal "KYC procedure" manuals are junk)
_KYC_WEAK = [
    re.compile(r"\bKYC\b"),
    re.compile(r"связанных\s+сторон", re.I),
    re.compile(r"комплаенс", re.I),
    re.compile(r"байланысты\s+тарап", re.I),
    re.compile(r"комплаенс", re.I),  # same latin in KZ docs
]

_JUNK_STRONG = [
    re.compile(r"пресс[-\s]?релиз", re.I),
    re.compile(r"press\s+release", re.I),
    re.compile(r"Уведомление\s+АХО", re.I),
    re.compile(r"ИТ[-\s]?инцидент", re.I),
    re.compile(r"Политика\s+удал[её]нной", re.I),
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
    # Kazakh junk
    re.compile(r"баспас[өо]з\s+хабарлама", re.I),
    re.compile(r"ішкі\s+регламент", re.I),
    re.compile(r"КҮШІНЕН\s+АЙЫРЫЛҒАН\s+РЕДАКЦИЯ", re.I),
]

# Superseded / draft loan versions must not be treated as active agreements
_SUPERSEDED = re.compile(
    r"НЕДЕЙСТВУЮЩАЯ\s+РЕДАКЦИЯ|Заменена\s+и\s+изложена\s+в\s+новой\s+редакции|"
    r"НЕ\s+ПРИМЕНЯЕТСЯ|superseded|DRAFT\s*[—\-–]\s*NOT\s+EXECUTED|"
    r"КҮШІНЕН\s+АЙЫРЫЛҒАН|қолданылмайды",
    re.I,
)

# Draft AUP / intermediate audit working papers (still useful but lower priority)
_DRAFT_NOTES = re.compile(
    r"ПРОЕКТ\s*[—\-–]\s*ПРОМЕЖУТОЧНАЯ|НЕ\s+ЯВЛЯЕТСЯ\s+ОКОНЧАТЕЛЬНОЙ\s+ПОЗИЦИЕЙ|"
    r"ЖОБА\s*[—\-–]|аралық\s+позиция",
    re.I,
)


def _score(patterns: list[re.Pattern[str]], text: str, weight: float = 1.0) -> float:
    return sum(weight for p in patterns if p.search(text))


def classify_text_rules(text: str, path: str = "") -> DocClassification:
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

    # Prefer mapped borrowers / non-noise accounts (not hard-coded ACC-7*)
    account_id: Optional[str] = prefer_borrower_account(accounts)

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
    """Classify a document; optionally fall back to LLM for low confidence."""
    result = classify_text_rules(text, path=path)

    # Re-rank account using ledger mapping when available
    if account_to_scenario:
        accounts = find_account_ids(text)
        preferred = prefer_borrower_account(
            accounts, account_to_scenario=account_to_scenario
        )
        if preferred:
            result.account_id = preferred

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
    """Optional LLM classification (CLASSIFY_* or primary LLM_*)."""
    from agent.prompts.system import DOC_CLASSIFY_PROMPT
    from agent.tools.llm import get_classify_model

    preview = text[:PDF_TEXT_PREVIEW_CHARS]
    prompt = DOC_CLASSIFY_PROMPT.format(text=preview)
    llm = get_classify_model(temperature=0.0)
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
    account_id = prefer_borrower_account(accounts)

    return DocClassification(
        path=path,
        doc_type=doc_type,
        account_id=account_id,
        company_name=companies[0] if companies else None,
        confidence=0.8,
        method="llm",
        preview=preview,
    )

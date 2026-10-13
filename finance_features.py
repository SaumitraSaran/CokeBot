"""Trusted finance capabilities: approved metrics, local plans and audit helpers."""
from __future__ import annotations

from datetime import datetime
import hashlib
import re

MAX_RESULT_ROWS = 500

GLOSSARY = {
    "transaction amount": {"definition": "Sum of transaction-currency amounts.", "expression": "SUM(amount_cur)"},
    "reporting amount": {"definition": "Sum in the reporting currency, safe for cross-currency totals.", "expression": "SUM(reporting_currency_amount)"},
    "active customer": {"definition": "A customer with at least one transaction in the selected period.", "expression": "COUNT(DISTINCT customer_party)"},
    "collection rate": {"definition": "Not available from the current transaction-only dataset; settlement status is required.", "expression": None},
    "net sales": {"definition": "Not available as a verified metric in the current dataset; this table contains transactions, not a sales ledger.", "expression": None},
    "margin": {"definition": "Not available from the current dataset; cost data is required.", "expression": None},
    "overdue": {"definition": "Due dates are available, but an overdue balance needs verified open/settled status.", "expression": None},
}


def normalized_key(question: str, context: list[dict]) -> str:
    context_text = " ".join(str(item.get("content", "")) for item in context[-2:])
    return hashlib.sha256(" ".join((question + " " + context_text).lower().split()).encode()).hexdigest()


def glossary_match(question: str) -> dict | None:
    q = question.lower()
    for metric, detail in GLOSSARY.items():
        if metric in q:
            return {"metric": metric, **detail}
    return None


def _limit(question: str, default: int = 10) -> int:
    match = re.search(r"\b(?:top|bottom|first|last|show|list)?\s*(\d{1,3})\b", question.lower())
    return min(max(int(match.group(1)), 1), 100) if match else default


def _period_filter(question: str) -> str:
    q = question.lower()
    year = re.search(r"\b(20(?:1[8-9]|2[0-6]))\b", q)
    if year:
        return f"YEAR(ct.trans_date) = {year.group(1)}"
    # Relative periods are anchored to the most recent loaded finance data,
    # rather than the machine clock, so historical demos stay correct.
    anchor = "(SELECT MAX(trans_date) FROM customer_transactions)"
    if "last month" in q:
        return f"ct.trans_date >= DATE_FORMAT({anchor} - INTERVAL 1 MONTH, '%Y-%m-01') AND ct.trans_date < DATE_FORMAT({anchor}, '%Y-%m-01')"
    if "this month" in q or "current month" in q:
        return f"ct.trans_date >= DATE_FORMAT({anchor}, '%Y-%m-01')"
    if "this year" in q or "ytd" in q:
        return f"YEAR(ct.trans_date) = YEAR({anchor})"
    return ""


def local_plan(question: str) -> dict | None:
    """Approved, parameter-free SQL plans for common queries. Never builds SQL from raw values."""
    q = " ".join(question.lower().split())
    period = _period_filter(q)
    where = f" WHERE {period}" if period else ""
    if any(metric in q for metric in ("net sales", "margin", "collection rate", "overdue")):
        glossary = glossary_match(q)
        if glossary and not glossary["expression"]:
            return {"unsupported_metric": glossary}
    if "trend" in q or "by month" in q or "monthly" in q:
        return {"intent": "monthly_transaction_trend", "query_type": "trend", "chart_type": "line",
                "sql": "SELECT DATE_FORMAT(ct.trans_date, '%Y-%m') AS month, "
                       "SUM(ct.reporting_currency_amount) AS reporting_amount "
                       "FROM customer_transactions AS ct "
                       "WHERE ct.trans_date >= DATE_SUB((SELECT MAX(trans_date) FROM customer_transactions), INTERVAL 5 MONTH) "
                       "GROUP BY DATE_FORMAT(ct.trans_date, '%Y-%m') ORDER BY month;"}
    if "payment mode" in q or "payment-mode" in q:
        return {"intent": "payment_mode_breakdown", "query_type": "breakdown", "chart_type": "bar",
                "sql": f"SELECT COALESCE(ct.payment_mode, 'Unspecified') AS payment_mode, SUM(ct.reporting_currency_amount) AS reporting_amount FROM customer_transactions AS ct{where} GROUP BY COALESCE(ct.payment_mode, 'Unspecified') ORDER BY reporting_amount DESC LIMIT 50;"}
    if (re.search(r"\b(top|highest|largest|bottom|lowest)\b", q)
            and re.search(r"\bcustomers?\b", q)):
        direction = "ASC" if any(word in q for word in ("bottom", "lowest")) else "DESC"
        return {"intent": "customer_ranking", "query_type": "ranking", "chart_type": "bar",
                "sql": f"SELECT ct.customer_name, SUM(ct.reporting_currency_amount) AS reporting_amount FROM customer_transactions AS ct{where} GROUP BY ct.customer_name ORDER BY reporting_amount {direction} LIMIT {_limit(q)};"}
    if any(term in q for term in ("how many transaction", "transaction count", "number of transaction")):
        return {"intent": "transaction_count", "query_type": "kpi", "chart_type": "kpi",
                "sql": f"SELECT COUNT(DISTINCT ct.id) AS transaction_count FROM customer_transactions AS ct{where};"}
    if any(term in q for term in ("total", "total amount", "transaction amount", "revenue")):
        return {"intent": "total_reporting_amount", "query_type": "kpi", "chart_type": "kpi",
                "sql": f"SELECT SUM(ct.reporting_currency_amount) AS reporting_amount FROM customer_transactions AS ct{where};"}
    return None


def explain_plan(sql: str, query_type: str, data: dict) -> dict:
    lower = sql.lower()
    filters = []
    if "year(ct.trans_date)" in lower: filters.append("the requested calendar year")
    if "interval" in lower: filters.append("a period relative to the newest available transaction")
    if "where" not in lower: filters.append("the full available transaction history")
    return {
        "logic": "The result is calculated directly from approved Cokebot AI transaction fields.",
        "filters": filters or ["the requested finance criteria"],
        "time_range": "Transaction dates are used as the time spine.",
        "source": "Cokebot AI customer transaction data",
        "assumptions": ["Reporting currency is used for cross-currency totals.", "Results are limited to safe display sizes."],
        "query_type": query_type,
        "records_examined": len(data.get("rows", [])),
    }

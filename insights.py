"""Small, dependency-free helpers for the executive insight layer."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import re

MAX_DATA_YEAR = 2026


def is_obviously_out_of_scope(question: str) -> bool:
    """Reject clear general-knowledge requests before spending an LLM call."""
    q = question.lower().strip()
    # These categories are never represented in the Cokebot AI transaction schema,
    # even when a question also contains a generic time word such as "today".
    disallowed_terms = {
        "weather", "rain", "temperature", "forecast", "football", "cricket", "match",
        "movie", "music", "politics", "election", "president", "capital", "recipe",
        "python", "programming", "code", "joke", "health", "medical", "stock price",
    }
    if any(re.search(rf"\b{re.escape(term)}\b", q) for term in disallowed_terms):
        return True
    # Keep stemmed/plural business vocabulary here. This check runs before the
    # local intent engine, so it must never reject valid phrasing such as
    # "transactions" or "customers".
    finance_patterns = (
        r"\bcokebot\b", r"\btransactions?\b", r"\bcustomers?\b", r"\bclients?\b",
        r"\bpayments?\b", r"\binvoices?\b", r"\bvouchers?\b", r"\bamounts?\b",
        r"\brevenue\b", r"\bsales?\b", r"\bcollections?\b", r"\baccounts?\b",
        r"\bbalances?\b", r"\bfinancial?\b", r"\bmonths?\b", r"\bquarters?\b",
        r"\byears?\b", r"\btoday\b", r"\byesterday\b", r"\btrends?\b",
        r"\btop\b", r"\bbottom\b", r"\bhighest\b", r"\blowest\b", r"\btotals?\b",
        r"\breports?\b", r"\bdata\b",
    )
    return bool(q) and not any(re.search(pattern, q) for pattern in finance_patterns)


def chart_type_for(query_type: str | None, data: dict) -> str | None:
    columns = [str(c).lower() for c in data.get("columns", [])]
    rows = data.get("rows", [])
    if not rows or len(rows) < 2:
        return None
    if query_type == "trend" or any("month" in c or "date" in c or "period" in c for c in columns):
        return "line"
    if query_type in {"ranking", "breakdown", "comparison"}:
        return "bar"
    return None


def build_insight(data: dict, query_type: str | None) -> dict | None:
    """Return a transparent deterministic headline; never invent a metric."""
    rows = data.get("rows", [])
    columns = data.get("columns", [])
    if not rows or not columns:
        return None
    numeric_cells = []
    for row in rows:
        for index, value in enumerate(row):
            try:
                numeric_cells.append((index, Decimal(str(value))))
            except Exception:
                continue
    if not numeric_cells:
        return {"headline": f"{len(rows):,} matching records found.", "record_count": len(rows)}
    index, value = numeric_cells[0]
    label = columns[index].replace("_", " ").title()
    return {
        "headline": f"{label}: {value:,}",
        "record_count": len(rows),
        "chart_type": chart_type_for(query_type, data),
    }

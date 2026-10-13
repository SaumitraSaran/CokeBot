import json
import re
from insights import MAX_DATA_YEAR


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twenty": 20,
    "thirty": 30,
    "fifty": 50,
    "hundred": 100,
    "two hundred": 200,
}


def _extract_limit(question: str, default: int = 5) -> int:
    q = re.sub(r"\bq00\b", "100", question.lower())

    if re.search(r"\b(all|everything|display all|show all)\b", q):
        return 200

    rank_words = r"(?:top|first|last|biggest|largest|highest|maximum|most|show|display|get|list|fetch)"
    match = re.search(rf"\b{rank_words}\s+(\d{{1,4}})\b", q)
    if not match:
        match = re.search(rf"\b(\d{{1,4}})\s+{rank_words}\b", q)
    if not match:
        # Match standalone numbers like 100 or 200 in the query
        match = re.search(r"\b(\d{1,4})\b", q)
    if match:
        val = int(match.group(1))
        return min(max(val, 1), 1000)

    match = re.search(
        rf"\b{rank_words}\s+((?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|fifty|hundred|two hundred))\b",
        q,
    )
    if not match:
        match = re.search(
            rf"\b((?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|fifty|hundred|two hundred))\s+{rank_words}\b",
            q,
        )
    if match:
        return _NUMBER_WORDS[match.group(1)]

    return default


def _is_top_customer_transactions(question: str) -> bool:
    q = re.sub(r"\bq00\b", "100", question.lower()).strip()

    # Direct short queries like "100", "200", "q00", "top 100", "top 200", "all", "display all"
    if q in ("100", "200", "top 100", "top 200", "all", "display all", "show all"):
        return True

    # If asking for 100 or 200 with customer or transaction
    if re.search(r"\b(100|200)\b", q) and re.search(r"\b(customer|customers|client|clients|transaction|transactions)\b", q):
        return True

    has_rank_word = re.search(
        r"\b(top|biggest|largest|highest|maximum|most|first|all|display|show|get|list|fetch|\d+)\b",
        q,
    )
    has_transaction_word = re.search(
        r"\b(transaction|transactions|purchase|purchases|payment|payments|expense|expenses)\b",
        q,
    )
    has_customer_context = re.search(r"\b(customer|customers|client|clients)\b", q)
    return bool(has_rank_word and (has_transaction_word or has_customer_context))



def build_local_query(user_question: str) -> dict | None:
    """Return intent and validated parameters for a local match."""
    question = " ".join(user_question.lower().split())
    years = [int(year) for year in re.findall(r"\b(\d{4})\b", question)]
    if any(year > MAX_DATA_YEAR for year in years):
        return None
    if not question or not _is_top_customer_transactions(question):
        return None

    limit = _extract_limit(question)
    query = {
        "intent": "top_customer_transactions",
        "parameters": {"limit": limit, "sort_by": "amount", "sort_order": "DESC"},
        "source": "local_intent",
    }
    return query

import json
import re
import traceback
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import brain
import guardrails as guardrails
from mysql_dispatcher import get_data
import query_cache as qcache
import sql_validator
import local_intent
import time
from threading import Lock
from insights import MAX_DATA_YEAR, build_insight, is_obviously_out_of_scope
from finance_features import GLOSSARY, explain_plan, glossary_match, local_plan, normalized_key
from operations import audit_event, list_monitors, save_monitor

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# Fast, bounded in-process cache for repeated executive questions. Results are
# keyed by the normalized question and expire quickly so financial data remains fresh.
_answer_cache = {}
_plan_cache = {}
_summary_cache = {}
_cache_lock = Lock()
_CACHE_TTL_SECONDS = 120

def get_query_from_brain(user_question, context=None):
    return brain.get_response(user_question, context)

def _cache_key(question: str, context: list) -> str:
    recent = " ".join(str(item.get("content", "")) for item in context[-2:])
    return " ".join((question + " " + recent).lower().split())

def _read_cache(key: str):
    with _cache_lock:
        entry = _answer_cache.get(key)
        if entry and time.monotonic() - entry[0] < _CACHE_TTL_SECONDS:
            return entry[1]
        _answer_cache.pop(key, None)
    return None

def _write_cache(key: str, payload: dict):
    with _cache_lock:
        if len(_answer_cache) > 250:
            _answer_cache.pop(next(iter(_answer_cache)))
        _answer_cache[key] = (time.monotonic(), payload)

def _clean_context(raw_context) -> list:
    if not isinstance(raw_context, list):
        return []
    cleaned = []
    for item in raw_context[-6:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", "")).strip()[:500]
        if role in {"user", "assistant"} and content:
            cleaned.append({"role": role, "content": content})
    return cleaned

def get_query_locally(user_question):
    approved_plan = local_plan(user_question)
    if approved_plan:
        return json.dumps(approved_plan)
    detected = local_intent.build_local_query(user_question)
    if not detected:
        return None

    template = qcache.lookup_intent_template(detected["intent"])
    if not template:
        return None

    sql = qcache.render_intent_template(template["query"], detected["parameters"])
    if not sql:
        return None

    detected["sql"] = sql
    detected["query_type"] = "ranking"
    return json.dumps(detected)

def get_response_from_brain(query, question):
    cache_key = " ".join((str(query) + question).lower().split())
    with _cache_lock:
        cached = _summary_cache.get(cache_key)
    if cached:
        return cached
    response = brain.get_natural_response(query, question)
    with _cache_lock:
        _summary_cache[cache_key] = response
    return response

def _trust_score(local_match: bool, data: dict) -> dict:
    has_error = data.get("columns") == ["Error"]
    return {
        "score": 96 if local_match else 82,
        "basis": "verified metric" if local_match else "validated AI query",
        "freshness": "Latest available transaction date",
        "records_returned": len(data.get("rows", [])),
        "truncated": bool(data.get("truncated")),
        "has_error": has_error,
    }

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/ask", methods=["POST"])
def ask():
    started_at = time.perf_counter()
    body = request.get_json(silent=True) or {}
    user_question = (body.get("question") or "").strip()
    context = _clean_context(body.get("context"))
    actor = str(body.get("actor") or "demo-user")

    if not user_question:
        return jsonify({"error": "No question provided."}), 400

    if guardrails.is_salutation(user_question):
        return jsonify({
            "answer": guardrails.SALUTATION_RESPONSE,
            "sql": None,
            "salutation": True,
        })

    if is_obviously_out_of_scope(user_question):
        return jsonify({"answer": guardrails.OUT_OF_SCOPE_RESPONSE, "sql": None, "out_of_scope": True})

    years = [int(year) for year in re.findall(r"\b(\d{4})\b", user_question)]
    if any(year > MAX_DATA_YEAR for year in years):
        return jsonify({"answer": guardrails.OUT_OF_SCOPE_RESPONSE, "sql": None, "out_of_scope": True})

    cache_key = _cache_key(user_question, context)
    cached_response = _read_cache(cache_key)
    if cached_response:
        cached_response = dict(cached_response)
        cached_response["meta"] = {**cached_response.get("meta", {}), "source": "cache", "latency_ms": 0}
        return jsonify(cached_response)

    try:
        # ── 1. Try deterministic intent recognition before any LLM call ──
        raw_query = get_query_locally(user_question)
        local_match = raw_query is not None
        if local_match:
            print("\n========== LOCAL INTENT HIT ==========")

        # ── 2. Use the LLM only when no stored intent template matches ──
        cached = None
        if not local_match:
            metric = glossary_match(user_question)
            if metric and not metric.get("expression"):
                return jsonify({"answer": metric["definition"], "sql": None, "unsupported_metric": metric})
            context_text = "\n".join(f"{item['role']}: {item['content']}" for item in context)
            raw_query = get_query_from_brain(user_question, context_text)
            print(f"\n========== CACHE MISS ==========")

        if raw_query is None:
            return jsonify({"error": "Brain returned no response."}), 502

        if "OUT_OF_SCOPE" in raw_query.strip():
            return jsonify({
                "answer": guardrails.OUT_OF_SCOPE_RESPONSE,
                "sql": None,
            })

        cleaned = raw_query.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        query = json.loads(cleaned)

        if query.get("unsupported_metric"):
            metric = query["unsupported_metric"]
            return jsonify({"answer": metric["definition"], "sql": None, "unsupported_metric": metric})

        if query.get("needs_clarification"):
            clarification = query.get("clarification", {})
            return jsonify({
                "answer": clarification.get("question", "Could you clarify your question?"),
                "options": clarification.get("options", []),
                "sql": None,
            })

        if not query.get("sql", ""):
            return jsonify({
                "answer": guardrails.OUT_OF_SCOPE_RESPONSE,
                "sql": None,
                "out_of_scope": True,
            })

        # Validate SQL before execution
        sql_string = query["sql"]
        is_valid, validation_error = sql_validator.validate_sql(sql_string)
        if not is_valid:
            return jsonify({
                "error": "The generated query failed security validation.",
                "details": validation_error,
                "sql": sql_string
            }), 403

        sql_started = time.perf_counter()
        data = get_data(sql_string)
        sql_latency_ms = round((time.perf_counter() - sql_started) * 1000)

        intent = query.get("intent")
        if not intent:
            detected = local_intent.build_local_query(user_question)
            if detected:
                intent = detected.get("intent")

        response = {
            "answer": None,
            "sql": sql_string,
            "data": data,
            "intent": intent,
            "query_type": query.get("query_type", "breakdown"),
            "insight": build_insight(data, query.get("query_type")),
            "explanation": explain_plan(sql_string, query.get("query_type", "breakdown"), data),
            "trust": _trust_score(local_match, data),
            "meta": {
                "source": "local intent" if local_match else "AI analysis",
                "latency_ms": round((time.perf_counter() - started_at) * 1000),
                "sql_latency_ms": sql_latency_ms,
                "data_through_year": MAX_DATA_YEAR,
            },
        }
        if query.get("chart_type"):
            response["insight"]["chart_type"] = query["chart_type"]
        _write_cache(cache_key, response)
        audit_event(actor, "answer", user_question, sql_string, {"source": response["meta"]["source"], "latency_ms": response["meta"]["latency_ms"]})
        return jsonify(response)

    except json.JSONDecodeError:
        return jsonify({
            "answer": guardrails.OUT_OF_SCOPE_RESPONSE,
            "sql": None,
            "out_of_scope": True,
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route("/api/answer", methods=["POST"])
def answer():
    body = request.get_json(silent=True) or {}
    user_question = (body.get("question") or "").strip()
    data = body.get("data")

    if not user_question:
        return jsonify({"error": "No question provided."}), 400

    try:
        response = get_response_from_brain(str(data), user_question)
        return jsonify({"answer": response})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route("/api/report", methods=["POST"])
@app.route("/api/feedback", methods=["POST"])
def report():
    body = request.get_json(silent=True) or {}
    user_question = (body.get("question") or "").strip()
    intent = (body.get("intent") or "").strip()
    is_correct = bool(body.get("is_correct", False))
    feedback = (body.get("feedback") or "").strip()

    if not user_question and not intent:
        return jsonify({"error": "Question or intent missing."}), 400

    # If it's reported as incorrect, ensure feedback/description is provided or noted
    if not is_correct and not feedback:
        feedback = "Incorrect output reported"

    try:
        if not intent and user_question:
            detected = local_intent.build_local_query(user_question)
            if detected:
                intent = detected["intent"]
            else:
                # Default to top_customer_transactions if present in frequent_queries
                intent = "top_customer_transactions"

        result = qcache.record_query_feedback(
            intent=intent,
            is_correct=is_correct,
            feedback=feedback,
            user_question=user_question,
        )

        if "error" in result:
            return jsonify(result), 400

        return jsonify(result)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route("/api/stats", methods=["GET"])
def stats():
    intent = request.args.get("intent", "top_customer_transactions")
    result = qcache.get_query_stats(intent)
    if not result:
        return jsonify({"error": f"No stats found for intent '{intent}'"}), 404
    return jsonify(result)

@app.route("/api/glossary", methods=["GET"])
def glossary():
    return jsonify(GLOSSARY)

@app.route("/api/monitors", methods=["GET", "POST"])
def monitors():
    actor = str(request.args.get("actor") or (request.get_json(silent=True) or {}).get("actor") or "demo-user")
    if request.method == "GET":
        return jsonify({"monitors": list_monitors(actor)})
    body = request.get_json(silent=True) or {}
    try:
        monitor = save_monitor(actor, str(body.get("name") or "Finance monitor"), str(body.get("metric") or ""), float(body.get("threshold")), str(body.get("operator") or ">"))
        audit_event(actor, "monitor_created", metadata=monitor)
        return jsonify(monitor), 201
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/command-center", methods=["GET"])
def command_center():
    """Compact, verified home-screen feed anchored to the current dataset."""
    latest = "(SELECT MAX(trans_date) FROM customer_transactions)"
    queries = {
        "yesterday_amount": f"SELECT COALESCE(SUM(reporting_currency_amount), 0) AS value FROM customer_transactions WHERE trans_date = {latest} - INTERVAL 1 DAY;",
        "latest_amount": f"SELECT COALESCE(SUM(reporting_currency_amount), 0) AS value FROM customer_transactions WHERE trans_date = {latest};",
        "active_customers": f"SELECT COUNT(DISTINCT customer_party) AS value FROM customer_transactions WHERE trans_date >= DATE_FORMAT({latest}, '%Y-%m-01');",
        "largest_customer": f"SELECT customer_name AS label, SUM(reporting_currency_amount) AS value FROM customer_transactions WHERE trans_date >= DATE_FORMAT({latest}, '%Y-%m-01') GROUP BY customer_name ORDER BY value DESC LIMIT 1;",
    }
    cards = {}
    for name, sql in queries.items():
        cards[name] = get_data(sql, max_rows=1)
    return jsonify({"cards": cards, "freshness": "Latest available transaction date", "suggestions": ["Show the 6-month transaction trend", "Compare this month with last month", "Show top 10 customers"]})

@app.route("/api/investigate", methods=["POST"])
def investigate():
    """Deterministic root-cause decomposition over dimensions present in the data."""
    latest = "(SELECT MAX(trans_date) FROM customer_transactions)"
    sql = f"""SELECT COALESCE(payment_mode, 'Unspecified') AS payment_mode,
        SUM(CASE WHEN trans_date >= DATE_FORMAT({latest}, '%Y-%m-01') THEN reporting_currency_amount ELSE 0 END) AS current_period,
        SUM(CASE WHEN trans_date >= DATE_FORMAT({latest} - INTERVAL 1 MONTH, '%Y-%m-01')
                  AND trans_date < DATE_FORMAT({latest}, '%Y-%m-01') THEN reporting_currency_amount ELSE 0 END) AS prior_period,
        SUM(CASE WHEN trans_date >= DATE_FORMAT({latest}, '%Y-%m-01') THEN reporting_currency_amount ELSE 0 END) -
        SUM(CASE WHEN trans_date >= DATE_FORMAT({latest} - INTERVAL 1 MONTH, '%Y-%m-01')
                  AND trans_date < DATE_FORMAT({latest}, '%Y-%m-01') THEN reporting_currency_amount ELSE 0 END) AS change_amount
        FROM customer_transactions GROUP BY COALESCE(payment_mode, 'Unspecified')
        ORDER BY ABS(change_amount) DESC LIMIT 8;"""
    data = get_data(sql, max_rows=8)
    return jsonify({"answer": "Largest month-over-month drivers by payment mode.", "data": data, "query_type": "comparison", "insight": build_insight(data, "comparison"), "explanation": explain_plan(sql, "comparison", data)})

if __name__ == "__main__":
    app.run(debug=False, port=5002)

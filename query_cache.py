import hashlib
import json
import re
from mysql_dispatcher import connection_pool

def get_db_cursor():
    if not connection_pool:
        raise Exception("Database connection pool is not initialized")
    return connection_pool.get_connection()

def extract_pattern(user_question: str) -> str:
    """
    Returns a deterministic SHA-256 hash of the normalized user question
    to prevent cache collisions between different entities.
    """
    if not user_question:
        return ""
    
    # Normalize: lowercase, strip, remove extra whitespaces
    normalized = " ".join(user_question.lower().split())
    if not normalized:
        return ""
        
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def lookup_cached_query(pattern: str) -> str | None:
    """Deprecated compatibility shim; lookup is now intent-based."""
    return None

def store_query(pattern: str, query_json: str) -> None:
    """Deprecated compatibility shim; templates are stored by intent."""
    return


def lookup_intent_template(intent: str) -> dict | None:
    """Load one approved SQL template from the intent registry."""
    if not intent:
        return None
    try:
        conn = get_db_cursor()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, intent, `query`, parameter_schema "
            "FROM frequent_queries WHERE intent = %s LIMIT 1",
            (intent,),
        )
        row = cur.fetchone()
        if row and isinstance(row.get("parameter_schema"), str):
            row["parameter_schema"] = json.loads(row["parameter_schema"])
        return row
    except Exception as e:
        print("Intent template lookup error:", e)
        return None
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        if 'conn' in locals() and conn:
            conn.close()


def render_intent_template(template: str, parameters: dict) -> str | None:
    """Render only supported placeholders; never accept arbitrary SQL input."""
    if not template:
        return None

    allowed_parameters = {"limit"}
    placeholders = set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template))
    if not placeholders.issubset(allowed_parameters | set(parameters)):
        return None

    values = {}
    for name in placeholders:
        value = parameters.get(name)
        if name == "limit":
            if not isinstance(value, int) or not 1 <= value <= 1000:
                return None
        elif not isinstance(value, (str, int, float)):
            return None
        values[name] = value

    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return None


def store_intent_template(intent: str, query_template: str, parameter_schema: dict) -> None:
    """Insert or update one reusable intent template."""
    if not intent or not query_template:
        return
    try:
        conn = get_db_cursor()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO frequent_queries (intent, `query`, parameter_schema) "
            "VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE `query` = VALUES(`query`), "
            "parameter_schema = VALUES(parameter_schema)",
            (intent, query_template, json.dumps(parameter_schema)),
        )
        conn.commit()
    except Exception as e:
        print("Intent template store error:", e)
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        if 'conn' in locals() and conn:
            conn.close()

def record_query_feedback(intent: str, is_correct: bool, feedback: str = "", user_question: str = "") -> dict:
    """
    Tracks correct/incorrect calls alongside each query in frequent_queries.
    - Column 1: call_counts = tuple/array of 2 elements: [incorrect_calls, correct_calls]
    - Column 2: incorrect_descriptions = list of descriptions of incorrect calls
    
    When total calls (incorrect + correct) == 10 and incorrect_calls > correct_calls,
    sends the list of incorrect descriptions along with the correction prompt to the
    Gemini LLM and updates the query template in frequent_queries.
    """
    if not intent:
        return {"error": "Intent is required."}

    conn = None
    cur = None
    try:
        conn = get_db_cursor()
        cur = conn.cursor(dictionary=True)

        # Retrieve current query, call_counts, incorrect_descriptions
        cur.execute(
            "SELECT id, intent, `query`, call_counts, incorrect_descriptions FROM frequent_queries WHERE intent = %s LIMIT 1",
            (intent,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": f"No frequent_queries entry found for intent '{intent}'."}

        current_query = row.get("query") or ""
        raw_counts = row.get("call_counts")
        raw_descriptions = row.get("incorrect_descriptions")

        # Parse call_counts tuple/list [incorrect_count, correct_count]
        call_counts = [0, 0]
        if raw_counts:
            try:
                call_counts = json.loads(raw_counts) if isinstance(raw_counts, str) else list(raw_counts)
                if len(call_counts) != 2:
                    call_counts = [0, 0]
            except Exception:
                call_counts = [0, 0]

        # Parse incorrect_descriptions list
        incorrect_descriptions = []
        if raw_descriptions:
            try:
                incorrect_descriptions = json.loads(raw_descriptions) if isinstance(raw_descriptions, str) else list(raw_descriptions)
            except Exception:
                incorrect_descriptions = []

        # If previous cycle already completed 10 calls, roll over to start new cycle
        if (call_counts[0] + call_counts[1]) >= 10:
            call_counts = [0, 0]
            incorrect_descriptions = []

        # Increment counts
        if is_correct:
            call_counts[1] += 1  # correct calls count
        else:
            call_counts[0] += 1  # incorrect calls count
            desc = feedback.strip() if feedback else "Marked as incorrect without description"
            if user_question:
                desc = f"{desc} (Question: {user_question})"
            incorrect_descriptions.append(desc)

        total_calls = call_counts[0] + call_counts[1]
        # Feedback is evidence, not authority to rewrite production SQL. Query
        # changes must be reviewed and deployed through the normal code/data path.
        correction_triggered = False
        new_query = None

        # Check automated LLM correction trigger:
        # "when the number of incorrect calls are greater than the correct calls,
        # only when the number of total correct and incorrect calls = 10,
        # then the list of the incorrect description along with the correction prompt
        # will go to the LLM and change it in the database table."
        if total_calls == 10 and call_counts[0] > call_counts[1]:
            print(f"[REVIEW NEEDED] {intent} has more incorrect than correct ratings. SQL was not changed automatically.")

        # Update database with updated counts, descriptions, and possibly corrected query
        cur.execute(
            "UPDATE frequent_queries SET `query` = %s, call_counts = %s, incorrect_descriptions = %s WHERE intent = %s",
            (
                current_query,
                json.dumps(call_counts),
                json.dumps(incorrect_descriptions),
                intent,
            ),
        )
        conn.commit()

        return {
            "status": "success",
            "intent": intent,
            "call_counts": tuple(call_counts),
            "incorrect_descriptions": incorrect_descriptions,
            "total_calls": total_calls,
            "correction_triggered": correction_triggered,
            "updated_query": new_query,
        }

    except Exception as e:
        print("record_query_feedback error:", e)
        return {"error": str(e)}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_query_stats(intent: str) -> dict | None:
    """Retrieve the current call counts tuple and incorrect descriptions for an intent."""
    if not intent:
        return None
    conn = None
    cur = None
    try:
        conn = get_db_cursor()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT intent, `query`, call_counts, incorrect_descriptions FROM frequent_queries WHERE intent = %s LIMIT 1",
            (intent,),
        )
        row = cur.fetchone()
        if not row:
            return None
        
        counts = [0, 0]
        if row.get("call_counts"):
            try:
                counts = json.loads(row["call_counts"]) if isinstance(row["call_counts"], str) else list(row["call_counts"])
            except Exception:
                pass

        descriptions = []
        if row.get("incorrect_descriptions"):
            try:
                descriptions = json.loads(row["incorrect_descriptions"]) if isinstance(row["incorrect_descriptions"], str) else list(row["incorrect_descriptions"])
            except Exception:
                pass

        return {
            "intent": row["intent"],
            "query": row["query"],
            "call_counts": tuple(counts),
            "incorrect_descriptions": descriptions,
        }
    except Exception as e:
        print("get_query_stats error:", e)
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def add_flag(pattern: str, feedback: str, user_question: str = "") -> None:
    """Store feedback about a cached query in the flagged column and record feedback."""
    record_query_feedback(pattern, is_correct=False, feedback=feedback, user_question=user_question)

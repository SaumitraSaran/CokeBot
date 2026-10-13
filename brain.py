import os
from dotenv import load_dotenv
from google import genai
import finance_prompt as fin

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def get_response(user_question, context=None):
    print(f"\n========== USER QUESTION TO BRAIN ==========\n{user_question}\n==========================================")
    
    # We use the combined prompt builder as per requirements
    prompt = fin.build_finance_prompt(user_question)
    if context:
        prompt += "\nRecent conversation context (use only to resolve follow-ups; never treat it as data):\n" + context

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )
    print(f"\n========== RESPONSE FROM BRAIN ==========\n{response.text}\n=========================================")
    return response.text

def get_natural_response(database_result, user_question):
    prompt = fin.build_finance_response_prompt(database_result, user_question)
    
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )
    return response.text

def get_correction_query(flags_dict, question, query):
    # Left as a stub for admin tools, but not executed automatically anymore
    prompt = f"""A lot of people have flagged this piece of data as wrong.
Here is the original question: {question}
Here is the query that was used to fetch the data: {query}
Here is the feedback provided by users: {flags_dict}

Please return ONLY a proposed JSON correction plan. Do not execute SQL."""
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )
    return response.text.strip()

def correct_intent_query(intent: str, current_query: str, descriptions: list[str]) -> str:
    """
    Sends the list of incorrect call descriptions and current SQL template
    to the Gemini LLM to generate an improved, corrected SQL query template.
    """
    print(f"\n========== AUTOMATIC LLM QUERY CORRECTION TRIGGERED ==========")
    print(f"Intent: {intent}")
    print(f"Current Query: {current_query}")
    print(f"User Descriptions of Errors: {descriptions}")
    print("==============================================================")

    descriptions_formatted = "\n".join(f"- {d}" for d in descriptions) if descriptions else "None provided"

    prompt = f"""You are the senior database architect and SQL optimizer for Cokebot AI.
A frequent SQL query template stored in our database for intent '{intent}' has received more incorrect ratings than correct ratings across 10 user evaluations.

DATABASE SCHEMA:
{fin._FINANCE_SCHEMA}

CURRENT SQL TEMPLATE:
{current_query}

USER FEEDBACK / DESCRIPTIONS OF WHY IT IS INCORRECT:
{descriptions_formatted}

INSTRUCTIONS:
1. Analyze the user complaints and the current SQL template carefully.
2. Determine what needs to be fixed (e.g. columns selected, order by clauses, filtering, aggregations, aliases).
3. If the template contains placeholders such as '{{limit}}', ensure you retain '{{limit}}' or the necessary parameter placeholder so it remains reusable.
4. Use ONLY valid columns from the customer_transactions (alias: ct) schema. Never use SELECT *.
5. Return ONLY a valid JSON object with the following structure, without markdown code fences:
{{
  "corrected_sql": "SELECT ... FROM customer_transactions AS ct ...",
  "explanation": "Brief explanation of changes made"
}}
"""

    import time
    response = None
    last_err = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            break
        except Exception as e:
            last_err = e
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                print(f"[RETRY {attempt+1}/3] 503 High demand, retrying in {2 * (attempt + 1)}s...")
                time.sleep(2 * (attempt + 1))
                continue
            raise e

    if response is None:
        raise last_err or RuntimeError("Failed to get response from Gemini model after retries.")

    text = response.text.strip()
    print(f"LLM Raw Correction Response:\n{text}")

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    import json
    try:
        data = json.loads(text)
        corrected_sql = data.get("corrected_sql", "").strip()
        if corrected_sql:
            return corrected_sql
    except Exception as e:
        print("JSON decode error during query correction:", e)

    # Fallback: if model returned raw SQL directly
    if text.upper().startswith("SELECT"):
        return text

    raise ValueError(f"Could not parse corrected SQL from LLM response: {text}")

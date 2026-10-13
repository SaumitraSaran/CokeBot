"""Durable operational features. Fail closed: audit/monitor failures never block answers."""
from __future__ import annotations

import json
from mysql_dispatcher import connection_pool


def _connection():
    if not connection_pool:
        return None
    return connection_pool.get_connection()


def audit_event(actor: str, event_type: str, question: str = "", sql: str = "", metadata: dict | None = None) -> None:
    conn = _connection()
    if not conn:
        return
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ai_query_audit (actor, event_type, question, sql_text, metadata) VALUES (%s, %s, %s, %s, %s)",
            (actor[:100], event_type[:40], question[:2000], sql[:10000], json.dumps(metadata or {})),
        )
        conn.commit()
    except Exception as exc:
        print("Audit write failed:", exc)
    finally:
        if cur: cur.close()
        conn.close()


def list_monitors(actor: str) -> list[dict]:
    conn = _connection()
    if not conn:
        return []
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, name, metric, threshold_value, operator, enabled, created_at FROM ai_saved_monitors WHERE actor = %s ORDER BY created_at DESC", (actor[:100],))
        return cur.fetchall()
    finally:
        if cur: cur.close()
        conn.close()


def save_monitor(actor: str, name: str, metric: str, threshold: float, operator: str) -> dict:
    if metric not in {"reporting_amount", "transaction_count"} or operator not in {">", "<", ">=", "<="}:
        raise ValueError("Unsupported monitor configuration")
    conn = _connection()
    if not conn:
        raise RuntimeError("Data service is unavailable")
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO ai_saved_monitors (actor, name, metric, threshold_value, operator) VALUES (%s, %s, %s, %s, %s)", (actor[:100], name[:120], metric, threshold, operator))
        conn.commit()
        return {"id": cur.lastrowid, "status": "saved"}
    finally:
        if cur: cur.close()
        conn.close()

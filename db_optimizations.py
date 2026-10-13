"""Apply idempotent performance and operational tables for the finance assistant."""
from mysql_dispatcher import connection_pool


INDEXES = {
    "idx_ct_trans_date": "trans_date",
    "idx_ct_customer_date": "customer_party, trans_date",
    "idx_ct_payment_date": "payment_mode, trans_date",
    "idx_ct_amount_date": "trans_date, reporting_currency_amount",
}


def apply() -> None:
    if not connection_pool:
        raise RuntimeError("Database connection pool is not initialized")
    conn = connection_pool.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""CREATE TABLE IF NOT EXISTS daily_finance_metrics (
            metric_date DATE NOT NULL PRIMARY KEY,
            reporting_amount DECIMAL(24,4) NOT NULL,
            transaction_count BIGINT NOT NULL,
            active_customers BIGINT NOT NULL,
            refreshed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_query_audit (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            actor VARCHAR(100) NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            question TEXT NULL,
            sql_text TEXT NULL,
            metadata JSON NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_audit_actor_time (actor, created_at)
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS ai_saved_monitors (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            actor VARCHAR(100) NOT NULL,
            name VARCHAR(120) NOT NULL,
            metric ENUM('reporting_amount','transaction_count') NOT NULL,
            threshold_value DECIMAL(24,4) NOT NULL,
            operator ENUM('>','<','>=','<=') NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_monitor_actor (actor, enabled)
        )""")
        for name, columns in INDEXES.items():
            cur.execute("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'customer_transactions' AND index_name = %s", (name,))
            if cur.fetchone()[0] == 0:
                cur.execute(f"CREATE INDEX {name} ON customer_transactions ({columns})")
                print("Created", name)
        cur.execute("""INSERT INTO daily_finance_metrics (metric_date, reporting_amount, transaction_count, active_customers)
            SELECT trans_date, SUM(reporting_currency_amount), COUNT(DISTINCT id), COUNT(DISTINCT customer_party)
            FROM customer_transactions WHERE trans_date >= '2000-01-01' GROUP BY trans_date
            ON DUPLICATE KEY UPDATE reporting_amount = VALUES(reporting_amount), transaction_count = VALUES(transaction_count), active_customers = VALUES(active_customers)""")
        conn.commit()
        print("Performance indexes, daily metrics, audit log, and monitors are ready.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    apply()

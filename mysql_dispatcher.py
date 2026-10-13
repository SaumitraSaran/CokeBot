import os
import mysql.connector
from mysql.connector import pooling
import guardrails as guardrails
from dotenv import load_dotenv
import decimal
import datetime

load_dotenv()

db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "12345678"),
    "database": os.getenv("DB_NAME", "SLMG_Trial")
}

# Create a connection pool
try:
    connection_pool = mysql.connector.pooling.MySQLConnectionPool(
        pool_name="mypool",
        pool_size=5,
        pool_reset_session=True,
        **db_config
    )
except Exception as e:
    print(f"Error creating connection pool: {e}")
    connection_pool = None

MAX_DISPLAY_ROWS = 500

def get_data(query: str | None, max_rows: int = MAX_DISPLAY_ROWS) -> dict:
    print(f"\n========== QUERY SENT TO MYSQL DISPATCHER ==========\n{query}\n====================================================")
    if query is None:
        return {"columns": [], "rows": []}
    
    if any(query.strip().upper().startswith(word) for word in guardrails.forbidden_queries):
        return {"columns": ["Error"], "rows": [[guardrails.OUT_OF_SCOPE_RESPONSE]]}
    
    if not connection_pool:
        return {"columns": ["Error"], "rows": [["Database connection pool is not initialized."]]}

    connection = None
    mycur = None
    try:
        connection = connection_pool.get_connection()
        mycur = connection.cursor()
        
        # MySQL's execution timeout is a session setting and not universally
        # available. Bounded fetching protects the web app from huge payloads.
        mycur.execute(query)
        columns = [desc[0] for desc in mycur.description] if mycur.description else []
        
        rows = []
        fetched_rows = mycur.fetchmany(max_rows + 1)
        truncated = len(fetched_rows) > max_rows
        for row in fetched_rows[:max_rows]:
            new_row = []
            for cell in row:
                if isinstance(cell, decimal.Decimal):
                    new_row.append(str(cell)) # Convert to string to preserve precision
                elif isinstance(cell, (datetime.date, datetime.datetime)):
                    new_row.append(str(cell))
                else:
                    new_row.append(cell)
            rows.append(tuple(new_row))
            
        return {"columns": columns, "rows": rows, "truncated": truncated}
    except Exception as e:
        print(f"Database execution error: {e}")
        return {"columns": ["Error"], "rows": [[f"Database execution error: {e}"]]}
    finally:
        if mycur:
            mycur.close()
        if connection:
            connection.close()

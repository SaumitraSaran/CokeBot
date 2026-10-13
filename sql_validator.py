import re

# Set of forbidden SQL keywords (DML, DDL, DCL, TCL, etc.)
FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", 
    "GRANT", "REVOKE", "MERGE", "CALL", "REPLACE", "SET", "EXECUTE", "EXEC"
}

def validate_sql(sql: str) -> tuple[bool, str]:
    """
    Validates a SQL query for safety.
    Returns (is_valid, error_message).
    """
    if not sql or not isinstance(sql, str):
        return False, "Query is empty or not a string."
    
    # Strip leading/trailing whitespaces
    sql = sql.strip()
    
    # 1. Remove comments to prevent them from bypassing checks.
    # Remove multi-line comments /* ... */
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    # Remove single line comments -- ... and # ...
    sql = re.sub(r'(--|#).*', '', sql)
    
    sql = sql.strip()
    
    if not sql:
        return False, "Query is empty after stripping comments."
    
    # 2. Reject multiple statements (look for semicolon that isn't at the very end)
    if ';' in sql and not sql.endswith(';'):
        return False, "Multiple statements are not allowed."
    if sql.count(';') > 1:
        return False, "Multiple statements are not allowed."
        
    # 3. Ensure the query is SELECT only.
    if not sql.upper().startswith("SELECT"):
        return False, "Query must be a SELECT statement."
        
    # 4. Check for forbidden keywords using word boundaries
    upper_sql = sql.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(r'\b' + keyword + r'\b', upper_sql):
            return False, f"Forbidden keyword detected: {keyword}"

    # The product data contract currently supports calendar years through 2026.
    for year in re.findall(r"(?<!\d)(\d{4})(?!\d)", sql):
        if int(year) > 2026:
            return False, "Queries cannot request data after 2026."
            
    # 5. Ensure only permitted table is referenced (customer_transactions)
    if "FROM" in upper_sql or "JOIN" in upper_sql:
        if "CUSTOMER_TRANSACTIONS" not in upper_sql:
            return False, "Query must reference the customer_transactions table."
            
        if "INFORMATION_SCHEMA" in upper_sql or "MYSQL." in upper_sql or "SYS." in upper_sql or "PERFORMANCE_SCHEMA" in upper_sql:
            return False, "Query attempting to access system tables."

    return True, "Valid SQL."

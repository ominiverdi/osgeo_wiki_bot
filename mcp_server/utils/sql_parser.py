# mcp_server/utils/sql_parser.py
import re
import sqlparse
from typing import Tuple, List, Optional

def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Validate SQL query for security concerns.
    Returns (is_valid, reason)
    """
    # Normalize whitespace and convert to lowercase for checks
    normalized_sql = ' '.join(sql.lower().split())
    
    # Check for dangerous SQL commands
    dangerous_commands = [
        'drop', 'truncate', 'delete', 'update', 'insert', 'alter', 'create',
        'grant', 'revoke', 'commit', 'rollback', 'vacuum', 'reindex'
    ]
    
    for command in dangerous_commands:
        pattern = r'\b' + command + r'\b'
        if re.search(pattern, normalized_sql):
            return False, f"Dangerous SQL command detected: {command}"
    
    # Only allow SELECT statements
    if not normalized_sql.strip().startswith('select'):
        return False, "Only SELECT statements are allowed"
    
    # Try to parse the SQL to ensure it's valid syntax
    try:
        parsed = sqlparse.parse(sql)
        if not parsed:
            return False, "Could not parse SQL"
    except Exception as e:
        return False, f"SQL parsing error: {str(e)}"
    
    # Simple check for SQL injection attempts
    injection_patterns = [
        r"--",                 # Comment
        r"/\*.*?\*/",          # Multi-line comment
        r";.*?$",              # Multiple statements
        r"xp_.*?",             # Extended stored procedures
        r"sp_.*?",             # Stored procedures
        r"exec.*?",            # Execute
    ]
    
    for pattern in injection_patterns:
        if re.search(pattern, normalized_sql):
            return False, "Potential SQL injection detected"
    
    return True, "SQL is valid"

def simplify_sql(sql: str) -> str:
    """
    Simplify a complex SQL query by removing some constraints.
    """
    # Parse the SQL
    parsed = sqlparse.parse(sql)[0]
    
    # Convert to string for regex operations (not ideal but simpler)
    sql_str = str(sql)
    
    # Simplify by removing some constraints from WHERE clause
    # This is a simplified approach - a real implementation would use a proper SQL parser
    where_pattern = r'WHERE(.*?)(?:ORDER BY|GROUP BY|LIMIT|$)'
    where_match = re.search(where_pattern, sql_str, re.IGNORECASE | re.DOTALL)
    
    if where_match:
        where_clause = where_match.group(1)
        conditions = where_clause.split('AND')
        
        # Remove half of the conditions if there are more than one
        if len(conditions) > 1:
            # Keep the first condition (usually the most important)
            simplified_where = conditions[0]
            
            # Replace the entire WHERE clause
            sql_str = re.sub(
                where_pattern,
                f'WHERE{simplified_where}\\2',
                sql_str,
                flags=re.IGNORECASE | re.DOTALL
            )
    
    return sql_str
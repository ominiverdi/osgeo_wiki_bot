# mcp_server/utils/sql_parser.py
import re
import sqlparse
from typing import Tuple, List, Optional

def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Validate SQL query with a more sophisticated approach.
    Returns (is_valid, reason)
    """
    # Normalize whitespace and convert to lowercase for checks
    normalized_sql = ' '.join(sql.lower().split())
    
    # Check for truly dangerous SQL commands only
    dangerous_commands = [
        'drop', 'truncate', 'delete', 'update', 'insert', 'alter', 'create',
        'grant', 'revoke', 'commit', 'rollback'
    ]
    
    # Only reject if these commands appear as standalone keywords, not in strings
    parsed = sqlparse.parse(sql)[0]
    tokens = [token for token in parsed.flatten() if not token.is_whitespace]
    
    for token in tokens:
        if (token.ttype is sqlparse.tokens.Keyword and 
            token.value.lower() in dangerous_commands):
            return False, f"Dangerous SQL command detected: {token.value}"
    
    # Ensure it's a SELECT statement
    if not parsed.get_type().lower() == 'select':
        return False, "Only SELECT statements are allowed"
    
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
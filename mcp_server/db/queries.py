# mcp_server/db/queries.py
from typing import Dict, List, Any, Optional, Tuple
import re
import logging
logger = logging.getLogger(__name__)


async def execute_search_query(sql: str, params: list = None) -> List[Dict[str, Any]]:
    """
    Execute a search query and return results as a list of dictionaries.
    
    Args:
        sql: SQL query string
        params: Optional list of query parameters
        
    Returns:
        List of result dictionaries
    """
    from mcp_server.db.connection import get_cursor  # Import here to avoid circular imports
    
    try:
        if params:
            # Simple string substitution for logging only - not for actual execution
            log_sql = sql
            for param in params:
                log_sql = log_sql.replace("%s", f"'{param}'", 1)
            logger.info(f"EXECUTING SQL: {log_sql}")

        with get_cursor() as cursor:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            
            # Return results as list of dictionaries
            return list(cursor.fetchall())
    except Exception as e:
        logger.error(f"Error executing search query: {e}")
        logger.error(f"SQL: {sql}")
        if params:
            logger.error(f"Params: {params}")
        return []


async def get_keyword_cloud() -> str:
    """Generate a keyword cloud from the most common terms in the wiki."""
    
    sql = """
    WITH term_counts AS (
        SELECT 
            word, 
            COUNT(*) as count
        FROM 
            ts_stat('SELECT to_tsvector(''english'', chunk_text) FROM page_chunks')
        WHERE 
            length(word) > 3  -- Skip very short words
            AND word NOT IN ('http', 'https', 'www', 'com', 'org', 'html')  -- Skip common URLs
            AND NOT word ~ '^\d+$'  -- Skip pure numbers
        GROUP BY 
            word
        ORDER BY 
            count DESC
        LIMIT 150
    )
    SELECT 
        word,
        GREATEST(1, LEAST(5, CEIL(LOG(2, count)))) as weight
    FROM 
        term_counts
    ORDER BY 
        count DESC;
    """
    
    try:
        results = await execute_search_query(sql)
        
        # Format as a weighted text cloud
        cloud_terms = []
        for result in results:
            word = result.get("word")
            weight = int(result.get("weight", 1))
            # Repeat important words based on weight
            cloud_terms.extend([word] * weight)
        
        # Shuffle slightly to avoid bias toward first terms
        import random
        random.shuffle(cloud_terms)
        
        return " ".join(cloud_terms)
    except Exception as e:
        logger.error(f"Error generating keyword cloud: {e}")
        return ""


async def get_top_categories() -> list:
    """Get the most commonly used categories from the wiki."""
    
    sql = """
    SELECT 
        category_name, 
        COUNT(*) as count
    FROM 
        page_categories
    WHERE 
        category_name NOT IN ('Categories', 'Category')
    GROUP BY 
        category_name
    ORDER BY 
        count DESC
    LIMIT 30;
    """
    
    try:
        results = await execute_search_query(sql)
        return [result.get("category_name") for result in results]
    except Exception as e:
        logger.error(f"Error fetching top categories: {e}")
        return []
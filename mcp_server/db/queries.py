# mcp_server/db/queries.py
from typing import Dict, List, Any, Optional, Tuple
import logging

from ..config import settings
from .connection import get_cursor

logger = logging.getLogger(__name__)

async def execute_search_query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Execute a search query and return the results."""
    try:
        with get_cursor() as cursor:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            
            results = cursor.fetchall()
            # Return as list of dictionaries
            return list(results)
    except Exception as e:
        logger.error(f"Error executing search query: {e}")
        logger.error(f"SQL: {sql}")
        if params:
            logger.error(f"Params: {params}")
        # Return empty list on error
        return []

async def execute_fallback_search(query: str, category: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """Execute a fallback search using websearch_to_tsquery directly."""
    sql = """
    SELECT DISTINCT p.id, p.title, p.url, pc.chunk_text,
           ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) AS rank
    FROM pages p
    JOIN page_chunks pc ON p.id = pc.page_id
    """
    
    where_clauses = ["pc.tsv @@ websearch_to_tsquery('english', %s)"]
    params = [query, query]  # First for WHERE, second for ts_rank
    
    # Add category filter if provided
    if category:
        sql += "JOIN page_categories cat ON p.id = cat.page_id "
        where_clauses.append("cat.category_name = %s")
        params.append(category)
    
    # Combine where clauses
    sql += f"WHERE {' AND '.join(where_clauses)} "
    
    # Add order by and limit
    sql += "ORDER BY rank DESC LIMIT %s"
    params.append(limit)
    
    return await execute_search_query(sql, params)

async def execute_category_boosted_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Execute a search with category boosting."""
    sql = """
    SELECT p.id, p.title, p.url, pc.chunk_text,
           ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) + 
           CASE WHEN EXISTS (
               SELECT 1 FROM page_categories pc2 
               WHERE pc2.page_id = p.id 
               AND lower(pc2.category_name) LIKE '%%' || lower(%s) || '%%'
           ) THEN 0.5 ELSE 0 END AS rank
    FROM pages p
    JOIN page_chunks pc ON p.id = pc.page_id
    LEFT JOIN page_categories pc2 ON p.id = pc2.page_id
    WHERE pc.tsv @@ websearch_to_tsquery('english', %s)
    GROUP BY p.id, p.title, p.url, pc.chunk_text
    ORDER BY rank DESC
    LIMIT %s
    """
    
    # Extract potential category term (longest word)
    terms = query.split()
    category_term = max(terms, key=len) if terms else ""
    
    params = [query, category_term, query, limit]
    return await execute_search_query(sql, params)

async def get_db_schema() -> str:
    """Get the database schema for the LLM."""
    schema_query = """
    SELECT 
        table_name, 
        column_name, 
        data_type, 
        column_default
    FROM 
        information_schema.columns
    WHERE 
        table_schema = 'public' AND
        table_name IN ('pages', 'page_chunks', 'page_categories')
    ORDER BY 
        table_name, ordinal_position;
    """
    
    try:
        schema_info = await execute_search_query(schema_query)
        
        # Format schema as string
        tables = {}
        for col in schema_info:
            if col['table_name'] not in tables:
                tables[col['table_name']] = []
            tables[col['table_name']].append(col)
        
        schema_str = ""
        for table_name, columns in tables.items():
            schema_str += f"Table: {table_name}\n"
            schema_str += "Columns:\n"
            for col in columns:
                default = f" DEFAULT {col['column_default']}" if col['column_default'] else ""
                schema_str += f"  - {col['column_name']} {col['data_type']}{default}\n"
            schema_str += "\n"
        
        return schema_str
    except Exception as e:
        logger.error(f"Error fetching schema: {e}")
        return "Error fetching schema"
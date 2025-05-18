from typing import Dict, List, Any, Optional, Tuple
import re
import logging
logger = logging.getLogger(__name__)

# Add these functions to mcp_server/db/queries.py

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

async def execute_keyword_search(keywords: dict, limit: int = 10) -> List[Dict[str, Any]]:
    """Execute a search using the extracted keywords with fallback strategy."""
    
    # Combine primary and secondary keywords
    primary_keywords = keywords.get("primary_keywords", [])
    secondary_keywords = keywords.get("secondary_keywords", [])
    
    # If no keywords were extracted, return empty results
    if not primary_keywords and not secondary_keywords:
        return []
    
    # Join the keywords with the OR operator for the search query
    if primary_keywords and secondary_keywords:
        # Weight primary keywords more heavily
        search_query = " | ".join(primary_keywords + secondary_keywords)
    elif primary_keywords:
        search_query = " | ".join(primary_keywords)
    else:
        search_query = " | ".join(secondary_keywords)
    
    print(f"==== SQL SEARCH ====")
    print(f"SEARCH QUERY: {search_query}")
    
    # Better ranking that considers title matches more important
    base_sql = """
    SELECT 
        p.id, p.title, p.url, pc.chunk_text,
        ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) + 
        CASE WHEN p.title ILIKE '%%' || %s || '%%' THEN 2.5 ELSE 0 END AS rank
    FROM 
        pages p
    JOIN 
        page_chunks pc ON p.id = pc.page_id
    WHERE 
        pc.tsv @@ websearch_to_tsquery('english', %s)
    """
    
    # Try search with category filtering if categories exist
    categories = keywords.get("categories", [])
    
    if categories:
        print(f"CATEGORIES: {categories}")
        category_where = "AND EXISTS (SELECT 1 FROM page_categories cat WHERE cat.page_id = p.id AND cat.category_name IN ({}))"
        category_where = category_where.format(", ".join(["%s"] * len(categories)))
        
        category_sql = base_sql + category_where + " ORDER BY rank DESC LIMIT %s"
        
        # The main keyword appears twice - once for ts_rank and once for title ILIKE
        category_params = [search_query, search_query.split(" | ")[0], search_query] + categories + [limit]
        
        category_results = await execute_search_query(category_sql, category_params)
        
        if category_results and len(category_results) > 0:
            print(f"CATEGORY FILTERED RESULTS: {len(category_results)}")
            return category_results
        else:
            print("No results with category filtering, falling back to full search")
    
    # Fallback to search without category filtering
    fallback_sql = base_sql + " ORDER BY rank DESC LIMIT %s"
    # The main keyword appears twice - once for ts_rank and once for title ILIKE
    fallback_params = [search_query, search_query.split(" | ")[0], search_query, limit]
    
    results = await execute_search_query(fallback_sql, fallback_params)
    
    print(f"FALLBACK RESULTS COUNT: {len(results)}")
    if results and len(results) > 0:
        print(f"TOP FALLBACK RESULT: {results[0].get('title')} - {results[0].get('url')}")
    
    return results

async def execute_fallback_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Execute a simpler fallback search when keyword extraction doesn't yield results.
    This directly uses the query as input for websearch_to_tsquery.
    """
    # Simple sanitization - keep only words and spaces, limit length
    sanitized_query = re.sub(r'[^\w\s]', ' ', query)
    sanitized_query = ' '.join(sanitized_query.split()[:10])  # Limit to 10 words
    
    if not sanitized_query:
        return []
    
    sql = """
    SELECT 
        p.id, p.title, p.url, pc.chunk_text,
        ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) AS rank
    FROM 
        pages p
    JOIN 
        page_chunks pc ON p.id = pc.page_id
    WHERE 
        pc.tsv @@ websearch_to_tsquery('english', %s)
    ORDER BY 
        rank DESC
    LIMIT %s
    """
    
    params = [sanitized_query, sanitized_query, limit]
    
    return await execute_search_query(sql, params)

async def execute_search_query(sql: str, params: list = None) -> List[Dict[str, Any]]:
    """Execute a search query and return results as a list of dictionaries."""
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

async def execute_alternative_search(query_alternatives: List[str], limit: int = 10, rank_threshold: float = 0.1):
    """Execute search query with the exact query structure from test script."""
    alternatives_list = []
    
    # Format alternatives for SQL exactly as in test script
    for alt in query_alternatives:
        # Replace single quotes with double single quotes for SQL safety
        safe_alt = alt.replace("'", "''")
        alternatives_list.append(f"'{safe_alt}'")
    
    alternatives_sql = ", ".join(alternatives_list)
    
    sql = f"""
    WITH query_alternatives AS (
        SELECT unnest(ARRAY[{alternatives_sql}]) AS query_text
    ),
    ranked_chunks AS (
        SELECT 
            p.id AS page_id,
            p.title,
            p.url,
            pc.chunk_text,
            ts_rank(pc.tsv, websearch_to_tsquery('english', alt.query_text)) AS chunk_rank,
            alt.query_text
        FROM 
            page_chunks pc
        JOIN 
            pages p ON pc.page_id = p.id
        CROSS JOIN query_alternatives alt
        WHERE 
            pc.tsv @@ websearch_to_tsquery('english', alt.query_text)
    )
    SELECT 
        r.title,
        r.url,
        r.page_id as id,
        r.chunk_text,
        ts_headline('english', r.chunk_text, 
            websearch_to_tsquery('english', r.query_text),
            'MaxFragments=1, MaxWords=20, MinWords=3, StartSel=<<, StopSel=>>, HighlightAll=true'
        ) AS highlighted_text,
        r.chunk_rank AS rank
    FROM (
        SELECT DISTINCT ON (title, url) 
            title, url, page_id, chunk_text, query_text, chunk_rank
        FROM ranked_chunks
        WHERE chunk_rank >= {rank_threshold}
        ORDER BY title, url, chunk_rank DESC
    ) r
    ORDER BY 
        rank DESC
    LIMIT {limit};
    """
    
    return await execute_search_query(sql)
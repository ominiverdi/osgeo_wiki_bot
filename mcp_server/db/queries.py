from typing import Dict, List, Any, Optional, Tuple
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
    """Execute a search using the extracted keywords."""
    
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
    
    # Build SQL query with category boosting if applicable
    categories = keywords.get("categories", [])
    
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
    """
    
    params = [search_query, search_query]
    
    # Add category filtering if categories are present
    if categories:
        placeholders = ", ".join(["%s"] * len(categories))
        sql += f"""
        AND EXISTS (
            SELECT 1 
            FROM page_categories cat 
            WHERE cat.page_id = p.id 
            AND cat.category_name IN ({placeholders})
        )
        """
        params.extend(categories)
    
    # Complete the query with order by and limit
    sql += """
    ORDER BY 
        rank DESC
    LIMIT %s
    """
    params.append(limit)
    
    return await execute_search_query(sql, params)
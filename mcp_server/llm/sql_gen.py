# mcp_server/llm/sql_gen.py
from typing import Dict, List, Any, Optional
import logging
import json
import re

from ..config import settings

logger = logging.getLogger(__name__)

def create_sql_generation_prompt(query: str, schema: str) -> str:
    """Create a detailed prompt for SQL generation with rich examples."""
    return f"""
You are a PostgreSQL search expert for an OSGeo wiki chatbot. Your job is to create optimal search queries using PostgreSQL's full-text search capabilities.

DATABASE SCHEMA:
{schema}

USER QUERY: {query}

FULL-TEXT SEARCH GUIDELINES:
1. ALWAYS use `websearch_to_tsquery` instead of other tsquery functions for best results
2. ALWAYS include multiple related search terms to improve coverage
3. ALWAYS use proper ranking with `ts_rank(tsv, query)` ordered DESC
4. PREFER combining text search with relevant category filtering when possible
5. NEVER use category filtering alone without full-text search
6. ALWAYS return at least title, url, and chunk_text from search results
7. DO NOT use exact phrase matching or LIKE searches - use proper text search vectors

EXAMPLE QUERIES:

Example 1: "What is OSGeo?"
```sql
SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, websearch_to_tsquery('english', 'OSGeo foundation organization about mission purpose')) AS rank
FROM pages p
JOIN page_chunks pc ON p.id = pc.page_id
WHERE pc.tsv @@ websearch_to_tsquery('english', 'OSGeo foundation organization about mission purpose')
ORDER BY rank DESC
LIMIT 5;
```

Example 2: "Who is on the OSGeo board?"
```sql
SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, websearch_to_tsquery('english', 'OSGeo board directors members president officers')) AS rank
FROM pages p
JOIN page_chunks pc ON p.id = pc.page_id
LEFT JOIN page_categories cat ON p.id = cat.page_id
WHERE pc.tsv @@ websearch_to_tsquery('english', 'OSGeo board directors members president officers')
  AND (cat.category_name = 'Board' OR cat.category_name = 'Elections' OR pc.tsv @@ websearch_to_tsquery('english', 'board governance'))
ORDER BY rank DESC
LIMIT 7;
```

Example 3: "How is OSGeo governed?"
```sql
SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, websearch_to_tsquery('english', 'OSGeo governance structure board organization bylaws committees president')) AS rank
FROM pages p
JOIN page_chunks pc ON p.id = pc.page_id
LEFT JOIN page_categories cat ON p.id = cat.page_id
WHERE pc.tsv @@ websearch_to_tsquery('english', 'OSGeo governance structure board organization bylaws committees president')
  AND (cat.category_name IN ('Board', 'Governance', 'Elections') OR pc.tsv @@ websearch_to_tsquery('english', 'board governance committee president chair'))
ORDER BY 
  CASE WHEN cat.category_name = 'Board' THEN 2.0 ELSE 1.0 END * rank DESC
LIMIT 8;
```

Example 4: "What events does OSGeo organize?"
```sql
SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, websearch_to_tsquery('english', 'OSGeo events conference FOSS4G organize sprint')) AS rank
FROM pages p
JOIN page_chunks pc ON p.id = pc.page_id
LEFT JOIN page_categories cat ON p.id = cat.page_id
WHERE pc.tsv @@ websearch_to_tsquery('english', 'OSGeo events conference FOSS4G organize sprint')
  AND (cat.category_name IN ('Events', 'FOSS4G', 'Code Sprints', 'Past Events') OR pc.tsv @@ websearch_to_tsquery('english', 'event conference FOSS4G'))
ORDER BY rank DESC
LIMIT 5;
```

Example 5: "What projects are part of OSGeo?"
```sql
SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, websearch_to_tsquery('english', 'OSGeo projects software incubation official')) AS rank
FROM pages p
JOIN page_chunks pc ON p.id = pc.page_id
WHERE pc.tsv @@ websearch_to_tsquery('english', 'OSGeo projects software incubation official')
ORDER BY rank DESC
LIMIT 7;
```

Now create the optimal SQL query for the user's question about: {query}

SQL:
```sql
"""

def create_context_aware_sql_prompt(query: str, schema: str, query_context: Dict[str, Any]) -> str:
    """Create a context-aware prompt for SQL generation."""
    # Format the context information
    context_str = ""
    if query_context.get("is_followup", False):
        context_str += "This is a follow-up question. Previous conversation:\n"
        for msg in query_context.get("recent_messages", []):
            context_str += f"{msg['role']}: {msg['content']}\n"
        
        if "topic_entities" in query_context:
            context_str += f"\nMain topics: {', '.join(query_context['topic_entities'])}\n"
        
        if "recent_results" in query_context:
            context_str += "\nRecent search results:\n"
            for res in query_context["recent_results"]:
                context_str += f"- {res['title']}: {res['snippet'][:100]}...\n"
    
    # Build on the standard prompt but add context awareness
    base_prompt = create_sql_generation_prompt(query, schema)
    
    # Insert context information before the final instruction
    sql_prompt_parts = base_prompt.split("Now create the optimal SQL query")
    context_aware_prompt = f"{sql_prompt_parts[0]}\n{context_str}\nThis query is part of a conversation. {query_context.get('is_followup', False) and 'It is a follow-up question.' or ''}\n\nNow create the optimal SQL query{sql_prompt_parts[1]}"
    
    return context_aware_prompt

def extract_sql_from_response(text: str) -> str:
    """Extract SQL from generated LLM response."""
    # Look for SQL between SQL code fences or just return the text
    if "```sql" in text and "```" in text.split("```sql", 1)[1]:
        return text.split("```sql", 1)[1].split("```", 1)[0].strip()
    elif "```" in text and "```" in text.split("```", 1)[1]:
        # Sometimes the model might not include 'sql' after the first fence
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text.strip()

def create_response_generation_prompt(query: str, results: List[Dict[str, Any]]) -> str:
    """Create a detailed prompt for response generation based on search results."""
    try:
        # Convert results to a more manageable format
        simplified_results = []
        for i, result in enumerate(results):
            simplified_results.append({
                "index": i + 1,
                "title": result.get("title", "Untitled"),
                "url": result.get("url", "#"),
                "text": result.get("chunk_text", "")[:500] + ("..." if len(result.get("chunk_text", "")) > 500 else ""),
                "rank": float(result.get("rank", 0)) if "rank" in result else 0
            })
        
        results_json = json.dumps(simplified_results, indent=2)
    except Exception as e:
        logger.error(f"Error formatting results: {e}")
        # Fallback with less formatting
        results_json = str(results)
    
    return f"""
You are an expert assistant for the OSGeo wiki. You need to create a helpful response based on search results.

USER QUERY: {query}

SEARCH RESULTS:
{results_json}

RESPONSE GUIDELINES:
1. Focus on the most relevant information from the search results
2. Be accurate and factual based ONLY on the provided information
3. For governance questions, emphasize formal structures like the Board, President, and committees
4. Organize your response logically, starting with the most important information
5. If search results are insufficient, acknowledge limitations rather than inventing information
6. Keep your response concise (3-5 sentences) but comprehensive
7. Cite information sources by mentioning page titles when relevant

Your response:
"""

def create_context_aware_response_prompt(
    query: str, 
    results: List[Dict[str, Any]], 
    query_context: Dict[str, Any]
) -> str:
    """Create a context-aware prompt for response generation."""
    # Start with the standard prompt
    base_prompt = create_response_generation_prompt(query, results)
    
    # Format the context information
    context_str = ""
    if query_context.get("is_followup", False):
        context_str += "This is a follow-up question. Previous conversation:\n"
        for msg in query_context.get("recent_messages", []):
            context_str += f"{msg['role']}: {msg['content']}\n"
    
    # Insert context information before the final instruction
    response_prompt_parts = base_prompt.split("RESPONSE GUIDELINES:")
    context_aware_prompt = f"{response_prompt_parts[0]}\nCONVERSATION CONTEXT:\n{context_str}\n\nRESPONSE GUIDELINES:{response_prompt_parts[1]}"
    
    return context_aware_prompt
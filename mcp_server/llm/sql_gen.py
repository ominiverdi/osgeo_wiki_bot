# mcp_server/llm/sql_gen.py
from typing import Dict, List, Any, Optional
import logging

from ..config import settings

logger = logging.getLogger(__name__)

def create_sql_generation_prompt(query: str, schema: str) -> str:
    """Create a prompt for SQL generation."""
    return f"""
You are a SQL expert specializing in PostgreSQL. Your job is to convert natural language queries about OSGeo wiki content into SQL queries.

Database Schema:
{schema}

User Query: {query}

Rules:
1. Use websearch_to_tsquery for full-text search
2. Be careful with JOINs and ensure they're necessary
3. Return only the SQL query, nothing else
4. Ensure the SQL is valid PostgreSQL syntax

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
    
    return f"""
You are a SQL expert specializing in PostgreSQL. Your job is to convert natural language queries about OSGeo wiki content into SQL queries.

Database Schema:
{schema}

{context_str}

User Query: {query}

Rules:
1. Use websearch_to_tsquery for full-text search
2. Be careful with JOINs and ensure they're necessary
3. Return only the SQL query, nothing else
4. Ensure the SQL is valid PostgreSQL syntax
5. For follow-up questions, reference entities from previous queries if relevant

SQL:
```sql
"""

def extract_sql_from_response(text: str) -> str:
    """Extract SQL from generated LLM response."""
    # Look for SQL between SQL code fences or just return the text
    if "```sql" in text and "```" in text.split("```sql", 1)[1]:
        return text.split("```sql", 1)[1].split("```", 1)[0].strip()
    elif "```" in text and "```" in text.split("```", 1)[1]:
        # Sometimes the model might not include 'sql' after the first fence
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text.strip()
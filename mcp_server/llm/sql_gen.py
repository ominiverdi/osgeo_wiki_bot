# mcp_server/llm/sql_gen.py
from typing import Dict, List, Any, Optional
import logging
import json
import re

from ..config import settings

logger = logging.getLogger(__name__)

def create_keyword_extraction_prompt(query: str, keyword_cloud: str, categories: list) -> str:
    """Create a prompt for extracting search keywords from a user query."""
    
    # Format the categories as a readable list
    categories_str = "\n".join([f"- {cat}" for cat in categories])
    
    return f"""
You are a search assistant for the OSGeo wiki. Extract the most effective search keywords from the user's query.

OSGeo KEYWORD CLOUD:
{keyword_cloud}

MAIN WIKI CATEGORIES:
{categories_str}

USER QUERY: {query}

Based on the user query, extract keywords that will lead to the most relevant search results.
Return your response as a JSON object with the following structure:
{{
  "primary_keywords": ["most", "important", "terms"],
  "secondary_keywords": ["supporting", "context", "terms"],
  "categories": ["Relevant", "Categories", "To", "Filter"]
}}

Primary keywords should be the main focus of the search (1-3 terms).
Secondary keywords should provide context or related concepts (2-5 terms).
Categories should match the wiki categories that might contain relevant content.

JSON:
"""

async def extract_keywords_from_query(client, query: str, keyword_cloud: str, categories: list) -> dict:
    """Extract search keywords from a user query."""
    
    prompt = create_keyword_extraction_prompt(query, keyword_cloud, categories)
    
    result = await client.generate(
        prompt=prompt,
        temperature=0.3  # Low temperature for more deterministic output
    )
    
    # Extract JSON from the response
    try:
        # Find JSON object in the response
        json_match = re.search(r'(\{.*\})', result, re.DOTALL)
        if json_match:
            keywords_json = json.loads(json_match.group(1))
            return keywords_json
        else:
            # Fallback if no JSON is found
            return {
                "primary_keywords": [query],
                "secondary_keywords": [],
                "categories": []
            }
    except Exception as e:
        logger.error(f"Error parsing keyword extraction result: {e}")
        # Simple fallback
        return {
            "primary_keywords": [query],
            "secondary_keywords": [],
            "categories": []
        }
        
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
# mcp_server/llm/response_gen.py
from typing import Dict, List, Any, Optional
import json
import logging

logger = logging.getLogger(__name__)

# In mcp_server/llm/response_gen.py or mcp_server/llm/sql_gen.py
def create_response_generation_prompt(query: str, results: List[Dict[str, Any]]) -> str:
    """Create a prompt for response generation."""
    return f"""
You are an assistant specialized in explaining OSGeo wiki content.

User Query: {query}

SQL Results:
{json.dumps(results, indent=2)}

Generate a CONCISE, informative answer based on these results. Be brief but accurate.
- Use 3-5 short sentences maximum
- Focus ONLY on answering the exact query
- If asked about "what is OSGeo", prioritize general information about the organization itself
- Include the EXACT URL to the specific wiki page at the end (no markdown formatting)
- Do not wrap or alter the URL in any way
- Focus only on the most relevant information
- Do not ask follow-up questions

Your response:
"""

def create_context_aware_response_prompt(
    query: str, 
    results: List[Dict[str, Any]], 
    query_context: Dict[str, Any]
) -> str:
    """Create a context-aware prompt for response generation."""
    # Format the context information
    context_str = ""
    if query_context.get("is_followup", False):
        context_str += "This is a follow-up question. Previous conversation:\n"
        for msg in query_context.get("recent_messages", []):
            context_str += f"{msg['role']}: {msg['content']}\n"
    
    return f"""
You are an assistant specialized in explaining search results about OSGeo wiki content.

{context_str}

User Query: {query}

SQL Results:
{json.dumps(results, indent=2)}

Generate a concise, informative answer based on these results. Be conversational but precise.
If the results don't answer the query well, acknowledge this limitation.
If there are no results, mention that no information was found.
If this is a follow-up question, ensure your answer maintains continuity with the previous conversation.

Your response:
"""
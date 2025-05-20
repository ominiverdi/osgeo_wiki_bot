# mcp_server/llm/response_gen.py
from typing import Dict, List, Any, Optional
import json
import logging
from datetime import datetime   
logger = logging.getLogger(__name__)
from ..config import settings

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

def create_response_generation_prompt(query: str, results: List[Dict[str, Any]]) -> str:
    """Create prompt exactly matching the one in the test script."""
    # Use the exact date format from test script
    current_date = datetime.now().strftime("%A, %B %d, %Y")  # "Sunday, May 18, 2025"
    
    # Format search results for the LLM prompt exactly as in test script
    results_text = ""
    for i, result in enumerate(results, 1):
        results_text += f"Result {i}:\n"
        results_text += f"Title: {result.get('title', '')}\n"
        results_text += f"URL: {result.get('url', '')}\n"
        results_text += f"Relevance: {result.get('rank', 0):.2f}\n"
        
        # Include highlighted text if available
        if 'highlighted_text' in result:
            results_text += f"Content: {result['highlighted_text']}\n\n"
        else:
            results_text += f"Content: {result.get('chunk_text', '')[:200]}...\n\n"

    prompt = f"""
You are an expert assistant for the OSGeo wiki. Answer the following question based on the search results provided.

TODAY'S DATE: {current_date}

Question: {query}

Search Results:
{results_text}

Guidelines for your answer:
1. Synthesize information from multiple sources where appropriate.
2. Give precedence to information from higher-ranked results (higher relevance score).
3. When information appears contradictory, note the discrepancy and indicate which source seems more authoritative.
4. When dates, names, or specific facts are mentioned, include them precisely as they appear in the results.
5. If the search results don't contain enough information to answer confidently, acknowledge the limitations.
6. Format your answer in a concise, readable manner.
7. Include relevant URLs from the search results as references.
8. For list-type questions, organize information clearly if multiple items are found.

URL FORMATTING GUIDELINES:
- Place the URL on its own line at the end of your answer
- Do NOT put any brackets, parentheses or other punctuation immediately before or after the URL
- Format as: "Source: https://wiki.osgeo.org/example" (not "[https://...]" or "(https://...)")
- If citing multiple sources, put each URL on its own line
- Make sure to leave a space between any text and the URL

SPECIAL TIME-BASED INSTRUCTIONS:
9. "Next" means events occurring AFTER {current_date}.
10. "Last" or "latest" means the most recent events BEFORE {current_date}.
11. "Current" refers to the status as of {current_date}.
12. For historical questions (founding dates, etc.), prioritize sources that explicitly mention "founded", "established", or "started", NOT references to MOUs or partnerships.
13. For organizational roles (president, etc.), evaluate whether information is current as of {current_date} - check if there are date indicators in the search results.

Your response should be factual, helpful, and directly address the question without adding speculation beyond what's in the search results.
"""
    return prompt
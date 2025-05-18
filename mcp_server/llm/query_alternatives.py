# mcp_server/llm/query_alternatives.py
import json
import re
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from mcp_server.config import settings  

logger = logging.getLogger(__name__)

def create_query_alternatives_prompt(query: str, keyword_cloud: str, categories: list) -> str:
    """Create a prompt for LLM to generate alternative search queries."""
    # Format the categories as a readable list
    categories_str = "\n".join([f"- {cat}" for cat in categories])
    
    # Get current date for temporal context
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    return f"""
You are a search assistant for the OSGeo wiki. Generate alternative search queries that will help find relevant information.

OSGeo KEYWORD CLOUD:
{keyword_cloud}

MAIN WIKI CATEGORIES (for your reference):
{categories_str}

CURRENT DATE: {current_date}

USER QUERY: {query}

Analyze the query and respond with a JSON object containing ONLY:
- A "query_alternatives" array containing 3-5 alternative search queries, ordered from most specific to most general

Guidelines for generating alternatives:
- Make alternatives specific and varied to maximize search coverage
- Include temporality ("current", "latest", "{current_date[:4]}", etc.) when time-relevant
- Use quotes for exact phrases that should appear together
- Focus on terms that would likely appear in wiki pages
- Consider OSGeo's structure, events, and terminology
- For questions about recent or current information, include the current year ({current_date[:4]})
- For "who is" questions, focus on role titles, names, and positions

Examples:

Query: "What is OSGeo?"
CORRECT: {{
  "query_alternatives": [
    "OSGeo foundation description",
    "about OSGeo mission",
    "OSGeo organization overview",
    "what is OSGeo foundation"
  ]
}}

Query: "Who is the president of OSGeo?"
CORRECT: {{
  "query_alternatives": [
    "current OSGeo president name",
    "OSGeo president {current_date[:4]}",
    "who leads OSGeo foundation",
    "OSGeo board president"
  ]
}}

Query: "When was FOSS4G 2022 held?"
CORRECT: {{
  "query_alternatives": [
    "FOSS4G 2022 location date",
    "FOSS4G 2022 event details",
    "where when FOSS4G 2022",
    "FOSS4G 2022 conference"
  ]
}}

JSON:
"""

def extract_alternatives_from_response(text: str, query: str = "") -> List[str]:
    """Extract query alternatives JSON from the LLM response."""
    try:
        # Find JSON object in the response
        json_match = re.search(r'(\{[^{]*"query_alternatives".*\})', text, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            
        if json_match:
            alternatives_json = json.loads(json_match.group(1))
            alternatives = alternatives_json.get("query_alternatives", [])
            logger.debug(f"Extracted alternatives: {alternatives}")
            return alternatives
        else:
            # Fallback if no JSON is found
            logger.warning(f"No JSON found in query alternatives extraction response")
            return [query]  # Return original query as fallback
    except Exception as e:
        logger.error(f"Error parsing query alternatives extraction result: {e}")
        return [query]  # Return original query as fallback

async def extract_query_alternatives(client, query: str, keyword_cloud: str, categories: list) -> List[str]:
    """Generate alternative search queries from a user query."""
    
    prompt = create_query_alternatives_prompt(query, keyword_cloud, categories)
    
    result = await client.generate(
        prompt=prompt,
        temperature=settings.KEYWORD_TEMPERATURE
    )
    
    # Extract alternatives from the response
    alternatives = extract_alternatives_from_response(result, query)
    
    # Ensure we have at least one alternative (the original query)
    if not alternatives:
        alternatives = [query]
        
    return alternatives
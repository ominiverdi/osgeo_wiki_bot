# mcp_server/llm/keyword_extraction.py (rename from sql_gen.py)
from typing import Dict, List, Any, Optional
import logging
import json
import re

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

def extract_keywords_from_response(text: str, original_query: str = "") -> dict:
    """Extract JSON from the LLM response."""
    extraction_logger.debug(f"Original query: {original_query}")
    extraction_logger.debug(f"LLM response: {text}")
    
    try:
        # Find JSON object in the response
        json_match = re.search(r'(\{.*\})', text, re.DOTALL)
        if json_match:
            keywords_json = json.loads(json_match.group(1))
            extraction_logger.debug(f"Extracted keywords: {json.dumps(keywords_json, indent=2)}")
            return keywords_json
        else:
            # Fallback if no JSON is found
            extraction_logger.warning(f"No JSON found in keyword extraction response")
            return {
                "primary_keywords": [],
                "secondary_keywords": [],
                "categories": []
            }
    except Exception as e:
        extraction_logger.error(f"Error parsing keyword extraction result: {e}")
        # Simple fallback
        return {
            "primary_keywords": [],
            "secondary_keywords": [],
            "categories": []
        }
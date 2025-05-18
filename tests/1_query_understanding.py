# test_query_understanding.py
import json
import asyncio
import httpx
import re
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get LLM settings from .env
LLM_MODEL = os.getenv("LLM_MODEL", "gemma3:latest")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
TEMPERATURE = float(os.getenv("KEYWORD_TEMPERATURE", "0.1"))

# Current date to provide context for temporal queries
CURRENT_DATE = datetime.now().strftime("%Y-%m-%d")  # Format: 2025-05-18

# Test queries covering different query types
TEST_QUERIES = [
    "What is OSGeo?",
    "When was the last FOSS4G conference?",
    "Who is the president of OSGeo?",
    "How do I join OSGeo?",
    "Where was FOSS4G 2022 held?",
    "What projects are part of OSGeo?",
    "How does OSGeo's incubation process work?",
    "Can you explain what GDAL is used for?",
    "What are the local chapters of OSGeo?",
    "When was OSGeo founded?",
    "When was the first FOSS4G event?",  # Added to test "first" temporal queries
    "When is the next FOSS4G conference scheduled?"  # Added to test "next" temporal queries
]

# Sample data based on OSGeo wiki content
KEYWORD_CLOUD = """OSGeo foundation geospatial open source GIS mapping software 
                  community projects board conference FOSS4G event coordinate 
                  data geography python library local chapter committee meeting 
                  member repository code sprint"""

# Refined list of 16 core categories
CATEGORIES = [
    "OSGeo Member", "Board", "FOSS4G", "Incubation", 
    "Past Events", "Education", "Local Chapters", "Infrastructure",
    "Code Sprints", "Events", "Marketing", "Conference Committee",
    "Advocacy", "Journal", "OSGeoLive", "Projects"
]

def create_query_understanding_prompt(query):
    """Create a prompt for LLM to analyze query type and generate tiered keywords."""
    categories_str = "\n".join([f"- {cat}" for cat in CATEGORIES])
    
    return f"""
You are a search assistant for the OSGeo wiki. Analyze the query type and generate tiered search keywords.

OSGeo KEYWORD CLOUD:
{KEYWORD_CLOUD}

MAIN WIKI CATEGORIES (use EXACTLY these names, with exact spelling and capitalization):
{categories_str}

CURRENT DATE: {CURRENT_DATE}

USER QUERY: {query}

Analyze the query and respond with a JSON object containing:
1. A "query_type" field identifying the type of query (definitional, temporal, biographical, procedural, locational)
2. A "keyword_tiers" array containing tiers of search keywords from most specific to most general
3. A "categories" array of relevant wiki categories to filter by (use EXACTLY the names from the list above)

Pay close attention to these query types:

- Definitional queries: ("What is X?", "What does X do?")
  Focus on defining phrases, then key terms
  CORRECT: "What is OSGeo?" → [["\\\"OSGeo is\\\"", "\\\"about OSGeo\\\""], ["OSGeo", "foundation"]]
  INCORRECT: "What is OSGeo?" → [["\\\"What is OSGeo\\\""], ["OSGeo"]]

- Temporal queries: ("When did X happen?", "When will X occur?")
  Use specific years derived from current date
  For "last" events: Include current and previous years (e.g., 2025, 2024, 2023)
  For "first" events: Use terms like "first", "founding", "inaugural"
  For "next" or "upcoming" events: Include current AND future years (e.g., 2025, 2026, 2027)
  CORRECT: "When is the next FOSS4G?" → [["FOSS4G 2025", "FOSS4G 2026"]]
  INCORRECT: "When is the next FOSS4G?" → [["\\\"When is the next FOSS4G\\\""]]

- Locational queries: ("Where is X?", "Where was X held?")
  Focus on location terms, venues, places
  CORRECT: "Where was FOSS4G 2022 held?" → [["FOSS4G 2022 location", "FOSS4G 2022 venue"]]
  INCORRECT: "Where was FOSS4G 2022 held?" → [["\\\"Where was FOSS4G 2022 held\\\""]]
  This is a LOCATIONAL query, not temporal, even if it contains a year

- Biographical queries: ("Who is X?", "Who leads X?")
  Focus on person names and roles
  CORRECT: "Who is president?" → [["president OSGeo", "OSGeo leadership"]]
  INCORRECT: "Who is president?" → [["\\\"Who is president\\\""]]

- Procedural queries: ("How do I X?", "How does X work?")
  Include action verbs and process terms
  CORRECT: "How to join OSGeo?" → [["\\\"join OSGeo\\\"", "membership process"]]
  INCORRECT: "How to join OSGeo?" → [["\\\"How to join OSGeo\\\""]]

QUOTATION RULES:
1. NEVER quote the exact user query (e.g., "What is OSGeo?")
2. Only quote phrases likely to appear in the content (e.g., "OSGeo is a foundation")
3. For definitional queries, quote phrases like "X is", "about X", "X was founded"
4. For procedural queries, quote action phrases like "join X", "become a member"
5. Single words should NOT be quoted

IMPORTANT RULES:
1. For categories, use ONLY the exact names provided in the list above
2. "Where" questions are almost always LOCATIONAL, not temporal
3. "Next" or "upcoming" event queries should include future years (2025, 2026, 2027)
4. Carefully analyze whether a query is about a time (temporal) or a place (locational)

JSON:
"""

async def generate_from_ollama(prompt):
    """Generate response from Ollama API."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=60.0)
        if response.status_code == 200:
            return response.json()["response"]
        else:
            return f"Error: {response.status_code} - {response.text}"

def extract_json(text):
    """Extract JSON object from text response."""
    # Try to find JSON using regex
    json_match = re.search(r'(\{[^{]*"query_type".*\})', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            return {"error": "Could not parse JSON"}
    return {"error": "No JSON found in response"}

async def test_query(query):
    """Test a single query and return result."""
    prompt = create_query_understanding_prompt(query)
    response = await generate_from_ollama(prompt)
    json_obj = extract_json(response)
    return json_obj

async def main():
    """Test all queries and save results."""
    results = []
    
    print(f"Using model {LLM_MODEL} with temperature {TEMPERATURE}")
    print(f"Current date provided: {CURRENT_DATE}")
    print(f"Testing {len(TEST_QUERIES)} queries...\n")
    
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"Processing query {i}/{len(TEST_QUERIES)}: {query}")
        json_obj = await test_query(query)
        results.append({"query": query, "result": json_obj})
    
    # Save results to file
    with open("query_understanding_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    
    # Create a more readable output file with just queries and results
    with open("query_results.txt", "w", encoding="utf-8") as f:
        for item in results:
            f.write(f"QUERY: {item['query']}\n\n")
            f.write(json.dumps(item['result'], indent=2))
            f.write("\n\n" + "="*80 + "\n\n")
    
    print("\nTesting complete!")
    print("Results saved to query_understanding_results.json and query_results.txt")

if __name__ == "__main__":
    asyncio.run(main())
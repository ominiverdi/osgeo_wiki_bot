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
    "When was the first FOSS4G event?",
    "When is the next FOSS4G conference scheduled?"
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
    """Create a prompt for LLM to generate alternative search queries."""
    categories_str = "\n".join([f"- {cat}" for cat in CATEGORIES])
    
    return f"""
You are a search assistant for the OSGeo wiki. Generate alternative search queries that will help find relevant information.

OSGeo KEYWORD CLOUD:
{KEYWORD_CLOUD}

MAIN WIKI CATEGORIES (for your reference):
{categories_str}

CURRENT DATE: {CURRENT_DATE}

USER QUERY: {query}

Analyze the query and respond with a JSON object containing ONLY:
- A "query_alternatives" array containing 3-5 alternative search queries, ordered from most specific to most general

Guidelines for generating alternatives:
- Make alternatives specific and varied to maximize search coverage
- Include temporality ("current", "latest", "{CURRENT_DATE[:4]}", etc.) when time-relevant
- Use quotes for exact phrases that should appear together
- Focus on terms that would likely appear in wiki pages
- Consider OSGeo's structure, events, and terminology
- For questions about recent or current information, include the current year ({CURRENT_DATE[:4]})
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
    "OSGeo president {CURRENT_DATE[:4]}",
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
    json_match = re.search(r'(\{[^{]*"query_alternatives".*\})', text, re.DOTALL)
    if not json_match:
        # Fall back to any JSON-like structure in case the format varies
        json_match = re.search(r'(\{.*\})', text, re.DOTALL)
    
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
    
    
    print("\nTesting complete!")
    print("Results saved to query_understanding_results.json")

if __name__ == "__main__":
    asyncio.run(main())
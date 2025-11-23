#!/usr/bin/env python3
# test_language_response.py - Test answering in detected language
import asyncio
import httpx
import time
import json
import re

LLM_SERVER = "http://localhost:8080"

test_queries = [
    "What is OSGeo?",
    "¿Qué es OSGeo?",
    "Qu'est-ce que OSGeo?",
    "Was ist OSGeo?",
    "are you online?",
    "Explícame sobre GDAL",
]

async def detect_language(query):
    """Detect language and return code."""
    prompt = f"""Detect the language of this query.

Query: {query}

Return ONLY a JSON object: {{"language": "en"}}

JSON:"""
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{LLM_SERVER}/v1/chat/completions",
            json={
                "model": "granite-4.0-h-tiny-32k",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 50,
                "temperature": 0.1
            }
        )
        result = response.json()
        response_text = result['choices'][0]['message']['content'].strip()
        
        # Extract JSON
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'^```\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)
        
        json_match = re.search(r'\{.*?\}', response_text)
        if json_match:
            lang_obj = json.loads(json_match.group(0))
            return lang_obj.get('language', 'en')
        return 'en'

async def answer_in_language(query, lang_code):
    """Generate answer in specified language."""
    # Map codes to language names for clarity
    lang_names = {
        'en': 'English',
        'es': 'Spanish', 
        'fr': 'French',
        'de': 'German',
        'zh': 'Chinese'
    }
    lang_name = lang_names.get(lang_code, 'English')
    
    prompt = f"""Query: {query}

Provide a very short answer (1-2 sentences) in {lang_name}.

Answer:"""
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{LLM_SERVER}/v1/chat/completions",
            json={
                "model": "granite-4.0-h-tiny-32k",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.7
            }
        )
        result = response.json()
        return result['choices'][0]['message']['content'].strip()

async def test_query(query):
    """Test full cycle: detect language -> answer in that language."""
    print(f"\nQuery: {query}")
    print("-" * 70)
    
    # Step 1: Detect language
    lang = await detect_language(query)
    print(f"Detected language: {lang}")
    
    # Step 2: Answer in that language
    answer = await answer_in_language(query, lang)
    print(f"Answer: {answer}")

async def main():
    print("Language-Aware Response Test")
    print("=" * 70)
    
    for query in test_queries:
        await test_query(query)
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
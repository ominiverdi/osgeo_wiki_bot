#!/usr/bin/env python3
# test_separate_classification.py - Test language and type as separate calls
import asyncio
import httpx
import json
import re
import time

LLM_SERVER = "http://localhost:8080"

# Subset of test queries for quicker validation
test_queries = [
    # Meta - various languages
    ("are you online?", "meta", "en"),
    ("who are you?", "meta", "en"),
    ("¿quién eres?", "meta", "es"),
    ("¿estás en línea?", "meta", "es"),
    ("qui es-tu?", "meta", "fr"),
    ("bonjour", "meta", "fr"),
    ("wer bist du?", "meta", "de"),
    ("hallo", "meta", "de"),
    
    # Wiki - various languages
    ("What is OSGeo?", "wiki", "en"),
    ("Where was FOSS4G 2022?", "wiki", "en"),
    ("¿Qué es OSGeo?", "wiki", "es"),
    ("Explícame sobre GDAL", "wiki", "es"),
    ("Qu'est-ce que OSGeo?", "wiki", "fr"),
    ("Où était FOSS4G 2022?", "wiki", "fr"),
    ("Was ist OSGeo?", "wiki", "de"),
    ("Wo war FOSS4G 2022?", "wiki", "de"),
    
    # Edge cases
    ("ok", "meta", "en"),
    ("OSGeo", "wiki", "en"),
]

async def detect_language(query):
    """Detect language only."""
    prompt = f"""Detect the language of this query.

Query: {query}

Return ONLY a JSON object: {{"language": "en"}}

Replace "en" with the correct 2-letter code (en, es, fr, de, it, pt, zh).

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

async def classify_type(query):
    """Classify query type only."""
    prompt = f"""Classify this query:

Query: {query}

Types:
- "meta": About YOU the assistant (who are you, are you online, what can you do, help)
- "wiki": About OSGeo content (projects, events, people, technical topics, how-to)

Return ONLY JSON: {{"type": "wiki"}}

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
            type_obj = json.loads(json_match.group(0))
            return type_obj.get('type', 'wiki')
        return 'wiki'

async def classify_query(query):
    """Run both classification tasks separately."""
    # Run in parallel
    lang_task = detect_language(query)
    type_task = classify_type(query)
    
    lang, qtype = await asyncio.gather(lang_task, type_task)
    
    return {"language": lang, "type": qtype}

async def main():
    print("Separate Classification Test (Parallel Execution)")
    print("=" * 90)
    
    start_time = time.time()
    
    meta_correct = 0
    wiki_correct = 0
    lang_correct = 0
    total_meta = 0
    total_wiki = 0
    
    errors = []
    
    for query, expected_type, expected_lang in test_queries:
        classification = await classify_query(query)
        
        type_match = classification['type'] == expected_type
        lang_match = classification['language'] == expected_lang
        
        if expected_type == "meta":
            total_meta += 1
            if type_match:
                meta_correct += 1
        else:
            total_wiki += 1
            if type_match:
                wiki_correct += 1
        
        if lang_match:
            lang_correct += 1
        
        mark = "✓" if (type_match and lang_match) else "✗"
        
        if not (type_match and lang_match):
            errors.append({
                'query': query,
                'expected': f"{expected_type}/{expected_lang}",
                'got': f"{classification['type']}/{classification['language']}"
            })
        
        print(f"{mark} {query[:40]:<40} -> {classification['type']:<6} ({classification['language']}) "
              f"[expect: {expected_type}/{expected_lang}]")
    
    elapsed = time.time() - start_time
    
    print("=" * 90)
    print(f"Meta questions: {meta_correct}/{total_meta} correct ({meta_correct/total_meta*100:.1f}%)")
    print(f"Wiki questions: {wiki_correct}/{total_wiki} correct ({wiki_correct/total_wiki*100:.1f}%)")
    print(f"Language detection: {lang_correct}/{len(test_queries)} correct ({lang_correct/len(test_queries)*100:.1f}%)")
    print(f"Overall accuracy: {(meta_correct + wiki_correct)/len(test_queries)*100:.1f}%")
    print(f"Total time: {elapsed:.1f}s ({elapsed/len(test_queries)*1000:.0f}ms per query)")
    print(f"Note: Calls run in parallel, so time ~= single call time")
    
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  - '{err['query']}' expected {err['expected']}, got {err['got']}")

if __name__ == "__main__":
    asyncio.run(main())
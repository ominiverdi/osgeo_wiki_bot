#!/usr/bin/env python3
# test_query_classification.py - Test language detection and OSGeo classification
import asyncio
import httpx
import json
import re
import time

LLM_SERVER = "http://localhost:8080"

# Test queries with expected results
# Expanded test queries with diverse cases
test_queries = [
    # === Greetings - various languages ===
    ("hi", False, "en"),
    ("hello", False, "en"),
    ("hey", False, "en"),
    ("ok", False, "en"),
    ("thanks", False, "en"),
    ("hola", False, "es"),
    ("gracias", False, "es"),
    ("ciao", False, "it"),
    ("bonjour", False, "fr"),
    ("salut", False, "fr"),
    ("merci", False, "fr"),
    ("hallo", False, "de"),
    ("danke", False, "de"),
    
    # === Identity/status questions ===
    ("who are you?", False, "en"),
    ("what can you do?", False, "en"),
    ("are you online?", False, "en"),
    ("¿quién eres?", False, "es"),
    ("¿estás en línea?", False, "es"),
    ("qui es-tu?", False, "fr"),
    ("wer bist du?", False, "de"),
    
    # === General tech questions (not OSGeo) ===
    ("how to learn python", False, "en"),
    ("what is machine learning", False, "en"),
    ("best IDE for coding", False, "en"),
    ("docker tutorial", False, "en"),
    
    # === OSGeo projects - direct mentions ===
    ("What is OSGeo?", True, "en"),
    ("OSGeo", True, "en"),
    ("tell me about QGIS", True, "en"),
    ("GDAL tutorial", True, "en"),
    ("PostGIS installation", True, "en"),
    ("how to use GEOS", True, "en"),
    ("MapServer documentation", True, "en"),
    ("GeoServer setup", True, "en"),
    
    # === OSGeo projects - non-English ===
    ("¿Qué es OSGeo?", True, "es"),
    ("Explícame sobre GDAL", True, "es"),
    ("cómo instalar PostGIS", True, "es"),
    ("Qu'est-ce que OSGeo?", True, "fr"),
    ("tutoriel QGIS", True, "fr"),
    ("Was ist OSGeo?", True, "de"),
    ("GDAL Dokumentation", True, "de"),
    
    # === OSGeo events ===
    ("Where was FOSS4G 2022?", True, "en"),
    ("FOSS4G conference", True, "en"),
    ("Où était FOSS4G 2022?", True, "fr"),
    ("Wo war FOSS4G 2022?", True, "de"),
    
    # === OSGeo community projects ===
    ("what is OSGeo4W", True, "en"),
    ("TorchGeo documentation", True, "en"),
    ("how to use OSGeoLive", True, "en"),
    
    # === Geospatial terms (OSGeo-related) ===
    ("geospatial analysis", True, "en"),
    ("open source GIS", True, "en"),
    ("GIS software", True, "en"),
    
    # === Ambiguous cases ===
    ("maps", False, "en"),  # Could go either way, but likely OSGeo context
    ("database", False, "en"),  # Too general
    ("Python GIS", True, "en"),  # GIS makes it OSGeo-related
    
    # === Comparisons mentioning OSGeo ===
    ("QGIS vs ArcGIS", True, "en"),
    ("PostGIS or MongoDB", True, "en"),
    ("difference between GDAL and Rasterio", True, "en"),
    
    # === Questions about OSGeo people/governance ===
    ("OSGeo board members", True, "en"),
    ("who founded OSGeo", True, "en"),
    ("OSGeo Foundation history", True, "en"),
    
    # === Edge cases ===
    ("", False, "en"),  # Empty query
    ("???", False, "en"),  # Just punctuation
    ("asdfghjkl", False, "en"),  # Random text
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

async def classify_osgeo_related(query, lang='en'):
    """Determine if query is OSGeo-related."""
    
    prompt = f"""OSGeo-related terms and projects include:

OSGeo Official Projects: PostGIS, QGIS, GDAL, OGR, GEOS, PROJ, GeoTools, GeoServer, MapServer, 
GeoNetwork, pycsw, GeoNode, Marble, gvSIG, pgRouting, GRASS, OrfeoToolBox, deegree, ZOO-Project, 
OpenLayers, GeoMoose, Mapbender, PyWPS, pygeoapi, OSGeoLive

OSGeo Community Projects: OSGeo4W, Opticks, TorchGeo, mappyfile, ETF, PROJ-JNI, GeoStyler, 
Open Data Cube, MDAL, actinia, Pronto Raster, OWSLib, FDO, OSSIM, GeoServer Client PHP, Loader, 
GeoHealthCheck, Portable GIS, TEAM Engine, Giswater, MobilityDB, rasdaman, XYZ, MAPP, GeoExt, 
GC2, Vidi, GeoWebCache, MapGuide, mapfish, istSOS

OSGeo Terms: FOSS4G, OSGeo Foundation, OSGeo, geospatial, GIS, open source geospatial

Is this query about OSGeo (mentions projects, events, people, technical topics, foundation)?
Does this query explicitly mention any OSGeo project, event, or term listed above?

Return true ONLY if query mentions OSGeo projects/terms.
Return false for greetings, general chat, identity questions, exclamations, unclear, ambiguos or nonsense.

NOT OSGeo examples:
- Greetings: hello, hi, bonjour, hallo, hola, ciao, gracias, merci, danke
- Identity: who are you, qui es-tu, wer bist du, ¿quién eres?
- Capability: what can you do, help, aide, hilfe, ayuda
- Status: are you online, ok
- Nonsense: ???, asdfghjkl, empty strings

Query: {query}
Language: {lang}


Return ONLY JSON: {{"is_osgeo": true}}

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
            obj = json.loads(json_match.group(0))
            return obj.get('is_osgeo', False)
        return False

async def classify_query(query):
    """Run classification: language first, then check if OSGeo-related."""
    
    # Handle empty queries
    query_stripped = query.strip()
    if not query_stripped:
        return {"language": "en", "is_osgeo": False}

    # Check if query contains any alphanumeric characters
    if not any(c.isalnum() for c in query_stripped):
        return {"language": "en", "is_osgeo": False}
    
    # Detect language first
    lang = await detect_language(query_stripped)
    
    # Check if OSGeo-related
    is_osgeo = await classify_osgeo_related(query_stripped, lang)
    
    return {"language": lang, "is_osgeo": is_osgeo}

async def main():
    print("OSGeo Classification Test (Sequential: Language → OSGeo Check)")
    print("=" * 90)
    
    start_time = time.time()
    
    non_osgeo_correct = 0
    osgeo_correct = 0
    lang_correct = 0
    total_non_osgeo = 0
    total_osgeo = 0
    
    errors = []
    
    for query, expected_is_osgeo, expected_lang in test_queries:
        classification = await classify_query(query)
        
        osgeo_match = classification['is_osgeo'] == expected_is_osgeo
        lang_match = classification['language'] == expected_lang
        
        if expected_is_osgeo:
            total_osgeo += 1
            if osgeo_match:
                osgeo_correct += 1
        else:
            total_non_osgeo += 1
            if osgeo_match:
                non_osgeo_correct += 1
        
        if lang_match:
            lang_correct += 1
        
        mark = "✓" if (osgeo_match and lang_match) else "✗"
        
        if not (osgeo_match and lang_match):
            errors.append({
                'query': query,
                'expected': f"{'OSGeo' if expected_is_osgeo else 'non-OSGeo'}/{expected_lang}",
                'got': f"{'OSGeo' if classification['is_osgeo'] else 'non-OSGeo'}/{classification['language']}"
            })
        
        osgeo_str = "OSGeo" if classification['is_osgeo'] else "non-OSGeo"
        expected_str = "OSGeo" if expected_is_osgeo else "non-OSGeo"
        
        print(f"{mark} {query[:40]:<40} -> {osgeo_str:<10} ({classification['language']}) "
              f"[expect: {expected_str}/{expected_lang}]")
    
    elapsed = time.time() - start_time
    
    print("=" * 90)
    print(f"Non-OSGeo questions: {non_osgeo_correct}/{total_non_osgeo} correct ({non_osgeo_correct/total_non_osgeo*100:.1f}%)")
    print(f"OSGeo questions: {osgeo_correct}/{total_osgeo} correct ({osgeo_correct/total_osgeo*100:.1f}%)")
    print(f"Language detection: {lang_correct}/{len(test_queries)} correct ({lang_correct/len(test_queries)*100:.1f}%)")
    print(f"Overall accuracy: {(non_osgeo_correct + osgeo_correct)/len(test_queries)*100:.1f}%")
    print(f"Total time: {elapsed:.1f}s ({elapsed/len(test_queries)*1000:.0f}ms per query)")
    print(f"Note: Sequential execution - language detected first, then OSGeo check")
    
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  - '{err['query']}' expected {err['expected']}, got {err['got']}")
    
    

if __name__ == "__main__":
    asyncio.run(main())
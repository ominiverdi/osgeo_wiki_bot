"""
Query classification module for OSGeo Wiki Bot.

Handles:
- Language detection
- OSGeo-related query classification
"""

import httpx
import json
import re
import logging
from typing import Dict

from mcp_server.config import settings

logger = logging.getLogger(__name__)

# OSGeo projects and terms for classification context
OSGEO_CONTEXT = """OSGeo-related terms and projects include:

OSGeo Official Projects: PostGIS, QGIS, GDAL, OGR, GEOS, PROJ, GeoTools, GeoServer, MapServer, 
GeoNetwork, pycsw, GeoNode, Marble, gvSIG, pgRouting, GRASS, OrfeoToolBox, deegree, ZOO-Project, 
OpenLayers, GeoMoose, Mapbender, PyWPS, pygeoapi, OSGeoLive

OSGeo Community Projects: OSGeo4W, Opticks, TorchGeo, mappyfile, ETF, PROJ-JNI, GeoStyler, 
Open Data Cube, MDAL, actinia, Pronto Raster, OWSLib, FDO, OSSIM, GeoServer Client PHP, Loader, 
GeoHealthCheck, Portable GIS, TEAM Engine, Giswater, MobilityDB, rasdaman, XYZ, MAPP, GeoExt, 
GC2, Vidi, GeoWebCache, MapGuide, mapfish, istSOS

OSGeo Infrastructure: osgeo servers (osgeo6, osgeo7, osgeo8, etc), matrix service, IRC, 
mailing lists, wiki hosting, infrastructure, deployment, hosting services

OSGeo Terms: FOSS4G, OSGeo Foundation, OSGeo, geospatial, GIS, open source geospatial"""


async def detect_language(query: str) -> str:
    """
    Detect the language of a query.
    
    Args:
        query: User query string
        
    Returns:
        Full language name (English, Spanish, French, German, Italian, Portuguese, Chinese)
    """
    prompt = f"""Detect the language of this query.

Query: {query}

Return ONLY a JSON object with the FULL language name: {{"language": "English"}}

Examples:
- "hello" -> {{"language": "English"}}
- "hola" -> {{"language": "Spanish"}}
- "bonjour" -> {{"language": "French"}}
- "ciao" -> {{"language": "Italian"}}
- "hallo" -> {{"language": "German"}}

JSON:"""
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.LLM_BASE_URL}/v1/chat/completions",
                json={
                    "model": settings.LLM_MODEL,
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
                detected_lang = lang_obj.get('language', 'English')
                logger.debug(f"Detected language: {detected_lang} for query: {query[:50]}")
                return detected_lang
                
    except Exception as e:
        logger.warning(f"Language detection failed, defaulting to English: {e}")
        
    return 'English'


async def classify_osgeo_related(query: str, lang: str = 'en') -> bool:
    """
    Determine if a query is OSGeo-related.
    
    Args:
        query: User query string
        lang: Detected language code
        
    Returns:
        True if query is about OSGeo projects/topics, False otherwise
    """
    prompt = f"""{OSGEO_CONTEXT}

Is this query about OSGeo (mentions projects, events, people, technical topics, foundation)?
Does this query explicitly mention any OSGeo project, event, or term listed above?

Return true ONLY if query mentions OSGeo projects/terms.
Return false for greetings, general chat, identity questions, exclamations or nonsense.

NOT OSGeo: greetings (hello, hi, bonjour, hallo), 
   identity questions (who are you, qui es-tu), 
   status checks (are you online, ok)

Query: {query}
Language: {lang}

Return ONLY JSON: {{"is_osgeo": true}}

JSON:"""
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.LLM_BASE_URL}/v1/chat/completions",
                json={
                    "model": settings.LLM_MODEL,
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
                is_osgeo = obj.get('is_osgeo', False)
                logger.debug(f"OSGeo classification: {is_osgeo} for query: {query[:50]}")
                return is_osgeo
                
    except Exception as e:
        logger.warning(f"OSGeo classification failed, defaulting to False: {e}")
        
    return False


async def classify_query(query: str) -> Dict[str, any]:
    """
    Classify a query for language and OSGeo relevance.
    
    Args:
        query: User query string
        
    Returns:
        Dict with 'language' (str) and 'is_osgeo' (bool)
    """
    # Handle empty queries
    query_stripped = query.strip()
    if not query_stripped:
        logger.debug("Empty query detected")
        return {"language": "en", "is_osgeo": False}
    
    # Check if query contains any alphanumeric characters
    if not any(c.isalnum() for c in query_stripped):
        logger.debug("Query contains no alphanumeric characters")
        return {"language": "en", "is_osgeo": False}
    
    # Detect language first
    lang = await detect_language(query_stripped)
    
    # Check if OSGeo-related
    is_osgeo = await classify_osgeo_related(query_stripped, lang)
    
    logger.info(f"Classification result: lang={lang}, is_osgeo={is_osgeo} for query: {query_stripped[:50]}")
    
    return {"language": lang, "is_osgeo": is_osgeo}
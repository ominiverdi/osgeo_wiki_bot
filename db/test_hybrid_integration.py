#!/usr/bin/env python3
"""
Keyword extraction approach: LLM extracts keywords (positive/negative)
to optimize fulltext and semantic search, without generating SQL.

This tests whether simple keyword extraction is sufficient, or if
full SQL generation provides better results.
"""

import os
import time
import re
import asyncio
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'dbname': os.getenv('DB_NAME', 'osgeo_wiki'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

LLM_SERVER = os.getenv('LLM_SERVER', 'http://localhost:8080')

TEST_QUERIES = [
    'What is the relationship between QGIS and OSGeo?',
    'How is GDAL connected to Frank Warmerdam?',
    'List all OSGeo projects',
    'What is QGIS?',
    'What projects did Frank Warmerdam create?',
]


async def call_llm(prompt, timeout=60):
    """Call LLM API"""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{LLM_SERVER}/v1/chat/completions",
            json={
                "model": "granite-4.0-h-tiny-32k",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.1
            }
        )
        result = response.json()
        return result['choices'][0]['message']['content']


async def extract_keywords(query):
    """LLM extracts keywords for search optimization"""
    prompt = f"""Extract search keywords from: "{query}"

Return ONLY this format (nothing else):
INCLUDE: word1, word2, word3
EXCLUDE: word4, word5

Rules:
1. INCLUDE: 2-5 important terms that should appear in results
2. EXCLUDE: 0-2 terms to filter out (optional, use EXCLUDE: none if no exclusions)
3. For person names include both full name and last name
4. Keep terms simple and relevant to OSGeo wiki content
5. DO NOT include meta-terms like "search", "query", "keywords", "python"

Examples:

Query: "What is the relationship between QGIS and OSGeo?"
INCLUDE: QGIS, OSGeo
EXCLUDE: none

Query: "How is GDAL connected to Frank Warmerdam?"
INCLUDE: GDAL, Frank Warmerdam, Warmerdam
EXCLUDE: none

Query: "List all OSGeo projects"
INCLUDE: OSGeo, projects
EXCLUDE: proposal

Query: "What is QGIS?"
INCLUDE: QGIS
EXCLUDE: none

Now extract for: "{query}"
Return only the INCLUDE/EXCLUDE lines, nothing else."""

    try:
        response = await call_llm(prompt, timeout=15)
        
        # Clean response
        response = response.strip()
        
        # Parse INCLUDE
        include_match = re.search(r'INCLUDE:\s*(.+?)(?:\n|$)', response, re.IGNORECASE | re.MULTILINE)
        include = []
        if include_match:
            include_text = include_match.group(1).strip()
            include = [k.strip() for k in include_text.split(',') if k.strip() and k.strip().lower() not in ['none', 'n/a', '']]
        
        # Parse EXCLUDE
        exclude_match = re.search(r'EXCLUDE:\s*(.+?)(?:\n|$)', response, re.IGNORECASE | re.MULTILINE)
        exclude = []
        if exclude_match:
            exclude_text = exclude_match.group(1).strip()
            if exclude_text.lower() not in ['none', 'n/a', '', 'nothing']:
                exclude = [k.strip() for k in exclude_text.split(',') if k.strip() and k.strip().lower() not in ['none', 'n/a', '']]
        
        # Fallback: if no keywords extracted, use query terms
        if not include:
            include = [query]
        
        return {
            'include': include,
            'exclude': exclude,
            'raw_response': response
        }
        
    except Exception as e:
        print(f"    [KEYWORD EXTRACTION ERROR] {e}")
        return {'include': [query], 'exclude': [], 'raw_response': ''}


def build_search_query(keywords):
    """Build PostgreSQL websearch_to_tsquery from keywords"""
    query_parts = []
    
    # Add INCLUDE keywords
    if keywords['include']:
        query_parts.extend(keywords['include'])
    
    # Add EXCLUDE keywords with negation
    if keywords['exclude']:
        for term in keywords['exclude']:
            query_parts.append(f"!{term}")
    
    return ' '.join(query_parts)


async def search_fulltext_with_keywords(conn, query):
    """Search page_chunks using LLM-extracted keywords"""
    start = time.time()
    
    try:
        # Extract keywords
        keywords = await extract_keywords(query)
        search_query = build_search_query(keywords)
        
        # Execute search
        sql = """
            SELECT p.title, p.url, pc.chunk_text,
                   ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            WHERE pc.tsv @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 5;
        """
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [search_query, search_query])
            results = cur.fetchall()
        
        elapsed = time.time() - start
        return {
            'success': True,
            'results': results,
            'count': len(results),
            'time_ms': elapsed * 1000,
            'keywords': keywords,
            'search_query': search_query
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'results': [],
            'count': 0,
            'time_ms': (time.time() - start) * 1000
        }


async def search_semantic_with_keywords(conn, query):
    """Search page_extensions using LLM-extracted keywords"""
    start = time.time()
    
    try:
        # Extract keywords
        keywords = await extract_keywords(query)
        search_query = build_search_query(keywords)
        
        # Execute search
        sql = """
            SELECT page_title, wiki_url, resume, keywords as page_keywords,
                   ((0.6 * ts_rank(resume_tsv, websearch_to_tsquery('english', %s))) +
                    (0.4 * ts_rank(keywords_tsv, websearch_to_tsquery('english', %s))) +
                    CASE WHEN page_title_tsv @@ websearch_to_tsquery('english', %s) THEN 2.5 ELSE 0 END) as rank
            FROM page_extensions
            WHERE resume_tsv @@ websearch_to_tsquery('english', %s)
               OR keywords_tsv @@ websearch_to_tsquery('english', %s)
               OR page_title_tsv @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 5;
        """
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [search_query] * 6)
            results = cur.fetchall()
        
        elapsed = time.time() - start
        return {
            'success': True,
            'results': results,
            'count': len(results),
            'time_ms': elapsed * 1000,
            'keywords': keywords,
            'search_query': search_query
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'results': [],
            'count': 0,
            'time_ms': (time.time() - start) * 1000
        }


async def compare_keyword_extraction(conn, query):
    """Compare keyword extraction vs baseline"""
    print("\n" + "=" * 100)
    print(f"QUERY: {query}")
    print("=" * 100)
    
    # Search with keyword extraction
    fulltext_result = await search_fulltext_with_keywords(conn, query)
    semantic_result = await search_semantic_with_keywords(conn, query)
    
    # Show extracted keywords
    if fulltext_result['success']:
        print(f"\nExtracted keywords:")
        print(f"  INCLUDE: {', '.join(fulltext_result['keywords']['include'])}")
        if fulltext_result['keywords']['exclude']:
            print(f"  EXCLUDE: {', '.join(fulltext_result['keywords']['exclude'])}")
        else:
            print(f"  EXCLUDE: none")
        print(f"  Search query: {fulltext_result['search_query']}")
        print(f"  [RAW LLM] {fulltext_result['keywords']['raw_response'][:100]}...")
    
    # Show results
    print(f"\n{'FULLTEXT':<50} {'SEMANTIC':<50}")
    print(f"{'-' * 48}  {'-' * 48}")
    
    ft_status = f"✓ {fulltext_result['count']} results ({fulltext_result['time_ms']:.0f}ms)" if fulltext_result['success'] else "✗ FAILED"
    sem_status = f"✓ {semantic_result['count']} results ({semantic_result['time_ms']:.0f}ms)" if semantic_result['success'] else "✗ FAILED"
    
    print(f"{ft_status:<50} {sem_status:<50}")
    print()
    
    # Show top 3
    for i in range(min(3, max(
        len(fulltext_result['results']) if fulltext_result['success'] else 0,
        len(semantic_result['results']) if semantic_result['success'] else 0
    ))):
        ft_text = ""
        sem_text = ""
        
        if i < len(fulltext_result['results']):
            ft = fulltext_result['results'][i]
            ft_text = f"{i+1}. {ft['title'][:45]}"
        
        if i < len(semantic_result['results']):
            sem = semantic_result['results'][i]
            sem_text = f"{i+1}. {sem['page_title'][:45]}"
        
        print(f"{ft_text:<50} {sem_text:<50}")
    
    return {
        'query': query,
        'fulltext': fulltext_result,
        'semantic': semantic_result
    }


async def main():
    print("=" * 100)
    print("KEYWORD EXTRACTION TEST: LLM extracts keywords for fulltext/semantic search")
    print("=" * 100)
    print("\nTesting whether keyword extraction is sufficient, or if SQL generation is needed.")
    print("=" * 100)
    
    conn = psycopg2.connect(**DB_CONFIG)
    
    results = []
    
    try:
        for query in TEST_QUERIES:
            result = await compare_keyword_extraction(conn, query)
            results.append(result)
    
    finally:
        conn.close()
    
    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY: Keyword extraction approach")
    print("=" * 100)
    
    total_time_ft = sum(r['fulltext']['time_ms'] for r in results if r['fulltext']['success'])
    total_time_sem = sum(r['semantic']['time_ms'] for r in results if r['semantic']['success'])
    
    print(f"\nFulltext average: {total_time_ft / len(results):.0f}ms")
    print(f"Semantic average: {total_time_sem / len(results):.0f}ms")
    
    print("""
PROS:
- Faster than full SQL generation (~500ms vs ~3000ms)
- Simpler implementation
- Works for fulltext and semantic

CONS:
- Cannot generate complex graph queries
- Limited to keyword-based searches
- May miss context that SQL generation captures

RECOMMENDATION: 
Use keyword extraction for simple queries, SQL generation for relationships.
""")


if __name__ == "__main__":
    asyncio.run(main())
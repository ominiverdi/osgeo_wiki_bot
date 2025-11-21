#!/usr/bin/env python3
# db/test_search_comparison.py
import os
import sys
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'dbname': os.getenv('DB_NAME', 'osgeo_wiki'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

TEST_QUERIES = [
    "What is the relationship between QGIS and OSGeo?",
    "What projects did Frank Warmerdam work on?",
    "List all OSGeo projects",
    "Who are the members of OSGeo board?",
    "What organizations are connected to GDAL?"
]

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def search_page_chunks(conn, query):
    """Current method: search raw page chunks"""
    sql = """
        SELECT 
            p.title,
            p.url,
            pc.chunk_text,
            ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) as rank
        FROM page_chunks pc
        JOIN pages p ON pc.page_id = p.id
        WHERE pc.tsv @@ websearch_to_tsquery('english', %s)
        ORDER BY rank DESC
        LIMIT 10;
    """
    
    start = time.time()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [query, query])
            results = cur.fetchall()
        elapsed = time.time() - start
        return {
            'success': True,
            'results': results,
            'count': len(results),
            'time_ms': elapsed * 1000
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'time_ms': (time.time() - start) * 1000
        }

def search_page_extensions(conn, query):
    """Semantic search: LLM summaries and keywords"""
    sql = """
        SELECT 
            pe.page_title,
            pe.wiki_url,
            pe.resume,
            pe.keywords,
            ((0.6 * ts_rank(pe.resume_tsv, websearch_to_tsquery('english', %s))) + 
             (0.4 * ts_rank(pe.keywords_tsv, websearch_to_tsquery('english', %s))) + 
             CASE WHEN pe.page_title_tsv @@ websearch_to_tsquery('english', %s) THEN 2.5 ELSE 0 END) AS rank,
            ts_headline('english', pe.resume, websearch_to_tsquery('english', %s), 
                       'MaxFragments=2, MaxWords=30, MinWords=5, StartSel=<<, StopSel=>>') AS resume_headline
        FROM page_extensions pe
        WHERE (pe.resume_tsv @@ websearch_to_tsquery('english', %s) OR 
               pe.keywords_tsv @@ websearch_to_tsquery('english', %s) OR 
               pe.page_title_tsv @@ websearch_to_tsquery('english', %s))
        ORDER BY rank DESC
        LIMIT 10;
    """
    
    start = time.time()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, [query, query, query, query, query, query, query])
            results = cur.fetchall()
        elapsed = time.time() - start
        return {
            'success': True,
            'results': results,
            'count': len(results),
            'time_ms': elapsed * 1000
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'time_ms': (time.time() - start) * 1000
        }

def search_graph(conn, query):
    """Graph search: entity relationships"""
    # Simple heuristic to extract entity names from query
    query_lower = query.lower()
    
    # Determine query type and entities
    if "relationship" in query_lower or "connected" in query_lower:
        # Extract two entity names
        words = query.replace("?", "").split()
        entities = [w for w in words if w[0].isupper() and len(w) > 2]
        
        if len(entities) >= 2:
            sql = """
                SELECT 
                    e1.entity_name as subject,
                    er.predicate,
                    e2.entity_name as object,
                    p.title as source_page
                FROM entity_relationships er
                JOIN entities e1 ON er.subject_id = e1.id
                JOIN entities e2 ON er.object_id = e2.id
                JOIN pages p ON er.source_page_id = p.id
                WHERE (e1.entity_name ILIKE %s AND e2.entity_name ILIKE %s)
                   OR (e1.entity_name ILIKE %s AND e2.entity_name ILIKE %s)
                LIMIT 10;
            """
            params = [f'%{entities[0]}%', f'%{entities[1]}%', 
                     f'%{entities[1]}%', f'%{entities[0]}%']
        else:
            return {'success': False, 'error': 'Could not extract entities', 'time_ms': 0}
    
    elif "projects" in query_lower and "work" in query_lower:
        # "What projects did X work on?"
        person = None
        for word in query.split():
            if word[0].isupper() and len(word) > 2:
                person = word
                break
        
        if person:
            sql = """
                SELECT DISTINCT
                    e2.entity_name as project,
                    er.predicate as relationship,
                    p.title as source_page
                FROM entities e1
                JOIN entity_relationships er ON e1.id = er.subject_id OR e1.id = er.object_id
                JOIN entities e2 ON (er.object_id = e2.id AND e1.id = er.subject_id) 
                                  OR (er.subject_id = e2.id AND e1.id = er.object_id)
                JOIN pages p ON er.source_page_id = p.id
                WHERE e1.entity_name ILIKE %s
                  AND e2.entity_type = 'project'
                LIMIT 20;
            """
            params = [f'%{person}%']
        else:
            return {'success': False, 'error': 'Could not extract person name', 'time_ms': 0}
    
    elif "list" in query_lower or "all" in query_lower:
        # "List all X projects"
        org = None
        for word in query.split():
            if word[0].isupper():
                org = word
                break
        
        if org:
            sql = """
                SELECT DISTINCT
                    e2.entity_name as project
                FROM entities e1
                JOIN entity_relationships er ON e1.id = er.subject_id OR e1.id = er.object_id
                JOIN entities e2 ON (er.object_id = e2.id AND e1.id = er.subject_id) 
                                  OR (er.subject_id = e2.id AND e1.id = er.object_id)
                WHERE e1.entity_name ILIKE %s
                  AND e2.entity_type = 'project'
                LIMIT 50;
            """
            params = [f'%{org}%']
        else:
            return {'success': False, 'error': 'Could not extract organization', 'time_ms': 0}
    
    elif "members" in query_lower or "board" in query_lower:
        # "Who are the board members?"
        sql = """
            SELECT DISTINCT
                e1.entity_name as person,
                er.predicate as relationship,
                p.title as source_page
            FROM entities e1
            JOIN entity_relationships er ON e1.id = er.subject_id
            JOIN entities e2 ON er.object_id = e2.id
            JOIN pages p ON er.source_page_id = p.id
            WHERE e2.entity_name ILIKE '%OSGeo%'
              AND e2.entity_name ILIKE '%board%'
              AND e1.entity_type = 'person'
            LIMIT 30;
        """
        params = []
    
    elif "organizations" in query_lower or "connected" in query_lower:
        # "What organizations are connected to X?"
        entity = None
        for word in query.split():
            if word[0].isupper() and len(word) > 2:
                entity = word
                break
        
        if entity:
            sql = """
                SELECT DISTINCT
                    e2.entity_name as organization,
                    er.predicate as relationship,
                    p.title as source_page
                FROM entities e1
                JOIN entity_relationships er ON e1.id = er.subject_id OR e1.id = er.object_id
                JOIN entities e2 ON (er.object_id = e2.id AND e1.id = er.subject_id) 
                                  OR (er.subject_id = e2.id AND e1.id = er.object_id)
                JOIN pages p ON er.source_page_id = p.id
                WHERE e1.entity_name ILIKE %s
                  AND e2.entity_type = 'organization'
                LIMIT 20;
            """
            params = [f'%{entity}%']
        else:
            return {'success': False, 'error': 'Could not extract entity', 'time_ms': 0}
    else:
        return {'success': False, 'error': 'Query type not supported', 'time_ms': 0}
    
    start = time.time()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            results = cur.fetchall()
        elapsed = time.time() - start
        return {
            'success': True,
            'results': results,
            'count': len(results),
            'time_ms': elapsed * 1000
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'time_ms': (time.time() - start) * 1000
        }

def print_result_preview(result, method_name):
    """Print preview of results"""
    if not result['success']:
        print(f"  {method_name}: FAILED - {result.get('error', 'Unknown error')}")
        return
    
    print(f"  {method_name}: {result['count']} results in {result['time_ms']:.1f}ms")
    
    # Show first result
    if result['results']:
        first = result['results'][0]
        if 'subject' in first:  # Graph
            print(f"    → {first['subject']} -{first['predicate']}-> {first['object']}")
        elif 'project' in first:  # Graph project list
            print(f"    → {first['project']}")
        elif 'person' in first:  # Graph person list
            print(f"    → {first['person']} ({first.get('relationship', 'N/A')})")
        elif 'organization' in first:  # Graph org list
            print(f"    → {first['organization']} ({first.get('relationship', 'N/A')})")
        elif 'resume_headline' in first:  # page_extensions
            headline = first['resume_headline'][:80].replace('\n', ' ')
            print(f"    → {first['page_title'][:50]}: {headline}...")
        elif 'chunk_text' in first:  # page_chunks
            chunk = first['chunk_text'][:80].replace('\n', ' ')
            print(f"    → {first['title'][:50]}: {chunk}...")

def main():
    print("="*80)
    print("SEARCH METHOD COMPARISON TEST")
    print("="*80)
    print("\nMethods:")
    print("1. page_chunks     - Raw 500-char chunks (CURRENT)")
    print("2. page_extensions - LLM summaries + keywords (SEMANTIC)")
    print("3. graph           - Entity relationships (NEW)")
    print("="*80)
    
    conn = get_connection()
    
    all_results = []
    
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n[{i}/{len(TEST_QUERIES)}] {query}")
        print("-"*80)
        
        # Test all three methods
        chunks_result = search_page_chunks(conn, query)
        print_result_preview(chunks_result, "page_chunks    ")
        
        extensions_result = search_page_extensions(conn, query)
        print_result_preview(extensions_result, "page_extensions")
        
        graph_result = search_graph(conn, query)
        print_result_preview(graph_result, "graph          ")
        
        all_results.append({
            'query': query,
            'page_chunks': chunks_result,
            'page_extensions': extensions_result,
            'graph': graph_result
        })
    
    conn.close()
    
    # Summary comparison
    print("\n" + "="*80)
    print("PERFORMANCE SUMMARY")
    print("="*80)
    print(f"{'Query':<45} {'Chunks':<12} {'Extensions':<12} {'Graph':<12}")
    print("-"*80)
    
    for result in all_results:
        query_short = result['query'][:42] + "..." if len(result['query']) > 45 else result['query']
        
        chunks_time = f"{result['page_chunks']['time_ms']:.1f}ms" if result['page_chunks']['success'] else "FAILED"
        ext_time = f"{result['page_extensions']['time_ms']:.1f}ms" if result['page_extensions']['success'] else "FAILED"
        graph_time = f"{result['graph']['time_ms']:.1f}ms" if result['graph']['success'] else "FAILED"
        
        print(f"{query_short:<45} {chunks_time:<12} {ext_time:<12} {graph_time:<12}")
    
    # Calculate averages
    chunks_times = [r['page_chunks']['time_ms'] for r in all_results if r['page_chunks']['success']]
    ext_times = [r['page_extensions']['time_ms'] for r in all_results if r['page_extensions']['success']]
    graph_times = [r['graph']['time_ms'] for r in all_results if r['graph']['success']]
    
    if chunks_times and ext_times and graph_times:
        print("-"*80)
        avg_chunks = sum(chunks_times) / len(chunks_times)
        avg_ext = sum(ext_times) / len(ext_times)
        avg_graph = sum(graph_times) / len(graph_times)
        print(f"{'AVERAGE':<45} {avg_chunks:<12.1f} {avg_ext:<12.1f} {avg_graph:<12.1f}")
    
    # Result count comparison
    print("\n" + "="*80)
    print("RESULT COUNT COMPARISON")
    print("="*80)
    print(f"{'Query':<45} {'Chunks':<12} {'Extensions':<12} {'Graph':<12}")
    print("-"*80)
    
    for result in all_results:
        query_short = result['query'][:42] + "..." if len(result['query']) > 45 else result['query']
        
        chunks_count = result['page_chunks']['count'] if result['page_chunks']['success'] else 0
        ext_count = result['page_extensions']['count'] if result['page_extensions']['success'] else 0
        graph_count = result['graph']['count'] if result['graph']['success'] else 0
        
        print(f"{query_short:<45} {chunks_count:<12} {ext_count:<12} {graph_count:<12}")
    
    print("\n" + "="*80)
    print("OBSERVATIONS")
    print("="*80)
    print("\npage_chunks (current):")
    print("  + Fast, reliable")
    print("  - Returns raw text requiring extraction")
    print("  - No semantic understanding")
    
    print("\npage_extensions (semantic):")
    print("  + LLM-generated summaries (better context)")
    print("  + Keywords improve matching")
    print("  - Still text-based (not relationships)")
    print(f"  - Coverage: {5300}/{6000} pages (~88%)")
    
    print("\ngraph (relationships):")
    print("  + Returns direct answers (relationships)")
    print("  + Best for connection queries")
    print("  - Query classification needed")
    print("  - Temporal limitations (current vs past)")

if __name__ == "__main__":
    main()
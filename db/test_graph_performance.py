#!/usr/bin/env python3
# db/test_graph_performance.py
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

# Test queries: natural language -> graph interpretation
TEST_QUERIES = [
    {
        'query': 'What is the relationship between QGIS and OSGeo?',
        'graph_sql': """
            SELECT 
                e1.entity_name as subject,
                er.predicate,
                e2.entity_name as object,
                p.title as source_page
            FROM entity_relationships er
            JOIN entities e1 ON er.subject_id = e1.id
            JOIN entities e2 ON er.object_id = e2.id
            JOIN pages p ON er.source_page_id = p.id
            WHERE (e1.entity_name ILIKE '%QGIS%' AND e2.entity_name ILIKE '%OSGeo%')
               OR (e1.entity_name ILIKE '%OSGeo%' AND e2.entity_name ILIKE '%QGIS%')
            LIMIT 10;
        """,
        'fulltext_sql': """
            SELECT 
                p.title,
                p.url,
                pc.chunk_text,
                ts_rank(pc.tsv, websearch_to_tsquery('english', 'QGIS OSGeo relationship')) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            WHERE pc.tsv @@ websearch_to_tsquery('english', 'QGIS OSGeo relationship')
            ORDER BY rank DESC
            LIMIT 10;
        """
    },
    {
        'query': 'What projects did Frank Warmerdam work on?',
        'graph_sql': """
            SELECT DISTINCT
                e2.entity_name as project,
                er.predicate as relationship,
                p.title as source_page
            FROM entities e1
            JOIN entity_relationships er ON e1.id = er.subject_id OR e1.id = er.object_id
            JOIN entities e2 ON (er.object_id = e2.id AND e1.id = er.subject_id) 
                              OR (er.subject_id = e2.id AND e1.id = er.object_id)
            JOIN pages p ON er.source_page_id = p.id
            WHERE e1.entity_name ILIKE '%Frank Warmerdam%'
              AND e2.entity_type = 'project'
            LIMIT 20;
        """,
        'fulltext_sql': """
            SELECT 
                p.title,
                p.url,
                pc.chunk_text,
                ts_rank(pc.tsv, websearch_to_tsquery('english', 'Frank Warmerdam projects')) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            WHERE pc.tsv @@ websearch_to_tsquery('english', 'Frank Warmerdam projects')
            ORDER BY rank DESC
            LIMIT 10;
        """
    },
    {
        'query': 'List all OSGeo projects',
        'graph_sql': """
            SELECT DISTINCT
                e2.entity_name as project
            FROM entities e1
            JOIN entity_relationships er ON e1.id = er.subject_id OR e1.id = er.object_id
            JOIN entities e2 ON (er.object_id = e2.id AND e1.id = er.subject_id) 
                              OR (er.subject_id = e2.id AND e1.id = er.object_id)
            WHERE e1.entity_name ILIKE '%OSGeo%'
              AND e2.entity_type = 'project'
            LIMIT 50;
        """,
        'fulltext_sql': """
            SELECT 
                p.title,
                pc.chunk_text,
                ts_rank(pc.tsv, websearch_to_tsquery('english', 'OSGeo projects list')) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            WHERE pc.tsv @@ websearch_to_tsquery('english', 'OSGeo projects list')
            ORDER BY rank DESC
            LIMIT 10;
        """
    },
    {
        'query': 'Who are the members of OSGeo board?',
        'graph_sql': """
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
        """,
        'fulltext_sql': """
            SELECT 
                p.title,
                pc.chunk_text,
                ts_rank(pc.tsv, websearch_to_tsquery('english', 'OSGeo board members')) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            WHERE pc.tsv @@ websearch_to_tsquery('english', 'OSGeo board members')
            ORDER BY rank DESC
            LIMIT 10;
        """
    },
    {
        'query': 'What organizations are connected to GDAL?',
        'graph_sql': """
            SELECT DISTINCT
                e2.entity_name as organization,
                er.predicate as relationship,
                p.title as source_page
            FROM entities e1
            JOIN entity_relationships er ON e1.id = er.subject_id OR e1.id = er.object_id
            JOIN entities e2 ON (er.object_id = e2.id AND e1.id = er.subject_id) 
                              OR (er.subject_id = e2.id AND e1.id = er.object_id)
            JOIN pages p ON er.source_page_id = p.id
            WHERE e1.entity_name ILIKE '%GDAL%'
              AND e2.entity_type = 'organization'
            LIMIT 20;
        """,
        'fulltext_sql': """
            SELECT 
                p.title,
                pc.chunk_text,
                ts_rank(pc.tsv, websearch_to_tsquery('english', 'GDAL organizations')) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            WHERE pc.tsv @@ websearch_to_tsquery('english', 'GDAL organizations')
            ORDER BY rank DESC
            LIMIT 10;
        """
    }
]

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def run_query(conn, sql, label):
    """Run query and return results with timing."""
    start = time.time()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            results = cur.fetchall()
        elapsed = time.time() - start
        return {
            'success': True,
            'results': results,
            'count': len(results),
            'time_ms': elapsed * 1000,
            'label': label
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            'success': False,
            'error': str(e),
            'time_ms': elapsed * 1000,
            'label': label
        }

def print_result_summary(result):
    """Print summary of query result."""
    if not result['success']:
        print(f"  FAILED: {result['error'][:100]}")
        return
    
    print(f"  Results: {result['count']} rows in {result['time_ms']:.1f}ms")
    
    # Show first 3 results
    for i, row in enumerate(result['results'][:3], 1):
        if 'subject' in row:  # Graph result
            print(f"    {i}. {row['subject']} -{row['predicate']}-> {row['object']}")
        elif 'project' in row:  # Project list
            print(f"    {i}. {row['project']}")
        elif 'person' in row:  # Person list
            print(f"    {i}. {row['person']} ({row['relationship']})")
        elif 'organization' in row:  # Organization list
            print(f"    {i}. {row['organization']} ({row['relationship']})")
        elif 'title' in row:  # Fulltext result
            rank = row.get('rank', 0)
            print(f"    {i}. {row['title'][:60]} (rank: {rank:.3f})")

def main():
    print("="*80)
    print("GRAPH vs FULLTEXT PERFORMANCE TEST")
    print("="*80)
    
    conn = get_connection()
    
    results_summary = []
    
    for i, test in enumerate(TEST_QUERIES, 1):
        print(f"\n[{i}/{len(TEST_QUERIES)}] {test['query']}")
        print("-"*80)
        
        # Run graph query
        print("GRAPH QUERY:")
        graph_result = run_query(conn, test['graph_sql'], 'graph')
        print_result_summary(graph_result)
        
        # Run fulltext query
        print("\nFULLTEXT QUERY:")
        fulltext_result = run_query(conn, test['fulltext_sql'], 'fulltext')
        print_result_summary(fulltext_result)
        
        # Store for summary
        results_summary.append({
            'query': test['query'],
            'graph': graph_result,
            'fulltext': fulltext_result
        })
    
    conn.close()
    
    # Print comparison summary
    print("\n" + "="*80)
    print("PERFORMANCE SUMMARY")
    print("="*80)
    print(f"{'Query':<50} {'Graph (ms)':<15} {'Fulltext (ms)':<15} {'Winner'}")
    print("-"*80)
    
    for summary in results_summary:
        query_short = summary['query'][:47] + "..." if len(summary['query']) > 50 else summary['query']
        
        graph_time = summary['graph']['time_ms'] if summary['graph']['success'] else 999999
        fulltext_time = summary['fulltext']['time_ms'] if summary['fulltext']['success'] else 999999
        
        winner = "Graph" if graph_time < fulltext_time else "Fulltext"
        if graph_time == 999999 and fulltext_time == 999999:
            winner = "Both failed"
        
        print(f"{query_short:<50} {graph_time:<15.1f} {fulltext_time:<15.1f} {winner}")
    
    # Calculate averages
    graph_times = [s['graph']['time_ms'] for s in results_summary if s['graph']['success']]
    fulltext_times = [s['fulltext']['time_ms'] for s in results_summary if s['fulltext']['success']]
    
    if graph_times and fulltext_times:
        print("-"*80)
        print(f"{'AVERAGE':<50} {sum(graph_times)/len(graph_times):<15.1f} {sum(fulltext_times)/len(fulltext_times):<15.1f}")
    
    print("\n" + "="*80)
    print("ACCURACY ASSESSMENT")
    print("="*80)
    
    for summary in results_summary:
        print(f"\n{summary['query']}")
        graph_count = summary['graph']['count'] if summary['graph']['success'] else 0
        fulltext_count = summary['fulltext']['count'] if summary['fulltext']['success'] else 0
        
        print(f"  Graph returned {graph_count} specific relationships")
        print(f"  Fulltext returned {fulltext_count} text chunks")
        
        if graph_count > 0:
            print(f"  -> Graph provides DIRECT answers")
        else:
            print(f"  -> Graph found no relationships")
        
        if fulltext_count > 0:
            print(f"  -> Fulltext requires manual extraction from text")
        else:
            print(f"  -> Fulltext found no relevant chunks")

if __name__ == "__main__":
    main()
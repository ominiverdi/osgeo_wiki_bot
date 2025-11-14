#!/usr/bin/env python3
import psycopg2
import time
import os
from dotenv import load_dotenv

load_dotenv()

def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "osgeo_wiki"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        port=os.getenv("DB_PORT", "5432")
    )

def test_query(query_text, use_enhanced=False):
    """Test search performance with and without page_extensions."""
    conn = get_conn()
    
    if use_enhanced:
        # Option 2: JOIN with page_extensions
        sql = """
            SELECT 
                p.title,
                p.url,
                pc.chunk_text,
                pe.keywords,
                ts_rank(
                    setweight(to_tsvector('english', p.title), 'A') ||
                    setweight(to_tsvector('english', COALESCE(pe.keywords, '')), 'B') ||
                    setweight(to_tsvector('english', pc.chunk_text), 'C'),
                    websearch_to_tsquery('english', %s)
                ) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            LEFT JOIN page_extensions pe ON p.url = pe.wiki_url
            WHERE (
                setweight(to_tsvector('english', p.title), 'A') ||
                setweight(to_tsvector('english', COALESCE(pe.keywords, '')), 'B') ||
                setweight(to_tsvector('english', pc.chunk_text), 'C')
            ) @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 10;
        """
    else:
        # Current: Only chunks
        sql = """
            SELECT 
                p.title,
                p.url,
                pc.chunk_text,
                NULL as keywords,
                ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) as rank
            FROM page_chunks pc
            JOIN pages p ON pc.page_id = p.id
            WHERE pc.tsv @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 10;
        """
    
    start = time.time()
    with conn.cursor() as cur:
        cur.execute(sql, (query_text, query_text))
        results = cur.fetchall()
    elapsed = time.time() - start
    
    conn.close()
    return results, elapsed

# Test queries
test_queries = [
    "QGIS OSGeo relationship",
    "FOSS4G location",
    "board meeting minutes",
    "Frank Warmerdam projects",
    "code sprint"
]

print("="*70)
print("SEARCH PERFORMANCE COMPARISON")
print("="*70)

for query in test_queries:
    print(f"\nQuery: '{query}'")
    
    # Test without enhancement
    results_old, time_old = test_query(query, use_enhanced=False)
    print(f"  Current (chunks only): {len(results_old)} results in {time_old*1000:.1f}ms")
    
    # Test with enhancement
    results_new, time_new = test_query(query, use_enhanced=True)
    print(f"  Enhanced (with keywords): {len(results_new)} results in {time_new*1000:.1f}ms")
    
    if results_new and results_old:
        # Show top result comparison
        print(f"\n  Top result (current): {results_old[0][0][:50]}...")
        print(f"  Top result (enhanced): {results_new[0][0][:50]}...")
        if results_new[0][3]:  # keywords
            print(f"  Keywords used: {results_new[0][3][:80]}...")

print("\n" + "="*70)

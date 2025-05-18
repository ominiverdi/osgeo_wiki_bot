# tests/3_query_db_unified.py
import json
import os
import sys
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database connection parameters
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "osgeo_wiki"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres")
}

def get_db_connection():
    """Connect to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def extract_keywords(keyword_tiers):
    """Extract essential keywords from tiers."""
    # Get all keywords from first tier
    all_keywords = []
    important_keywords = []
    
    if keyword_tiers and len(keyword_tiers) > 0:
        # Process first tier for important keywords
        for keyword in keyword_tiers[0]:
            # Remove quotes
            cleaned = keyword.replace('"', '')
            # Split into words
            words = cleaned.split()
            # Keep substantive words
            for word in words:
                if len(word) > 3 and word.lower() not in ["what", "when", "where", "who", "how", "does", "is", "the", "for", "are", "was"]:
                    important_keywords.append(word)
                    all_keywords.append(word)
        
        # Get additional keywords from other tiers if needed
        if len(important_keywords) < 2 and len(keyword_tiers) > 1:
            for tier in keyword_tiers[1:]:
                for keyword in tier:
                    cleaned = keyword.replace('"', '')
                    words = cleaned.split()
                    for word in words:
                        if len(word) > 3 and word.lower() not in ["what", "when", "where", "who", "how", "does", "is", "the", "for", "are", "was"]:
                            all_keywords.append(word)
                            if len(important_keywords) < 2:
                                important_keywords.append(word)
    
    # Remove duplicates while preserving order
    important_keywords = list(dict.fromkeys(important_keywords))
    all_keywords = list(dict.fromkeys(all_keywords))
    
    return {
        "important": important_keywords[:2],  # Limit to 2 most important keywords
        "all": all_keywords[:6]  # Limit to 6 keywords total
    }

def search_unified(conn, keywords, limit=10):
    """
    Execute a unified search strategy that combines:
    1. Title search with important keywords
    2. Content search with AND operator
    3. Content search with OR operator as fallback
    """
    try:
        # Extract keywords
        keyword_dict = extract_keywords(keywords)
        important_keywords = keyword_dict["important"]
        all_keywords = keyword_dict["all"]
        
        # Fallback if no keywords found
        if not important_keywords and keywords and len(keywords) > 0 and len(keywords[0]) > 0:
            first_keyword = keywords[0][0].replace('"', '').split()[0]
            important_keywords = [first_keyword]
            all_keywords = [first_keyword]
        
        # Print the keywords being used
        print(f"  Using important keywords: {important_keywords}")
        print(f"  Using all keywords: {all_keywords}")
        
        # Create title search pattern
        title_patterns = []
        for keyword in important_keywords:
            title_patterns.append(f"%{keyword}%")
        
        # Create AND search pattern
        and_terms = []
        for keyword in important_keywords:
            if keyword and len(keyword) > 1:
                and_terms.append(keyword.lower())
        and_query = " & ".join(and_terms) if and_terms else "osgeo"
        
        # Create OR search pattern
        or_terms = []
        for keyword in all_keywords:
            if keyword and len(keyword) > 1:
                or_terms.append(keyword.lower())
        or_query = " | ".join(or_terms) if or_terms else "osgeo"
        
        # Build title condition
        title_conditions = []
        title_params = []
        for pattern in title_patterns:
            title_conditions.append("p.title ILIKE %s")
            title_params.append(pattern)
        
        title_where = " OR ".join(title_conditions) if title_conditions else "TRUE"
        
        # Unified SQL query
        sql = f"""
        SELECT id, title, url, snippet, rank FROM (
            -- Strategy 1: Title search (highest priority)
            SELECT 
                p.id, p.title, p.url, NULL as snippet, 5.0 AS rank
            FROM 
                pages p
            WHERE 
                {title_where}
            
            UNION
            
            -- Strategy 2: Content search with AND (medium priority)
            SELECT 
                p.id, p.title, p.url, 
                LEFT(pc.chunk_text, 150) as snippet, 
                ts_rank(pc.tsv, to_tsquery('english', %s)) * 2.0 AS rank
            FROM 
                pages p
            JOIN 
                page_chunks pc ON p.id = pc.page_id
            WHERE 
                pc.tsv @@ to_tsquery('english', %s)
            
            UNION
            
            -- Strategy 3: Content search with OR (lower priority)
            SELECT 
                p.id, p.title, p.url, 
                LEFT(pc.chunk_text, 150) as snippet, 
                ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) AS rank
            FROM 
                pages p
            JOIN 
                page_chunks pc ON p.id = pc.page_id
            WHERE 
                pc.tsv @@ websearch_to_tsquery('english', %s)
        ) combined
        GROUP BY id, title, url, snippet, rank
        ORDER BY rank DESC, title
        LIMIT %s
        """
        
        # Combine parameters
        params = [
            *title_params,  # Strategy 1
            and_query, and_query,  # Strategy 2
            or_query, or_query,  # Strategy 3
            limit
        ]
        
        # Print the SQL (for debugging)
        print(f"  SQL WHERE conditions:")
        print(f"    Title: {title_where}")
        print(f"    AND query: {and_query}")
        print(f"    OR query: {or_query}")
        
        # Execute query
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]
            
            return results
            
    except Exception as e:
        print(f"Search error: {e}")
        return []

def main():
    # Path to processed query results
    input_file = "processed_query_results.json"
    
    # Path to the output file
    output_file = "unified_search_results.json"
    
    # Load the processed queries
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            processed_queries = json.load(f)
        print(f"Loaded {len(processed_queries)} processed queries from {input_file}")
    except Exception as e:
        print(f"Error loading input file: {e}")
        return
    
    # Connect to the database
    conn = get_db_connection()
    
    # Process each query
    search_results = []
    for item in processed_queries:
        query = item["query"]
        processed = item["processed_result"]
        
        print(f"\nSearching for: {query}")
        
        # Get query details
        query_type = processed.get("query_type", "definitional")
        tiers = processed.get("keyword_tiers", [])
        
        print(f"  Query type: {query_type}")
        if tiers:
            print(f"  First tier: {tiers[0]}")
        
        # Execute search with unified approach
        results = search_unified(conn, tiers)
        
        # Print summary
        print(f"  Found {len(results)} results")
        if results:
            print("  Top results:")
            for j, result in enumerate(results[:3]):  # Show top 3
                print(f"    - {result['title']} ({result['url']})")
        
        # Add to search results
        search_results.append({
            "query": query,
            "processed": processed,
            "unified_results": results
        })
    
    # Save the search results
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(search_results, f, indent=2)
        print(f"\nSaved search results to {output_file}")
    except Exception as e:
        print(f"Error saving output file: {e}")
        return
    
    # Close the database connection
    conn.close()
    
    # Print overall summary
    print("\nSearch Summary:")
    print(f"  Total queries processed: {len(search_results)}")
    
    # Count queries with zero results
    zero_results = sum(1 for item in search_results if not item["unified_results"])
    print(f"  Queries with zero results: {zero_results}")
    
    # Get the total number of results
    total_results = sum(len(item["unified_results"]) for item in search_results)
    print(f"  Total results found: {total_results}")
    print(f"  Average results per query: {total_results / len(search_results):.1f}")

if __name__ == "__main__":
    main()
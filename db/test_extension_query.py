#!/usr/bin/env python3
# db/test_extensions_query.py
import os
import sys
import argparse
import psycopg2
import psycopg2.extras
import re
import textwrap
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

def get_db_connection():
    """Connect to the PostgreSQL database."""
    try:
        # Get connection parameters from environment variables
        db_params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "database": os.getenv("DB_NAME", "osgeo_wiki"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", "postgres"),
            "port": os.getenv("DB_PORT", "5432")
        }
        
        # Connect to the database
        conn = psycopg2.connect(**db_params)
        conn.autocommit = True
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to PostgreSQL database: {e}")
        sys.exit(1)

def search_extensions(conn, query, limit=10, search_field='both'):
    """
    Search the page_extensions table for relevant content with weighted ranking.
    
    Args:
        conn: Database connection
        query: Search query string
        limit: Maximum number of results to return
        search_field: 'resume', 'keywords', or 'both'
    
    Returns:
        List of result dictionaries
    """
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            # Using the optimized search queries with title weighting
            if search_field == 'resume':
                sql = """
                SELECT 
                    pe.id, 
                    pe.page_title,
                    pe.wiki_url,
                    pe.resume,
                    pe.keywords,
                    (ts_rank(pe.resume_tsv, websearch_to_tsquery('english', %s)) + 
                     CASE WHEN pe.page_title_tsv @@ websearch_to_tsquery('english', %s) THEN 2.5 ELSE 0 END) AS rank,
                    ts_headline('english', pe.resume, websearch_to_tsquery('english', %s), 
                               'MaxFragments=2, MaxWords=30, MinWords=5, StartSel=<<, StopSel=>>') AS resume_headline,
                    ts_headline('english', pe.keywords, websearch_to_tsquery('english', %s),
                               'MaxFragments=2, MaxWords=15, MinWords=1, StartSel=<<, StopSel=>>') AS keywords_headline
                FROM 
                    page_extensions pe
                WHERE 
                    pe.resume_tsv @@ websearch_to_tsquery('english', %s)
                ORDER BY 
                    rank DESC
                LIMIT %s
                """
                params = [query, query, query, query, query, limit]
                
            elif search_field == 'keywords':
                sql = """
                SELECT 
                    pe.id, 
                    pe.page_title,
                    pe.wiki_url,
                    pe.resume,
                    pe.keywords,
                    (ts_rank(pe.keywords_tsv, websearch_to_tsquery('english', %s)) + 
                     CASE WHEN pe.page_title_tsv @@ websearch_to_tsquery('english', %s) THEN 2.5 ELSE 0 END) AS rank,
                    ts_headline('english', pe.resume, websearch_to_tsquery('english', %s), 
                               'MaxFragments=2, MaxWords=30, MinWords=5, StartSel=<<, StopSel=>>') AS resume_headline,
                    ts_headline('english', pe.keywords, websearch_to_tsquery('english', %s),
                               'MaxFragments=2, MaxWords=15, MinWords=1, StartSel=<<, StopSel=>>') AS keywords_headline
                FROM 
                    page_extensions pe
                WHERE 
                    pe.keywords_tsv @@ websearch_to_tsquery('english', %s)
                ORDER BY 
                    rank DESC
                LIMIT %s
                """
                params = [query, query, query, query, query, limit]
                
            else:  # 'both'
                sql = """
                SELECT 
                    pe.id, 
                    pe.page_title,
                    pe.wiki_url,
                    pe.resume,
                    pe.keywords,
                    ((0.6 * ts_rank(pe.resume_tsv, websearch_to_tsquery('english', %s))) + 
                     (0.4 * ts_rank(pe.keywords_tsv, websearch_to_tsquery('english', %s))) + 
                     CASE WHEN pe.page_title_tsv @@ websearch_to_tsquery('english', %s) THEN 2.5 ELSE 0 END) AS rank,
                    ts_headline('english', pe.resume, websearch_to_tsquery('english', %s), 
                               'MaxFragments=2, MaxWords=30, MinWords=5, StartSel=<<, StopSel=>>') AS resume_headline,
                    ts_headline('english', pe.keywords, websearch_to_tsquery('english', %s),
                               'MaxFragments=2, MaxWords=15, MinWords=1, StartSel=<<, StopSel=>>') AS keywords_headline
                FROM 
                    page_extensions pe
                WHERE 
                    (pe.resume_tsv @@ websearch_to_tsquery('english', %s) OR 
                     pe.keywords_tsv @@ websearch_to_tsquery('english', %s) OR 
                     pe.page_title_tsv @@ websearch_to_tsquery('english', %s))
                ORDER BY 
                    rank DESC
                LIMIT %s
                """
                params = [query, query, query, query, query, query, query, query, limit]
                
            # Execute the query with appropriate parameters
            cursor.execute(sql, params)
            
            # Fetch and return results
            return [dict(row) for row in cursor.fetchall()]
    
    except Exception as e:
        print(f"Error executing search: {e}")
        return []

def format_results(results, verbose=False):
    """Format search results for display."""
    if not results:
        print("No matching results found.")
        return
    
    # Define ANSI color codes
    BOLD = '\033[1m'
    GREEN = '\033[92m'
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    NORMAL = '\033[0m'
    
    print(f"\nFound {len(results)} matching results:\n")
    
    for i, result in enumerate(results, 1):
        # Print separator before each result (except the first one)
        if i > 1:
            print("\n" + "─" * 80 + "\n")
        
        # Title section
        print(f"{BOLD}{i}. {result['page_title']}{NORMAL} (Score: {result['rank']:.4f})")
        print(f"   URL: {result['wiki_url']}")
        
        # Content section with clear header
        print(f"\n   {CYAN}CONTENT:{NORMAL}")
        resume_highlight = result['resume_headline'].replace('<<', BOLD).replace('>>', NORMAL)
        print(f"   {resume_highlight}")
        
        # Keywords section with highlighted matches
        print(f"\n   {YELLOW}KEYWORDS:{NORMAL}")
        keyword_text = result['keywords']
        # If keywords_headline exists, use it to find and highlight matching terms
        if 'keywords_headline' in result and result['keywords_headline']:
            # Extract the highlighted terms
            matches = re.findall(r'<<(.*?)>>', result['keywords_headline'])
            # Highlight those terms in the full keywords list
            for match in matches:
                pattern = re.compile(re.escape(match), re.IGNORECASE)
                keyword_text = pattern.sub(f"{BOLD}{GREEN}\\g<0>{NORMAL}", keyword_text)
        
        # Print the keywords, wrap long lines
        keyword_lines = textwrap.wrap(keyword_text, width=80, initial_indent="   ", subsequent_indent="   ")
        for line in keyword_lines:
            print(line)
        
        # In verbose mode, show more details
        if verbose:
            print(f"\n   {CYAN}RESUME (full):{NORMAL}")
            # Show all bullet points from resume
            resume_lines = result['resume'].split('\n')
            for line in resume_lines:
                if line.strip():
                    print(f"   {line}")
    
    # Print final separator
    print("\n" + "─" * 80)

def count_extension_records(conn):
    """Count the number of records in the page_extensions table."""
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM page_extensions")
            return cursor.fetchone()[0]
    except Exception as e:
        print(f"Error counting records: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(description="Test search using page_extensions table")
    parser.add_argument("query", nargs="*", help="Search query")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Maximum number of results (default: 5)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show more detailed results")
    parser.add_argument("--field", "-f", choices=["resume", "keywords", "both"], default="both", 
                       help="Which field to search (default: both)")
    
    args = parser.parse_args()
    
    # Connect to the database
    conn = get_db_connection()
    
    try:
        # Count records
        record_count = count_extension_records(conn)
        print(f"Found {record_count} records in page_extensions table")
        
        # If a query was provided, search for it
        if args.query:
            query = " ".join(args.query)
            print(f"Searching for: '{query}' in {args.field} field(s)")
            
            results = search_extensions(conn, query, args.limit, args.field)
            format_results(results, args.verbose)
        else:
            # Interactive mode
            print("\nEnter search queries (type 'exit' to quit):")
            while True:
                query = input("\nSearch query: ")
                if query.lower() in ('exit', 'quit', 'q'):
                    break
                
                results = search_extensions(conn, query, args.limit, args.field)
                format_results(results, args.verbose)
    
    finally:
        conn.close()

if __name__ == "__main__":
    main()
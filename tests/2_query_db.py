#!/usr/bin/env python3
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import os
import sys
import requests
from datetime import datetime


CURRENT_DATE = datetime.now().strftime("%A, %B %d, %Y")  # e.g., "Sunday, May 18, 2025"

# Load environment variables
load_dotenv()

# PostgreSQL connection parameters
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "osgeo_wiki"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres")
}

# LLM API settings
LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:11434/api/generate")
LLM_MODEL = os.getenv("LLM_MODEL", "gemma3:latest")

def get_db_connection():
    """Connect to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def execute_search_query(conn, query_alternatives, limit=10, rank_threshold=0.1):
    """Execute search query with the given alternatives."""
    alternatives_list = []
    
    # Format alternatives for SQL
    for alt in query_alternatives:
        # Replace single quotes with double single quotes for SQL safety
        safe_alt = alt.replace("'", "''")
        alternatives_list.append(f"'{safe_alt}'")
    
    alternatives_sql = ", ".join(alternatives_list)
    
    sql = f"""
    WITH query_alternatives AS (
        SELECT unnest(ARRAY[{alternatives_sql}]) AS query_text
    ),
    ranked_chunks AS (
        SELECT 
            p.id AS page_id,
            p.title,
            p.url,
            pc.chunk_text,
            ts_rank(pc.tsv, websearch_to_tsquery('english', alt.query_text)) AS chunk_rank,
            alt.query_text
        FROM 
            page_chunks pc
        JOIN 
            pages p ON pc.page_id = p.id
        CROSS JOIN query_alternatives alt
        WHERE 
            pc.tsv @@ websearch_to_tsquery('english', alt.query_text)
    )
    SELECT 
        r.title,
        r.url,
        ts_headline('english', r.chunk_text, 
            websearch_to_tsquery('english', r.query_text),
            'MaxFragments=1, MaxWords=20, MinWords=3, StartSel=<<, StopSel=>>, HighlightAll=true'
        ) AS highlighted_text,
        r.chunk_rank AS rank
    FROM (
        SELECT DISTINCT ON (title, url) 
            title, url, chunk_text, query_text, chunk_rank
        FROM ranked_chunks
        ORDER BY title, url, chunk_rank DESC
    ) r
    ORDER BY 
        rank DESC
    LIMIT {limit};
    """
    
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(sql)
            results = [dict(row) for row in cursor.fetchall()]
            return results
    except Exception as e:
        print(f"Error executing search query: {e}")
        return []

def generate_llm_response(query, search_results):
    """Generate a response from the LLM based on search results."""
    # Format search results for the LLM prompt
    results_text = ""
    for i, result in enumerate(search_results, 1):
        results_text += f"Result {i}:\n"
        results_text += f"Title: {result['title']}\n"
        results_text += f"URL: {result['url']}\n"
        results_text += f"Relevance: {result['rank']:.2f}\n"
        results_text += f"Content: {result['highlighted_text']}\n\n"

    prompt = f"""
You are an expert assistant for the OSGeo wiki. Answer the following question based on the search results provided.

TODAY'S DATE: {CURRENT_DATE}

Question: {query}

Search Results:
{results_text}

Guidelines for your answer:
1. Synthesize information from multiple sources where appropriate.
2. Give precedence to information from higher-ranked results (higher relevance score).
3. When information appears contradictory, note the discrepancy and indicate which source seems more authoritative.
4. When dates, names, or specific facts are mentioned, include them precisely as they appear in the results.
5. If the search results don't contain enough information to answer confidently, acknowledge the limitations.
6. Format your answer in a concise, readable manner.
7. Include relevant URLs from the search results as references.
8. For list-type questions, organize information clearly if multiple items are found.

Your response should be factual, helpful, and directly address the question without adding speculation beyond what's in the search results.
"""

    try:
        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "stream": False
        }
        response = requests.post(LLM_API_URL, json=payload)
        if response.status_code == 200:
            return response.json()["response"]
        else:
            return f"Error generating LLM response: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error calling LLM API: {e}"

def main():
    # Path to query understanding results
    input_file = "query_understanding_results.json"
    
    # Path to the output file
    output_file = "search_and_answer_results.json"
    
    # Load the query understanding results
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            query_results = json.load(f)
        print(f"Loaded {len(query_results)} queries from {input_file}")
    except Exception as e:
        print(f"Error loading input file: {e}")
        return
    
    # Connect to the database
    conn = get_db_connection()
    
    # Results container
    search_and_answer_results = []
    
    # Process each query
    for item in query_results:
        query = item["query"]
        alternatives = item["result"].get("query_alternatives", [])
        
        if not alternatives:
            print(f"No query alternatives found for: {query}")
            continue
        
        print(f"\nProcessing query: {query}")
        print(f"Using alternatives: {alternatives}")
        
        # Execute search with alternatives
        search_results = execute_search_query(conn, alternatives)
        
        # print(f"Found {len(search_results)} search results")
        # if search_results:
        #     print("Top result:")
        #     print(f"  Title: {search_results[0]['title']}")
        #     print(f"  URL: {search_results[0]['url']}")
        #     print(f"  Highlight: {search_results[0]['highlighted_text']}")
        
        # Generate LLM response
        llm_answer = generate_llm_response(query, search_results)

        # Simple logging of just question and answer
        print("\n" + "="*80)
        print(f"QUESTION: {query}")
        print("-"*80)
        print(f"ANSWER: {llm_answer}")
        print("="*80)
        
        # Store the results
        search_and_answer_results.append({
            "query": query,
            "alternatives": alternatives,
            "search_results": search_results,
            "llm_answer": llm_answer
        })
    
    # Save the results
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(search_and_answer_results, f, indent=2)
        print(f"\nSaved search and answer results to {output_file}")
    except Exception as e:
        print(f"Error saving output file: {e}")
        return
    
    # Close the database connection
    conn.close()
    
    print("\nProcessing complete!")

if __name__ == "__main__":
    main()
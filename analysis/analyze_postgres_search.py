# analysis/analyze_postgres_search.py
import os
import sys
import psycopg2
import psycopg2.extras
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
import time
import json
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Sample queries to test (same as before for comparison)
SAMPLE_QUERIES = [
    # General OSGeo questions
    "What is OSGeo?",
    "How can I join OSGeo?",
    "Who founded OSGeo?",
    "What is the OSGeo foundation?",

    # Project-related questions
    "What is QGIS?",
    "How to contribute to GDAL?",
    "Tell me about MapServer",
    "What is GeoServer?",

    # Event-related questions
    "When was FOSS4G 2010?",
    "Where was FOSS4G 2019 held?",
    "What is a code sprint?",
    "Tell me about past OSGeo events",

    # Governance questions
    "Who is on the OSGeo board?",
    "How are OSGeo elections conducted?",
    "What committees exist in OSGeo?",
    "How is OSGeo funded?",

    # Technical questions
    "What is a GIS?",
    "What is open source geospatial?",
    "How do I get started with GIS?",
    "What OSGeo projects support WMS?"
]

# Different PostgreSQL search approaches to test
SEARCH_APPROACHES = {
    "basic_tsquery": {
        "description": "Basic text search using to_tsquery",
        "query": """
            SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, to_tsquery('english', %s)) AS rank
            FROM pages p
            JOIN page_chunks pc ON p.id = pc.page_id
            WHERE pc.tsv @@ to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 5
        """
    },
    "plainto_tsquery": {
        "description": "Natural language query parsing",
        "query": """
            SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, plainto_tsquery('english', %s)) AS rank
            FROM pages p
            JOIN page_chunks pc ON p.id = pc.page_id
            WHERE pc.tsv @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 5
        """
    },
    "websearch_to_tsquery": {
        "description": "Web search style query parsing",
        "query": """
            SELECT p.title, p.url, pc.chunk_text, ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) AS rank
            FROM pages p
            JOIN page_chunks pc ON p.id = pc.page_id
            WHERE pc.tsv @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 5
        """
    },
    "category_boosted": {
        "description": "Search with category relevance boosting",
        "query": """
            SELECT p.title, p.url, pc.chunk_text, 
                   ts_rank(pc.tsv, websearch_to_tsquery('english', %s)) + 
                   CASE WHEN EXISTS (
                       SELECT 1 FROM page_categories pc2 
                       WHERE pc2.page_id = p.id 
                       AND pc2.category_name ILIKE '%%' || %s || '%%'
                   ) THEN 0.5 ELSE 0 END AS rank
            FROM pages p
            JOIN page_chunks pc ON p.id = pc.page_id
            LEFT JOIN page_categories pc2 ON p.id = pc2.page_id
            WHERE pc.tsv @@ websearch_to_tsquery('english', %s)
            AND pc2.category_name NOT IN ('Categories', 'Category')
            ORDER BY rank DESC
            LIMIT 5
        """
    },
    "fuzzy_trigram": {
        "description": "Fuzzy search using trigram similarity",
        "query": """
            SELECT p.title, p.url, pc.chunk_text, 
                similarity(pc.chunk_text, %s) AS rank
            FROM pages p
            JOIN page_chunks pc ON p.id = pc.page_id
            WHERE similarity(pc.chunk_text, %s) > 0.3
            ORDER BY rank DESC
            LIMIT 5
        """
    }
}


def get_db_connection():
    """Connect to the PostgreSQL database."""
    try:
        # Get connection parameters from environment variables or use defaults
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


def prepare_query_for_tsquery(query):
    """Prepare a natural language query for tsquery format."""
    # Convert to lowercase and remove punctuation
    query = query.lower().replace('?', '').replace('.', '').replace(',', '')

    # Remove common stopwords that tsquery would ignore anyway
    stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were',
                 'be', 'to', 'in', 'on', 'at', 'by', 'of', 'for', 'with'}
    words = [word for word in query.split() if word not in stopwords]

    # Connect with & for AND operations
    return ' & '.join(words)


def count_query_terms_in_result(query, result):
    """Count how many query terms are present in a result."""
    query_terms = set(query.lower().replace('?', '').replace('.', '').split())
    result_text = result["chunk_text"].lower()

    count = sum(1 for term in query_terms if term in result_text)
    return count / len(query_terms) if query_terms else 0


def run_search_query(conn, approach, query):
    """Run a search query using the specified approach."""
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Handle different parameter requirements for different query types
            if approach == "basic_tsquery":
                tsquery = prepare_query_for_tsquery(query)
                cur.execute(SEARCH_APPROACHES[approach]
                            ["query"], (tsquery, tsquery))
            elif approach == "category_boosted":
                # Need to extract a key term for category matching
                key_terms = [w for w in query.lower().split() if len(w) > 3]
                key_term = key_terms[0] if key_terms else query.split()[0]
                cur.execute(SEARCH_APPROACHES[approach]
                            ["query"], (query, key_term, query))
            elif approach == "fuzzy_trigram":
                # Fuzzy trigram needs the query parameter twice
                cur.execute(
                    SEARCH_APPROACHES[approach]["query"], (query, query))
            else:
                # Standard parameter passing for other query types
                cur.execute(
                    SEARCH_APPROACHES[approach]["query"], (query, query))

            results = cur.fetchall()

            # Convert to list of dictionaries
            results_list = []
            for row in results:
                result = dict(row)
                result["term_coverage"] = count_query_terms_in_result(
                    query, result)
                results_list.append(result)

            return results_list
    except psycopg2.Error as e:
        print(f"Error executing search query '{approach}' for '{query}': {e}")
        return []


def evaluate_search_results(results, query):
    """Evaluate search results based on metrics."""
    if not results:
        return {
            "found_results": False,
            "result_count": 0,
            "avg_term_coverage": 0,
            "avg_rank": 0,
            "execution_time_ms": 0
        }

    # Calculate metrics
    avg_term_coverage = sum(r["term_coverage"] for r in results) / len(results)
    avg_rank = sum(float(r["rank"]) for r in results) / len(results)

    return {
        "found_results": True,
        "result_count": len(results),
        "avg_term_coverage": avg_term_coverage,
        "avg_rank": avg_rank
    }


def run_search_benchmark():
    """Run a benchmark comparing different search approaches."""
    conn = get_db_connection()
    results = {}

    # Enable pg_trgm extension if needed for fuzzy search
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    except psycopg2.Error as e:
        print(f"Warning: Could not enable pg_trgm extension: {e}")
        # Remove trigram search if extension not available
        if "fuzzy_trigram" in SEARCH_APPROACHES:
            del SEARCH_APPROACHES["fuzzy_trigram"]

    for query in SAMPLE_QUERIES:
        print(f"\nTesting query: '{query}'")
        query_results = {}

        for approach_name, approach_info in SEARCH_APPROACHES.items():
            print(f"  Running {approach_name} search...")

            start_time = time.time()
            search_results = run_search_query(conn, approach_name, query)
            execution_time = (time.time() - start_time) * 1000  # Convert to ms

            evaluation = evaluate_search_results(search_results, query)
            evaluation["execution_time_ms"] = execution_time

            query_results[approach_name] = {
                "results": search_results,
                "evaluation": evaluation
            }

            print(
                f"    Found {len(search_results)} results in {execution_time:.1f}ms")
            print(f"    Term coverage: {evaluation['avg_term_coverage']:.2f}")

        results[query] = query_results

    conn.close()
    return results


def generate_report(results):
    """Generate a report comparing the performance of search approaches."""
    # Initialize metrics
    approach_metrics = {approach: {
        "avg_term_coverage": [],
        "avg_result_count": [],
        "avg_exec_time": [],
        "success_rate": []
    } for approach in SEARCH_APPROACHES.keys()}

    # Collect metrics for each approach
    for query, query_results in results.items():
        for approach, data in query_results.items():
            eval_data = data["evaluation"]
            approach_metrics[approach]["avg_term_coverage"].append(
                eval_data["avg_term_coverage"])
            approach_metrics[approach]["avg_result_count"].append(
                eval_data["result_count"])
            approach_metrics[approach]["avg_exec_time"].append(
                eval_data["execution_time_ms"])
            approach_metrics[approach]["success_rate"].append(
                1 if eval_data["found_results"] else 0)

    # Calculate averages
    summary = {}
    for approach, metrics in approach_metrics.items():
        summary[approach] = {
            "avg_term_coverage": sum(metrics["avg_term_coverage"]) / len(SAMPLE_QUERIES),
            "avg_result_count": sum(metrics["avg_result_count"]) / len(SAMPLE_QUERIES),
            "avg_exec_time": sum(metrics["avg_exec_time"]) / len(SAMPLE_QUERIES),
            "success_rate": sum(metrics["success_rate"]) / len(SAMPLE_QUERIES) * 100
        }

    # Create a DataFrame for easier visualization
    df = pd.DataFrame(summary).T

    # Plot the results
    fig, axs = plt.subplots(2, 2, figsize=(15, 10))

    # Term coverage
    axs[0, 0].bar(df.index, df["avg_term_coverage"], color='blue', alpha=0.7)
    axs[0, 0].set_title('Average Term Coverage')
    axs[0, 0].set_ylim(0, 1)
    axs[0, 0].set_xticklabels(df.index, rotation=45, ha='right')

    # Result count
    axs[0, 1].bar(df.index, df["avg_result_count"], color='green', alpha=0.7)
    axs[0, 1].set_title('Average Result Count')
    axs[0, 1].set_xticklabels(df.index, rotation=45, ha='right')

    # Execution time
    axs[1, 0].bar(df.index, df["avg_exec_time"], color='red', alpha=0.7)
    axs[1, 0].set_title('Average Execution Time (ms)')
    axs[1, 0].set_xticklabels(df.index, rotation=45, ha='right')

    # Success rate
    axs[1, 1].bar(df.index, df["success_rate"], color='purple', alpha=0.7)
    axs[1, 1].set_title('Success Rate (%)')
    axs[1, 1].set_ylim(0, 100)
    axs[1, 1].set_xticklabels(df.index, rotation=45, ha='right')

    plt.tight_layout()
    plot_path = Path('postgres_search_comparison.png')
    plt.savefig(plot_path)
    print(f"\nPlot saved to {plot_path.absolute()}")
    plt.close()

    # Print summary
    print("\nSearch Approach Performance Summary:")
    for approach, metrics in sorted(summary.items(), key=lambda x: x[1]["avg_term_coverage"], reverse=True):
        print(f"  {approach}:")
        print(f"    Term Coverage: {metrics['avg_term_coverage']:.2f}")
        print(f"    Result Count: {metrics['avg_result_count']:.1f}")
        print(f"    Execution Time: {metrics['avg_exec_time']:.1f}ms")
        print(f"    Success Rate: {metrics['success_rate']:.1f}%")

    # Save detailed results as JSON for later analysis
    with open("postgres_search_results.json", "w") as f:
        # Convert any non-serializable objects to strings
        serializable_results = json.dumps(results, default=str, indent=2)
        f.write(serializable_results)

    # Sample result display for the best approach
    best_approach = max(
        summary.items(), key=lambda x: x[1]["avg_term_coverage"])[0]
    print(f"\nSample Results from Best Approach ({best_approach}):")

    # Find a query that had good results
    for query in SAMPLE_QUERIES:
        sample_results = results[query][best_approach]["results"]
        if sample_results:
            print(f"Query: '{query}'")
            # Show top 2 results
            for i, result in enumerate(sample_results[:2]):
                print(f"  Result {i+1}:")
                print(f"    Title: {result['title']}")
                print(f"    URL: {result['url']}")
                print(f"    Chunk excerpt: {result['chunk_text'][:150]}...")
                print(f"    Term Coverage: {result['term_coverage']:.2f}")
                print(f"    Rank Score: {float(result['rank']):.4f}")
            break


def main():
    """Run the PostgreSQL search analysis."""
    print("=== PostgreSQL Search Analysis ===")
    print("Testing actual database search performance...")

    benchmark_results = run_search_benchmark()
    generate_report(benchmark_results)

    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()

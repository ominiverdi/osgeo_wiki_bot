# analysis/analyze_query_quality.py
import os
import sys
import random
import json
from pathlib import Path
import matplotlib.pyplot as plt
from collections import Counter, defaultdict
import re

# Add the current directory to the path so we can import common_utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import common_utils

# Define category blacklist
CATEGORY_BLACKLIST = ['Categories', 'Category']

# Define sample queries that might be asked of the OSGeo wiki bot
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

def preprocess_query(query):
    """Transform a natural language query into search terms."""
    query = query.lower()
    
    # Remove common words that won't help with search
    stopwords = {"is", "the", "a", "an", "in", "on", "at", "and", "or", "to", "with", "about", "tell", "me"}
    terms = [word for word in query.split() if word not in stopwords]
    
    return terms

def chunk_content(content, chunk_size=500):
    """Split content into chunks of approximately chunk_size characters."""
    chunks = []
    current_chunk = ""
    
    # Split by paragraphs
    paragraphs = re.split(r'\n\n+', content)
    
    for para in paragraphs:
        if not para.strip():
            continue
        
        if len(current_chunk) + len(para) <= chunk_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def simulate_text_search(query_terms, wiki_data, chunk_size=500):
    """Simulate a basic text search on the wiki data."""
    title = wiki_data.get('title', '')
    content = wiki_data.get('content', '')
    url = wiki_data.get('url', '')
    categories = wiki_data.get('categories', [])
    
    # Skip if no content or has blacklisted categories
    if not content or any(cat in CATEGORY_BLACKLIST for cat in categories):
        return []
    
    # Split content into chunks
    chunks = chunk_content(content, chunk_size)
    
    # Check each chunk for query terms
    results = []
    for i, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()
        
        # Count occurrences of each term
        term_counts = {term: chunk_lower.count(term) for term in query_terms}
        
        # Calculate a simple relevance score
        relevance = sum(term_counts.values())
        
        # Only include chunks with at least one term match
        if relevance > 0:
            results.append({
                'title': title,
                'url': url,
                'chunk_text': chunk,
                'rank': relevance,
                'chunk_index': i
            })
    
    # Sort by relevance
    results.sort(key=lambda x: x['rank'], reverse=True)
    
    return results[:5]  # Return top 5 results

def simulate_phrase_search(query, wiki_data, chunk_size=500):
    """Simulate a phrase search on the wiki data."""
    title = wiki_data.get('title', '')
    content = wiki_data.get('content', '')
    url = wiki_data.get('url', '')
    categories = wiki_data.get('categories', [])
    
    # Skip if no content or has blacklisted categories
    if not content or any(cat in CATEGORY_BLACKLIST for cat in categories):
        return []
    
    # Split content into chunks
    chunks = chunk_content(content, chunk_size)
    
    # Check each chunk for the query phrase
    results = []
    for i, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()
        query_lower = query.lower()
        
        # Count phrase occurrences
        phrase_count = chunk_lower.count(query_lower)
        
        # Calculate relevance
        relevance = phrase_count * 10  # Weight phrase matches higher
        
        # Only include chunks with a phrase match
        if relevance > 0:
            results.append({
                'title': title,
                'url': url,
                'chunk_text': chunk,
                'rank': relevance,
                'chunk_index': i
            })
    
    # Sort by relevance
    results.sort(key=lambda x: x['rank'], reverse=True)
    
    return results[:5]  # Return top 5 results

def simulate_category_boosted_search(query_terms, wiki_data, chunk_size=500):
    """Simulate a text search with category boosting."""
    title = wiki_data.get('title', '')
    content = wiki_data.get('content', '')
    url = wiki_data.get('url', '')
    categories = wiki_data.get('categories', [])
    
    # Skip if no content or has blacklisted categories
    if not content or any(cat in CATEGORY_BLACKLIST for cat in categories):
        return []
    
    # Split content into chunks
    chunks = chunk_content(content, chunk_size)
    
    # Check each chunk for query terms
    results = []
    for i, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()
        
        # Count occurrences of each term
        term_counts = {term: chunk_lower.count(term) for term in query_terms}
        
        # Calculate base relevance
        relevance = sum(term_counts.values())
        
        # Boost relevance if categories seem relevant
        category_boost = 1.0
        for cat in categories:
            cat_lower = cat.lower()
            for term in query_terms:
                if term in cat_lower:
                    category_boost = 1.5
                    break
        
        final_relevance = relevance * category_boost
        
        # Only include chunks with at least one term match
        if relevance > 0:
            results.append({
                'title': title,
                'url': url,
                'chunk_text': chunk,
                'rank': final_relevance,
                'chunk_index': i
            })
    
    # Sort by relevance
    results.sort(key=lambda x: x['rank'], reverse=True)
    
    return results[:5]  # Return top 5 results

def evaluate_result(results, query_terms):
    """Evaluate search result relevance based on simple metrics."""
    if not results:
        return {
            "found_results": False,
            "term_coverage": 0,
            "result_count": 0,
            "avg_term_frequency": 0
        }
    
    # Basic metrics
    term_frequencies = []
    for term in query_terms:
        term_freq = sum(result["chunk_text"].lower().count(term.lower()) for result in results)
        term_frequencies.append(term_freq)
    
    avg_term_freq = sum(term_frequencies) / len(term_frequencies) if term_frequencies else 0
    term_coverage = sum(1 for freq in term_frequencies if freq > 0) / len(term_frequencies)
    
    return {
        "found_results": True,
        "term_coverage": term_coverage,
        "result_count": len(results),
        "avg_term_frequency": avg_term_freq
    }

def find_pages_with_term(query, min_pages=10):
    """Find pages that contain the query terms instead of random sampling."""
    query_terms = query.lower().split()
    files = common_utils.list_wiki_files()
    matching_files = []
    
    # Find pages that contain all query terms
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        content = wiki_data.get('content', '').lower()
        
        if all(term in content for term in query_terms):
            matching_files.append(file_path)
            if len(matching_files) >= min_pages:
                break
    
    # If we didn't find enough pages with all terms, try pages with any term
    if len(matching_files) < min_pages:
        for file_path in files:
            if file_path in matching_files:
                continue
                
            wiki_data = common_utils.parse_wiki_file(file_path)
            content = wiki_data.get('content', '').lower()
            
            if any(term in content for term in query_terms):
                matching_files.append(file_path)
                if len(matching_files) >= min_pages:
                    break
    
    return matching_files[:min_pages]

def simulate_search_approaches(query, wiki_files, chunk_size=500):
    """Simulate different search approaches for a query."""
    query_terms = preprocess_query(query)
    
    # Initialize results for each approach
    approach_results = {
        "basic_text_search": [],
        "phrase_search": [],
        "category_boosted_search": []
    }
    
    # Process all wiki files
    for file_path in wiki_files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        
        # Run each search approach
        text_results = simulate_text_search(query_terms, wiki_data, chunk_size)
        phrase_results = simulate_phrase_search(query, wiki_data, chunk_size)
        category_results = simulate_category_boosted_search(query_terms, wiki_data, chunk_size)
        
        # Append results
        approach_results["basic_text_search"].extend(text_results)
        approach_results["phrase_search"].extend(phrase_results)
        approach_results["category_boosted_search"].extend(category_results)
    
    # Sort and deduplicate results for each approach
    for approach in approach_results:
        # Sort by rank
        approach_results[approach].sort(key=lambda x: x['rank'], reverse=True)
        
        # Deduplicate by URL + chunk_index
        seen = set()
        unique_results = []
        for result in approach_results[approach]:
            key = (result['url'], result['chunk_index'])
            if key not in seen:
                seen.add(key)
                unique_results.append(result)
        
        # Keep top 5
        approach_results[approach] = unique_results[:5]
    
    return approach_results

def run_search_simulation():
    """Run search simulations for different approaches."""
    results = {}
    
    for query in SAMPLE_QUERIES:
        print(f"\nTesting query: '{query}'")
        query_terms = preprocess_query(query)
        print(f"Processed as search terms: {query_terms}")
        
        # Find relevant wiki files to search
        wiki_files = find_pages_with_term(query, min_pages=10)
        print(f"Found {len(wiki_files)} relevant pages to search")
        
        # Simulate different search approaches
        approach_results = simulate_search_approaches(query, wiki_files)
        
        # Evaluate results for each approach
        query_results = {}
        for approach, results_list in approach_results.items():
            evaluation = evaluate_result(results_list, query_terms)
            
            query_results[approach] = {
                "raw_results": results_list,
                "evaluation": evaluation
            }
            
            print(f"  {approach}: "
                  f"Found {len(results_list)} results, "
                  f"Term coverage: {evaluation['term_coverage']:.2f}")
        
        results[query] = query_results
    
    return results

def generate_report(results):
    """Generate a report comparing the different approaches."""
    if not results:
        print("No results to analyze.")
        return
    
    # Approach performance across all queries
    approach_scores = defaultdict(list)
    
    for query, query_results in results.items():
        for approach, data in query_results.items():
            if "evaluation" in data:
                # Use term_coverage as our primary metric
                approach_scores[approach].append(data["evaluation"]["term_coverage"])
    
    # Calculate average scores
    avg_scores = {approach: sum(scores)/len(scores) if scores else 0 
                for approach, scores in approach_scores.items()}
    
    # Plot comparison
    plt.figure(figsize=(10, 6))
    approaches = list(avg_scores.keys())
    scores = list(avg_scores.values())
    
    plt.bar(approaches, scores, color='blue', alpha=0.7)
    plt.title('Search Approach Effectiveness')
    plt.xlabel('Approach')
    plt.ylabel('Average Term Coverage')
    plt.ylim(0, 1)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    plot_path = Path('search_approach_comparison.png')
    plt.savefig(plot_path)
    print(f"\nPlot saved to {plot_path.absolute()}")
    plt.close()
    
    # Print summary
    print("\nApproach Performance Summary:")
    for approach, score in sorted(avg_scores.items(), key=lambda x: x[1], reverse=True):
        print(f"  {approach}: {score:.2f} average term coverage")
    
    # Sample result analysis for the best approach
    best_approach = max(avg_scores.items(), key=lambda x: x[1])[0]
    print(f"\nSample Results from Best Approach ({best_approach}):")
    
    sample_query = random.choice(SAMPLE_QUERIES)
    sample_results = results[sample_query][best_approach]["raw_results"]
    
    print(f"Query: '{sample_query}'")
    for i, result in enumerate(sample_results[:2]):  # Show top 2 results
        print(f"  Result {i+1}:")
        print(f"    Title: {result['title']}")
        print(f"    URL: {result['url']}")
        print(f"    Chunk excerpt: {result['chunk_text'][:150]}...")

def main():
    """Run the query quality analysis."""
    print("=== Query Quality Analysis ===")
    
    # Check if we should use mock data for development
    use_mock = len(sys.argv) > 1 and sys.argv[1] == "--mock"
    
    if use_mock:
        print("Using mock data for analysis")
        # Load mock results from file if available
        try:
            with open("mock_search_results.json", "r") as f:
                results = json.load(f)
        except FileNotFoundError:
            print("Mock data file not found. Generating mock data.")
            # Generate mock results for faster testing
            results = generate_mock_results()
            with open("mock_search_results.json", "w") as f:
                json.dump(results, f, indent=2)
    else:
        print("Running live search simulation on wiki files")
        results = run_search_simulation()
    
    # Generate report
    generate_report(results)
    
    print("\nAnalysis complete!")

def generate_mock_results():
    """Generate mock results for testing without running searches."""
    return {
        query: {
            approach: {
                "raw_results": [
                    {"title": f"Mock Title {i}", 
                     "url": "https://wiki.osgeo.org/mock",
                     "chunk_text": f"This is a mock result for {query} using {approach}. "
                                  f"It contains search terms like {' '.join(query.lower().split())}."}
                    for i in range(random.randint(0, 5))
                ],
                "evaluation": {
                    "found_results": bool(random.randint(0, 1)),
                    "term_coverage": random.random(),
                    "result_count": random.randint(0, 5),
                    "avg_term_frequency": random.random() * 10
                }
            }
            for approach in ["basic_text_search", "phrase_search", "category_boosted_search"]
        }
        for query in SAMPLE_QUERIES
    }

if __name__ == "__main__":
    main()
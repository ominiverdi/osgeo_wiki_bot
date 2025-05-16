# analysis/simulate_search.py (improved version)
import os
import sys
from pathlib import Path
import random
import re
from collections import Counter
import colorama
from colorama import Fore, Back, Style

# Add the current directory to the path so we can import common_utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import common_utils

# Initialize colorama
colorama.init()

# Sample search terms relevant to OSGeo wiki
SAMPLE_QUERIES = [
    "board meeting",
    "code sprint",
    "gdal",
    "qgis",
    "conference",
    "open source",
    "gis software",
    "mapping",
    "foss4g"
]

def chunk_content(content, chunk_size):
    """Split content into chunks of approximately chunk_size characters, enforcing max size."""
    chunks = []
    paragraphs = re.split(r'\n\n+', content)
    
    current_chunk = ""
    for para in paragraphs:
        para_clean = para.strip()
        if not para_clean:
            continue
            
        # If this paragraph would make the chunk too big, start a new chunk
        if len(current_chunk) + len(para_clean) > chunk_size:
            # If the current paragraph is itself larger than chunk_size, split it
            if len(para_clean) > chunk_size:
                # First add the current chunk if it's not empty
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                
                # Split the paragraph into sentences
                sentences = re.split(r'(?<=[.!?])\s+', para_clean)
                current_sentence_chunk = ""
                
                for sentence in sentences:
                    if len(current_sentence_chunk) + len(sentence) <= chunk_size:
                        current_sentence_chunk += sentence + " "
                    else:
                        if current_sentence_chunk:
                            chunks.append(current_sentence_chunk.strip())
                        
                        # If the sentence itself is too long, split it by force
                        if len(sentence) > chunk_size:
                            # Split it into word groups that fit
                            words = sentence.split()
                            current_word_chunk = ""
                            
                            for word in words:
                                if len(current_word_chunk) + len(word) + 1 <= chunk_size:
                                    current_word_chunk += word + " "
                                else:
                                    if current_word_chunk:
                                        chunks.append(current_word_chunk.strip())
                                    current_word_chunk = word + " "
                            
                            if current_word_chunk:
                                current_sentence_chunk = current_word_chunk
                            else:
                                current_sentence_chunk = ""
                        else:
                            current_sentence_chunk = sentence + " "
                
                if current_sentence_chunk:
                    current_chunk = current_sentence_chunk
            else:
                # Just add the current chunk and start a new one with this paragraph
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para_clean + "\n\n"
        else:
            current_chunk += para_clean + "\n\n"
    
    # Add the last chunk if it's not empty
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def find_pages_with_term(query, min_pages=10):
    """Find pages that contain the query terms."""
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

def highlight_matches(text, query_terms):
    """Highlight query terms in the text."""
    result = text
    for term in query_terms:
        # Create a regex pattern to match the term case-insensitively
        pattern = re.compile(r'(\b' + re.escape(term) + r'\b)', re.IGNORECASE)
        # Replace matches with highlighted version
        result = pattern.sub(f'{Fore.RED}{Back.YELLOW}\\1{Style.RESET_ALL}', result)
    
    return result

def truncate_text(text, max_length=200):
    """Truncate text to max_length, preserving words."""
    if len(text) <= max_length:
        return text
    
    truncated = text[:max_length]
    # Try to break at a space to avoid cutting words
    last_space = truncated.rfind(' ')
    if last_space > 0:
        truncated = truncated[:last_space]
    
    return truncated + "..."

def get_context(text, term, context_chars=50):
    """Get some context around the first occurrence of a term."""
    term_pos = text.lower().find(term.lower())
    if term_pos == -1:
        return None
    
    start = max(0, term_pos - context_chars)
    end = min(len(text), term_pos + len(term) + context_chars)
    
    # Adjust start and end to not break words
    if start > 0:
        while start > 0 and text[start].isalnum():
            start -= 1
    
    if end < len(text):
        while end < len(text) and text[end].isalnum():
            end += 1
    
    context = text[start:end]
    if start > 0:
        context = "..." + context
    if end < len(text):
        context = context + "..."
    
    return context

def simulate_search(query, chunk_sizes=[500, 2000, 10000], num_pages=10, max_results=3):
    """Simulate searching for a query using different chunk sizes."""
    query_terms = query.lower().split()
    search_pages = find_pages_with_term(query, min_pages=num_pages)
    
    print(f"\n{Fore.GREEN}===== SEARCH QUERY: '{query}' ====={Style.RESET_ALL}")
    print(f"Found {len(search_pages)} pages containing search terms.")
    
    for chunk_size in chunk_sizes:
        print(f"\n{Fore.BLUE}--- CHUNK SIZE: {chunk_size} CHARACTERS ---{Style.RESET_ALL}")
        
        all_chunks = []
        chunk_sources = []
        chunk_original_sizes = []
        
        # Create chunks for all selected pages
        for file_path in search_pages:
            wiki_data = common_utils.parse_wiki_file(file_path)
            content = wiki_data.get('content', '')
            
            if not content:
                continue
            
            chunks = chunk_content(content, chunk_size)
            all_chunks.extend(chunks)
            chunk_sources.extend([wiki_data['title']] * len(chunks))
            
            # Track the original sizes
            for chunk in chunks:
                chunk_original_sizes.append(len(chunk))
        
        # Show chunk statistics
        if chunk_original_sizes:
            avg_size = sum(chunk_original_sizes) / len(chunk_original_sizes)
            print(f"Average actual chunk size: {avg_size:.1f} characters")
            print(f"Total chunks: {len(all_chunks)}")
        
        # Simple search: check if all query terms are in the chunk
        matching_chunks = []
        for i, chunk in enumerate(all_chunks):
            chunk_lower = chunk.lower()
            if all(term in chunk_lower for term in query_terms):
                matching_chunks.append((i, chunk, chunk_sources[i]))
        
        # Display results
        print(f"Found {len(matching_chunks)} matching chunks")
        
        if matching_chunks:
            # Display a sample of the matches
            for idx, (chunk_idx, chunk, source) in enumerate(matching_chunks[:max_results]):
                print(f"\n{Fore.CYAN}Result {idx+1} from '{source}':{Style.RESET_ALL}")
                
                # Find first context for each term
                contexts = []
                for term in query_terms:
                    context = get_context(chunk, term, context_chars=70)
                    if context:
                        contexts.append(highlight_matches(context, query_terms))
                
                if contexts:
                    for i, ctx in enumerate(contexts[:2]):  # Show at most 2 contexts
                        print(f"{Fore.YELLOW}Context {i+1}:{Style.RESET_ALL} {ctx}")
                else:
                    # Fallback to general preview
                    preview = truncate_text(highlight_matches(chunk, query_terms), 300)
                    print(preview)
                
                # Show chunk size
                print(f"{Fore.MAGENTA}[Chunk size: {len(chunk)} characters]{Style.RESET_ALL}")
                
            if len(matching_chunks) > max_results:
                print(f"\n{Fore.YELLOW}...and {len(matching_chunks) - max_results} more results.{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}No matching chunks found.{Style.RESET_ALL}")

def main():
    """Run the search simulation."""
    print("=== Search Simulation with Different Chunk Sizes ===")
    
    # Set random seed for reproducibility
    random.seed(42)
    
    # Either use a random query or let the user specify
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = random.choice(SAMPLE_QUERIES)
        print(f"Using random query: '{query}'")
        print("(Provide your own query as command line arguments to test specific terms)")
    
    # Run the simulation
    simulate_search(query, chunk_sizes=[500, 2000, 10000], num_pages=15)
    
    print("\nSimulation complete!")

if __name__ == "__main__":
    main()
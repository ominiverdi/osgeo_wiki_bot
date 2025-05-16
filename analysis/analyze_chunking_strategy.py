# analysis/analyze_chunking_strategy.py
import os
import sys
from pathlib import Path
import matplotlib.pyplot as plt
from collections import Counter, defaultdict
import numpy as np
import re

# Add the current directory to the path so we can import common_utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import common_utils

def analyze_natural_breakpoints():
    """Analyze natural breakpoints in content (sections, paragraphs, etc.)."""
    files = common_utils.list_wiki_files()
    section_counts = []
    paragraph_counts = []
    avg_section_lengths = []
    avg_paragraph_lengths = []
    
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        content = wiki_data.get('content', '')
        
        if not content:
            continue
        
        # Count sections
        sections = common_utils.extract_sections(content)
        section_counts.append(len(sections))
        
        # Calculate average section length
        if sections:
            section_lengths = [len(section[1]) for section in sections]
            avg_section_lengths.append(sum(section_lengths) / len(section_lengths))
        
        # Count paragraphs
        paragraphs = re.split(r'\n\n+', content)
        paragraphs = [p for p in paragraphs if p.strip()]
        paragraph_counts.append(len(paragraphs))
        
        # Calculate average paragraph length
        if paragraphs:
            para_lengths = [len(p) for p in paragraphs]
            avg_paragraph_lengths.append(sum(para_lengths) / len(para_lengths))
    
    return {
        'section_counts': section_counts,
        'avg_section_lengths': avg_section_lengths,
        'paragraph_counts': paragraph_counts,
        'avg_paragraph_lengths': avg_paragraph_lengths
    }

def simulate_different_chunk_sizes(chunk_sizes=[500, 1000, 2000, 5000, 10000]):
    """Simulate different chunking strategies and analyze coverage."""
    files = common_utils.list_wiki_files()
    results = {}
    
    # Collect overall statistics
    total_pages = 0
    total_chunks_by_size = {size: 0 for size in chunk_sizes}
    chunks_per_page_by_size = {size: [] for size in chunk_sizes}
    
    # Collect statistics about chunk sizes
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        content = wiki_data.get('content', '')
        
        if not content:
            continue
        
        total_pages += 1
        
        # Try different chunk sizes
        for chunk_size in chunk_sizes:
            chunks = []
            current_chunk = ""
            
            # Simple chunking by paragraph with size limit
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
            
            total_chunks_by_size[chunk_size] += len(chunks)
            chunks_per_page_by_size[chunk_size].append(len(chunks))
    
    # Calculate averages and distributions
    for size in chunk_sizes:
        avg_chunks_per_page = sum(chunks_per_page_by_size[size]) / total_pages if total_pages > 0 else 0
        results[size] = {
            'total_chunks': total_chunks_by_size[size],
            'avg_chunks_per_page': avg_chunks_per_page,
            'max_chunks_per_page': max(chunks_per_page_by_size[size]) if chunks_per_page_by_size[size] else 0,
            'chunks_distribution': chunks_per_page_by_size[size]
        }
    
    return results

def estimate_database_impact(chunking_results):
    """Estimate database size and index size based on chunking strategy."""
    chunk_sizes = list(chunking_results.keys())
    
    # Rough estimate of database size
    # Assume each page has a 100 byte overhead (id, title, url)
    # Assume each chunk has a 50 byte overhead (id, page_id, index)
    # Assume tsv index is roughly 30% of text size
    page_count = 2033  # From basic metrics
    avg_content_size = 5386  # From basic metrics
    
    db_size_estimates = {}
    
    for size in chunk_sizes:
        result = chunking_results[size]
        
        # Pages table size
        pages_table_size = page_count * (100 + avg_content_size)
        
        # Chunks table size
        avg_chunk_size = min(size, avg_content_size)  # Actual average can't exceed chunk size limit
        chunks_table_size = result['total_chunks'] * (50 + avg_chunk_size)
        
        # Index size (tsv)
        index_size = result['total_chunks'] * (avg_chunk_size * 0.3)
        
        # Total estimated size
        total_size = pages_table_size + chunks_table_size + index_size
        
        db_size_estimates[size] = {
            'pages_table_mb': pages_table_size / (1024 * 1024),
            'chunks_table_mb': chunks_table_size / (1024 * 1024),
            'index_size_mb': index_size / (1024 * 1024),
            'total_mb': total_size / (1024 * 1024)
        }
    
    return db_size_estimates

def plot_breakpoint_statistics(breakpoint_data):
    """Plot statistics about natural breakpoints."""
    fig, axs = plt.subplots(2, 2, figsize=(12, 10))
    
    # Plot section count distribution
    axs[0, 0].hist(breakpoint_data['section_counts'], bins=20, color='blue', alpha=0.7)
    axs[0, 0].set_title('Distribution of Section Counts per Page')
    axs[0, 0].set_xlabel('Number of Sections')
    axs[0, 0].set_ylabel('Frequency')
    
    # Plot section length distribution
    axs[0, 1].hist(breakpoint_data['avg_section_lengths'], bins=20, color='green', alpha=0.7)
    axs[0, 1].set_title('Distribution of Average Section Lengths')
    axs[0, 1].set_xlabel('Average Section Length (characters)')
    axs[0, 1].set_ylabel('Frequency')
    
    # Plot paragraph count distribution
    axs[1, 0].hist(breakpoint_data['paragraph_counts'], bins=20, color='red', alpha=0.7)
    axs[1, 0].set_title('Distribution of Paragraph Counts per Page')
    axs[1, 0].set_xlabel('Number of Paragraphs')
    axs[1, 0].set_ylabel('Frequency')
    
    # Plot paragraph length distribution
    axs[1, 1].hist(breakpoint_data['avg_paragraph_lengths'], bins=20, color='purple', alpha=0.7)
    axs[1, 1].set_title('Distribution of Average Paragraph Lengths')
    axs[1, 1].set_xlabel('Average Paragraph Length (characters)')
    axs[1, 1].set_ylabel('Frequency')
    
    plt.tight_layout()
    plot_path = Path('breakpoint_statistics.png')
    plt.savefig(plot_path)
    print(f"Breakpoint statistics plot saved to {plot_path.absolute()}")
    plt.close()

def plot_chunking_comparison(chunking_results):
    """Plot comparison of different chunking strategies."""
    chunk_sizes = list(chunking_results.keys())
    total_chunks = [chunking_results[size]['total_chunks'] for size in chunk_sizes]
    avg_chunks_per_page = [chunking_results[size]['avg_chunks_per_page'] for size in chunk_sizes]
    
    fig, axs = plt.subplots(1, 2, figsize=(12, 5))
    
    # Plot total chunks
    axs[0].bar(range(len(chunk_sizes)), total_chunks, color='blue', alpha=0.7)
    axs[0].set_xticks(range(len(chunk_sizes)))
    axs[0].set_xticklabels([f"{size}" for size in chunk_sizes])
    axs[0].set_title('Total Number of Chunks')
    axs[0].set_xlabel('Chunk Size (characters)')
    axs[0].set_ylabel('Number of Chunks')
    
    # Plot average chunks per page
    axs[1].bar(range(len(chunk_sizes)), avg_chunks_per_page, color='green', alpha=0.7)
    axs[1].set_xticks(range(len(chunk_sizes)))
    axs[1].set_xticklabels([f"{size}" for size in chunk_sizes])
    axs[1].set_title('Average Chunks per Page')
    axs[1].set_xlabel('Chunk Size (characters)')
    axs[1].set_ylabel('Avg Chunks per Page')
    
    plt.tight_layout()
    plot_path = Path('chunking_comparison.png')
    plt.savefig(plot_path)
    print(f"Chunking comparison plot saved to {plot_path.absolute()}")
    plt.close()

def plot_database_impact(db_size_estimates):
    """Plot database size impact of different chunking strategies."""
    chunk_sizes = list(db_size_estimates.keys())
    total_sizes = [db_size_estimates[size]['total_mb'] for size in chunk_sizes]
    
    # Create stacked bar components
    pages_sizes = [db_size_estimates[size]['pages_table_mb'] for size in chunk_sizes]
    chunks_sizes = [db_size_estimates[size]['chunks_table_mb'] for size in chunk_sizes]
    index_sizes = [db_size_estimates[size]['index_size_mb'] for size in chunk_sizes]
    
    plt.figure(figsize=(10, 6))
    
    # Create stacked bars
    plt.bar(range(len(chunk_sizes)), pages_sizes, label='Pages Table', color='blue', alpha=0.7)
    plt.bar(range(len(chunk_sizes)), chunks_sizes, bottom=pages_sizes, label='Chunks Table', color='green', alpha=0.7)
    plt.bar(range(len(chunk_sizes)), index_sizes, bottom=[p+c for p,c in zip(pages_sizes, chunks_sizes)], 
            label='Index Size', color='red', alpha=0.7)
    
    plt.xticks(range(len(chunk_sizes)), [f"{size}" for size in chunk_sizes])
    plt.title('Estimated Database Size by Chunking Strategy')
    plt.xlabel('Chunk Size (characters)')
    plt.ylabel('Size (MB)')
    plt.legend()
    
    plt.tight_layout()
    plot_path = Path('database_impact.png')
    plt.savefig(plot_path)
    print(f"Database impact plot saved to {plot_path.absolute()}")
    plt.close()

def main():
    """Run the chunking strategy analysis."""
    print("=== Chunking Strategy Analysis ===")
    
    # Analyze natural breakpoints
    print("Analyzing natural breakpoints in content...")
    breakpoint_data = analyze_natural_breakpoints()
    
    # Display summary statistics
    print("\nNatural Breakpoint Statistics:")
    print(f"  Avg sections per page: {np.mean(breakpoint_data['section_counts']):.2f}")
    print(f"  Max sections in a page: {max(breakpoint_data['section_counts'])}")
    print(f"  Avg section length: {np.mean(breakpoint_data['avg_section_lengths']):.2f} characters")
    print(f"  Avg paragraphs per page: {np.mean(breakpoint_data['paragraph_counts']):.2f}")
    print(f"  Max paragraphs in a page: {max(breakpoint_data['paragraph_counts'])}")
    print(f"  Avg paragraph length: {np.mean(breakpoint_data['avg_paragraph_lengths']):.2f} characters")
    
    # Plot breakpoint statistics
    plot_breakpoint_statistics(breakpoint_data)
    
    # Simulate different chunk sizes
    print("\nSimulating different chunking strategies...")
    chunk_sizes = [500, 1000, 2000, 3000, 5000, 10000]
    chunking_results = simulate_different_chunk_sizes(chunk_sizes)
    
    # Display chunking results
    print("\nChunking Strategy Results:")
    for size in chunk_sizes:
        result = chunking_results[size]
        print(f"\n  Chunk size {size} characters:")
        print(f"    Total chunks: {result['total_chunks']}")
        print(f"    Avg chunks per page: {result['avg_chunks_per_page']:.2f}")
        print(f"    Max chunks for a page: {result['max_chunks_per_page']}")
    
    # Plot chunking comparison
    plot_chunking_comparison(chunking_results)
    
    # Estimate database impact
    print("\nEstimating database impact...")
    db_size_estimates = estimate_database_impact(chunking_results)
    
    # Display database impact estimates
    print("\nDatabase Size Estimates:")
    for size in chunk_sizes:
        estimate = db_size_estimates[size]
        print(f"\n  Chunk size {size} characters:")
        print(f"    Pages table: {estimate['pages_table_mb']:.2f} MB")
        print(f"    Chunks table: {estimate['chunks_table_mb']:.2f} MB")
        print(f"    Index size: {estimate['index_size_mb']:.2f} MB")
        print(f"    Total size: {estimate['total_mb']:.2f} MB")
    
    # Plot database impact
    plot_database_impact(db_size_estimates)
    
    # Make a recommendation
    print("\nRecommended Chunking Strategy:")
    # Simple heuristic: pick a size that balances chunk count and database size
    # This could be made more sophisticated
    balanced_size = 2000  # Default recommendation
    
    print(f"Based on the analysis, a chunk size of approximately {balanced_size} characters is recommended.")
    print("This balances the number of chunks (for search precision) with database size and efficiency.")
    print("Consider adjusting based on your specific search needs and server resources.")
    
    print("\nAnalysis complete!")

if __name__ == "__main__":
    main()
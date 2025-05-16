# analysis/analyze_basic_metrics.py
import os
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
import re
import datetime

# Add the current directory to the path so we can import common_utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import common_utils

def count_total_pages():
    """Count the total number of wiki pages crawled."""
    files = common_utils.list_wiki_files()
    return len(files)

def calculate_total_content_size():
    """Calculate the total size of all content in bytes and MB."""
    total_bytes = 0
    files = common_utils.list_wiki_files()
    
    for file_path in files:
        total_bytes += file_path.stat().st_size
    
    return {
        'bytes': total_bytes,
        'megabytes': total_bytes / (1024 * 1024)
    }

def analyze_content_length_distribution():
    """Analyze the distribution of content lengths."""
    files = common_utils.list_wiki_files()
    lengths = []
    
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        if wiki_data['content']:
            lengths.append(len(wiki_data['content']))
    
    return {
        'count': len(lengths),
        'min': min(lengths) if lengths else 0,
        'max': max(lengths) if lengths else 0,
        'mean': sum(lengths) / len(lengths) if lengths else 0,
        'median': sorted(lengths)[len(lengths)//2] if lengths else 0,
        'histogram_data': lengths
    }

def detect_date_ranges():
    """Detect date ranges mentioned in the content."""
    files = common_utils.list_wiki_files()
    # Date patterns to look for (simple version)
    date_pattern = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}'
    
    all_dates = []
    
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        if wiki_data['content']:
            dates = re.findall(date_pattern, wiki_data['content'], re.IGNORECASE)
            all_dates.extend(dates)
    
    return {
        'total_dates_found': len(all_dates),
        'unique_dates': len(set(all_dates)),
        'sample_dates': list(set(all_dates))[:20] if all_dates else []
    }

def plot_content_length_distribution(lengths):
    """Plot the distribution of content lengths."""
    plt.figure(figsize=(10, 6))
    plt.hist(lengths, bins=30, alpha=0.7, color='blue')
    plt.xlabel('Content Length (characters)')
    plt.ylabel('Frequency')
    plt.title('Distribution of Wiki Page Content Lengths')
    plt.axvline(np.mean(lengths), color='red', linestyle='dashed', linewidth=1)
    plt.text(np.mean(lengths)*1.1, plt.ylim()[1]*0.9, f'Mean: {int(np.mean(lengths))}')
    plt.grid(True, alpha=0.3)
    
    # Save the plot
    plot_path = Path('content_length_distribution.png')
    plt.savefig(plot_path)
    print(f"Plot saved to {plot_path.absolute()}")
    plt.close()

def main():
    """Run the basic metrics analysis."""
    print("=== Basic Metrics Analysis ===")
    
    # Count total pages
    total_pages = count_total_pages()
    print(f"Total pages crawled: {total_pages}")
    
    # Calculate total content size
    size_info = calculate_total_content_size()
    print(f"Total content size: {size_info['bytes']} bytes ({size_info['megabytes']:.2f} MB)")
    
    # Analyze content length distribution
    length_data = analyze_content_length_distribution()
    print("\nContent Length Distribution:")
    print(f"  Count: {length_data['count']}")
    print(f"  Min: {length_data['min']} characters")
    print(f"  Max: {length_data['max']} characters")
    print(f"  Mean: {length_data['mean']:.2f} characters")
    print(f"  Median: {length_data['median']} characters")
    
    # Plot the content length distribution
    if length_data['histogram_data']:
        plot_content_length_distribution(length_data['histogram_data'])
    
    # Detect date ranges
    date_info = detect_date_ranges()
    print("\nDate Detection:")
    print(f"  Total dates found: {date_info['total_dates_found']}")
    print(f"  Unique dates: {date_info['unique_dates']}")
    if date_info['sample_dates']:
        print("  Sample dates:")
        for date in date_info['sample_dates'][:5]:
            print(f"    - {date}")
    
    print("\nAnalysis complete!")

if __name__ == "__main__":
    main()
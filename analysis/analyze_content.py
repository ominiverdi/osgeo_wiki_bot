# analysis/analyze_content.py
import os
import sys
from pathlib import Path
import matplotlib.pyplot as plt
from collections import Counter, defaultdict
import re
import nltk
from nltk.corpus import stopwords

# Add the current directory to the path so we can import common_utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import common_utils

# Define categories to blacklist
CATEGORY_BLACKLIST = ['Categories', 'Category']

# Download necessary NLTK data
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

def extract_categories():
    """Extract and count all categories across wiki pages, excluding blacklisted ones."""
    files = common_utils.list_wiki_files()
    categories_counter = Counter()
    
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        for category in wiki_data['categories']:
            # Skip blacklisted categories
            if category not in CATEGORY_BLACKLIST:
                categories_counter[category] += 1
    
    return categories_counter

def simple_tokenize(text):
    """Simple word tokenization function that doesn't require punkt_tab."""
    # Convert to lowercase and replace punctuation with spaces
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    # Split on whitespace and filter empty strings
    return [word for word in text.split() if word]

def identify_top_keywords(min_word_length=3, top_n=200):
    """Identify top keywords across all content, excluding stopwords."""
    files = common_utils.list_wiki_files()
    word_counter = Counter()
    stop_words = set(stopwords.words('english'))
    
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        if wiki_data['content']:
            # Use simple tokenization instead of nltk.word_tokenize
            tokens = simple_tokenize(wiki_data['content'])
            filtered_words = [
                word for word in tokens 
                if word.isalpha() and 
                len(word) >= min_word_length and 
                word not in stop_words
            ]
            word_counter.update(filtered_words)
    
    return word_counter.most_common(top_n)

def generate_term_frequency_by_category(top_categories=10, top_terms=20):
    """Generate term frequency analysis for top categories."""
    files = common_utils.list_wiki_files()
    
    # Get top categories first (excluding blacklisted)
    categories_counter = extract_categories()
    top_cat_names = [cat for cat, _ in categories_counter.most_common(top_categories)]
    
    # Initialize category-specific word counters
    category_terms = {cat: Counter() for cat in top_cat_names}
    stop_words = set(stopwords.words('english'))
    
    # Process files
    for file_path in files:
        wiki_data = common_utils.parse_wiki_file(file_path)
        
        # Filter out blacklisted categories from the page categories
        page_categories = set([cat for cat in wiki_data['categories'] 
                            if cat not in CATEGORY_BLACKLIST])
        
        # Check if page belongs to any top category
        matching_categories = page_categories.intersection(top_cat_names)
        
        if matching_categories and wiki_data['content']:
            # Use simple tokenization
            tokens = simple_tokenize(wiki_data['content'])
            filtered_words = [
                word for word in tokens 
                if word.isalpha() and 
                len(word) >= 3 and 
                word not in stop_words
            ]
            
            # Update counters for each matching category
            for category in matching_categories:
                category_terms[category].update(filtered_words)
    
    # Extract top terms for each category
    result = {}
    for category, counter in category_terms.items():
        result[category] = counter.most_common(top_terms)
    
    return result

def plot_category_distribution(categories_counter, top_n=20):
    """Plot the distribution of top categories."""
    top_categories = categories_counter.most_common(top_n)
    categories, counts = zip(*top_categories) if top_categories else ([], [])
    
    plt.figure(figsize=(12, 8))
    plt.barh(range(len(categories)), counts, align='center')
    plt.yticks(range(len(categories)), categories)
    plt.xlabel('Number of Pages')
    plt.ylabel('Category')
    plt.title(f'Top {len(categories)} Categories')
    plt.tight_layout()
    
    # Save the plot
    plot_path = Path('category_distribution.png')
    plt.savefig(plot_path)
    print(f"Plot saved to {plot_path.absolute()}")
    plt.close()

def plot_keyword_cloud(keywords, top_n=100):
    """Generate and save a word cloud of top keywords."""
    try:
        from wordcloud import WordCloud
        
        # Create dictionary for word cloud
        word_dict = {word: count for word, count in keywords[:top_n]}
        
        # Generate word cloud
        wordcloud = WordCloud(width=800, height=400, 
                             background_color='white', 
                             max_words=top_n).generate_from_frequencies(word_dict)
        
        # Plot
        plt.figure(figsize=(10, 5))
        plt.imshow(wordcloud, interpolation='bilinear')
        plt.axis('off')
        plt.tight_layout()
        
        # Save
        cloud_path = Path('keyword_cloud.png')
        plt.savefig(cloud_path)
        print(f"Word cloud saved to {cloud_path.absolute()}")
        plt.close()
    except ImportError:
        print("WordCloud package not installed. Install with: pip install wordcloud")
        print("Top 30 keywords:")
        for word, count in keywords[:30]:
            print(f"  {word}: {count}")

def main():
    """Run the content analysis."""
    print("=== Content Analysis ===")
    
    # Extract categories (excluding blacklisted ones)
    print("Analyzing categories...")
    categories_counter = extract_categories()
    total_categories = len(categories_counter)
    total_categorized_pages = sum(categories_counter.values())
    
    print(f"Total unique categories (excluding blacklisted): {total_categories}")
    print(f"Total pages with meaningful categories: {total_categorized_pages}")
    print(f"Blacklisted categories: {', '.join(CATEGORY_BLACKLIST)}")
    
    # Top categories
    print("\nTop 15 meaningful categories:")
    for category, count in categories_counter.most_common(15):
        print(f"  {category}: {count} pages")
    
    # Plot category distribution
    plot_category_distribution(categories_counter)
    
    # Identify top keywords
    print("\nAnalyzing keywords...")
    top_keywords = identify_top_keywords()
    
    print("Top 20 keywords across all content:")
    for word, count in top_keywords[:20]:
        print(f"  {word}: {count}")
    
    # Generate word cloud
    plot_keyword_cloud(top_keywords)
    
    # Generate term frequency by category
    print("\nAnalyzing keywords by category...")
    category_terms = generate_term_frequency_by_category()
    
    print("Top 10 keywords for top 5 categories:")
    for i, (category, terms) in enumerate(list(category_terms.items())[:5]):
        if terms:  # Check if there are terms for this category
            print(f"\n  {category}:")
            for word, count in terms[:10]:
                print(f"    {word}: {count}")
    
    print("\nAnalysis complete!")

if __name__ == "__main__":
    main()
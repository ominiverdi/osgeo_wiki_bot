# analysis/common_utils.py
import os
import json
import re
from pathlib import Path
from collections import defaultdict

def get_wiki_dump_path():
    """Return the path to the wiki dump directory."""
    return Path("../wiki_dump")

def get_url_map():
    """Load and return the URL map from the wiki dump."""
    url_map_path = get_wiki_dump_path() / "url_map.json"
    if url_map_path.exists():
        with open(url_map_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def list_wiki_files():
    """Return a list of all wiki files in the dump."""
    wiki_dump_path = get_wiki_dump_path()
    # Exclude url_map.json
    return [f for f in wiki_dump_path.glob('*') 
            if f.is_file() and f.name != 'url_map.json']

def parse_wiki_file(file_path):
    """Parse a wiki file and return its structured content."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract basic metadata
    url_match = re.search(r'URL: (.*?)\n', content)
    title_match = re.search(r'Title: (.*?)\n', content)
    
    # Extract categories
    categories = []
    categories_section = re.search(r'Categories:\n(.*?)\n\nContent:', 
                                  content, re.DOTALL)
    if categories_section:
        categories_text = categories_section.group(1)
        categories = [cat.strip('- \n') for cat in categories_text.split('\n')
                     if cat.strip('- \n')]
    
    # Extract main content
    content_match = re.search(r'Content:\n(.*)', content, re.DOTALL)
    main_content = content_match.group(1) if content_match else ""
    
    return {
        'url': url_match.group(1) if url_match else None,
        'title': title_match.group(1) if title_match else None,
        'categories': categories,
        'content': main_content,
        'file_path': file_path
    }

def extract_sections(content):
    """Extract sections from wiki content."""
    # Simple section detection based on common patterns
    section_pattern = r'(?:^|\n)([A-Za-z0-9 ]+)\n[-=]+\n'
    sections = re.split(section_pattern, content)
    if sections and len(sections) > 1:
        # Reshape into pairs of [section_title, section_content]
        result = []
        for i in range(1, len(sections), 2):
            if i+1 < len(sections):
                result.append((sections[i], sections[i+1]))
        return result
    return [('Main', content)]  # No sections found

def extract_potential_chunks(content, min_size=100, max_size=1000):
    """Extract potential chunks from content based on size constraints."""
    # First try to split by sections
    sections = extract_sections(content)
    
    chunks = []
    for section_title, section_content in sections:
        # If section is too large, split by paragraphs
        if len(section_content) > max_size:
            paragraphs = re.split(r'\n\n+', section_content)
            current_chunk = ""
            
            for para in paragraphs:
                if len(current_chunk) + len(para) <= max_size:
                    current_chunk += para + "\n\n"
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = para + "\n\n"
            
            if current_chunk:
                chunks.append(current_chunk.strip())
        else:
            chunks.append(section_content.strip())
    
    # Filter out chunks that are too small
    return [chunk for chunk in chunks if len(chunk) >= min_size]
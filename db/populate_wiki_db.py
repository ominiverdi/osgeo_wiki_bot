# db/populate_wiki_db.py
import os
import sys
import re
import psycopg2
from pathlib import Path
import json
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Define constants
CHUNK_SIZE = 500  # Characters per chunk
CATEGORY_BLACKLIST = ['Categories', 'Category']  # Categories to ignore

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

def get_wiki_dump_path():
    """Return the path to the wiki dump directory."""
    return Path("../wiki_dump")

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
        'categories': [c for c in categories if c not in CATEGORY_BLACKLIST],
        'content': main_content,
        'file_path': str(file_path)
    }

def chunk_content(content, chunk_size=CHUNK_SIZE):
    """Split content into chunks of approximately chunk_size characters."""
    chunks = []
    current_chunk = ""
    
    # Split by paragraphs
    paragraphs = re.split(r'\n\n+', content)
    
    for para in paragraphs:
        if not para.strip():
            continue
        
        # If this paragraph would fit in the current chunk, add it
        if len(current_chunk) + len(para) <= chunk_size:
            current_chunk += para + "\n\n"
        else:
            # If the current chunk is non-empty, add it to the list
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            # If the paragraph itself is longer than chunk_size, split it
            if len(para) > chunk_size:
                # Simple approach: split by sentences
                sentences = re.split(r'(?<=[.!?])\s+', para)
                current_chunk = ""
                
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) <= chunk_size:
                        current_chunk += sentence + " "
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = sentence + " "
            else:
                # Start a new chunk with this paragraph
                current_chunk = para + "\n\n"
    
    # Add the last chunk if non-empty
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def get_page_id_by_url(conn, url):
    """Check if a page exists by URL and return its ID if it does."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM pages WHERE url = %s", (url,))
            result = cur.fetchone()
            return result[0] if result else None
    except psycopg2.Error as e:
        print(f"Error checking if page exists: {e}")
        return None

def insert_page(conn, page_data):
    """Insert a new page and return its ID."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pages (title, url) VALUES (%s, %s) RETURNING id",
                (page_data['title'], page_data['url'])
            )
            return cur.fetchone()[0]
    except psycopg2.Error as e:
        print(f"Error inserting page: {e}")
        return None

def update_page(conn, page_id, page_data):
    """Update an existing page."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pages SET title = %s, url = %s, last_crawled = CURRENT_TIMESTAMP WHERE id = %s",
                (page_data['title'], page_data['url'], page_id)
            )
            return True
    except psycopg2.Error as e:
        print(f"Error updating page: {e}")
        return False

def clear_page_chunks(conn, page_id):
    """Remove all chunks for a page."""
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM page_chunks WHERE page_id = %s", (page_id,))
            return True
    except psycopg2.Error as e:
        print(f"Error clearing page chunks: {e}")
        return False

def clear_page_categories(conn, page_id):
    """Remove all categories for a page."""
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM page_categories WHERE page_id = %s", (page_id,))
            return True
    except psycopg2.Error as e:
        print(f"Error clearing page categories: {e}")
        return False

def insert_page_chunks(conn, page_id, content):
    """Split content into chunks and insert them."""
    chunks = chunk_content(content)
    
    try:
        with conn.cursor() as cur:
            for i, chunk_text in enumerate(chunks):
                cur.execute(
                    "INSERT INTO page_chunks (page_id, chunk_index, chunk_text) VALUES (%s, %s, %s)",
                    (page_id, i, chunk_text)
                )
            return True
    except psycopg2.Error as e:
        print(f"Error inserting page chunks: {e}")
        return False

def insert_page_categories(conn, page_id, categories):
    """Insert categories for a page."""
    if not categories:
        return True
    
    try:
        with conn.cursor() as cur:
            for category in categories:
                cur.execute(
                    "INSERT INTO page_categories (page_id, category_name) VALUES (%s, %s)",
                    (page_id, category)
                )
            return True
    except psycopg2.Error as e:
        print(f"Error inserting page categories: {e}")
        return False

def content_has_changed(conn, page_id, new_content):
    """Check if content has changed by comparing chunks."""
    try:
        # Count the chunks we'd create from the new content
        new_chunks = chunk_content(new_content)
        new_chunk_count = len(new_chunks)
        
        # Check if number of chunks is different
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM page_chunks WHERE page_id = %s", 
                (page_id,)
            )
            current_chunk_count = cur.fetchone()[0]
            
            if current_chunk_count != new_chunk_count:
                return True
            
            # Compare each chunk (this is expensive but thorough)
            cur.execute(
                "SELECT chunk_index, chunk_text FROM page_chunks WHERE page_id = %s ORDER BY chunk_index",
                (page_id,)
            )
            current_chunks = {idx: text for idx, text in cur.fetchall()}
            
            for i, chunk_text in enumerate(new_chunks):
                if i not in current_chunks or current_chunks[i] != chunk_text:
                    return True
            
            return False
    except psycopg2.Error as e:
        print(f"Error checking if content changed: {e}")
        # If we can't check, assume it changed to be safe
        return True

def process_page(conn, page_data):
    """Process a page by inserting or updating it and its related data."""
    # Skip if URL is missing
    if not page_data['url']:
        print(f"Skipping page with missing URL: {page_data['title']}")
        return False
    
    # Check if page exists
    page_id = get_page_id_by_url(conn, page_data['url'])
    
    if page_id:
        # Page exists - check if content changed
        if content_has_changed(conn, page_id, page_data['content']):
            # Update page
            update_page(conn, page_id, page_data)
            
            # Clear and reinsert chunks and categories
            clear_page_chunks(conn, page_id)
            clear_page_categories(conn, page_id)
            insert_page_chunks(conn, page_id, page_data['content'])
            insert_page_categories(conn, page_id, page_data['categories'])
            
            print(f"Updated page: {page_data['title']}")
        else:
            print(f"Skipped unchanged page: {page_data['title']}")
    else:
        # New page - insert it
        page_id = insert_page(conn, page_data)
        if page_id:
            insert_page_chunks(conn, page_id, page_data['content'])
            insert_page_categories(conn, page_id, page_data['categories'])
            print(f"Added new page: {page_data['title']}")
        else:
            print(f"Failed to add page: {page_data['title']}")
            return False
    
    return True

def main():
    print("=== OSGeo Wiki Database Population ===")
    
    # Connect to database
    conn = get_db_connection()
    
    # Create a Path object for the wiki dump
    wiki_dump_path = get_wiki_dump_path()
    
    # Check if wiki dump exists
    if not wiki_dump_path.exists():
        print(f"Error: Wiki dump directory not found at {wiki_dump_path}")
        return
    
    # Get all wiki files
    wiki_files = list_wiki_files()
    total_files = len(wiki_files)
    
    print(f"Found {total_files} wiki files to process")
    
    # Process all files
    processed = 0
    success = 0
    
    for i, file_path in enumerate(wiki_files):
        # Show progress
        if i % 100 == 0 and i > 0:
            print(f"Progress: {i}/{total_files} files processed")
        
        # Parse and process the file
        try:
            page_data = parse_wiki_file(file_path)
            if process_page(conn, page_data):
                success += 1
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")
        
        processed += 1
    
    print(f"\nPopulation complete!")
    print(f"Processed {processed} files")
    print(f"Successfully added/updated {success} pages")
    
    # Close the database connection
    conn.close()

if __name__ == "__main__":
    main()
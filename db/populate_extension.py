#!/usr/bin/env python3
# db/populate_extension.py - Optimized version with ID-based pagination
import os
import psycopg2
import asyncio
import httpx
from pathlib import Path
import re
import time
import json
import argparse
import logging
from datetime import datetime
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("populate_extension.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/api/generate"
LLM_MODEL = os.getenv("LLM_MODEL", "wiki-extractor")

# Content length thresholds
MIN_CONTENT_LENGTH = 500  # Minimum characters required to generate a resume
MAX_CONTENT_LENGTH = 30000  # Maximum characters to send to the LLM

# Checkpoint file for resume capability
DEFAULT_CHECKPOINT_FILE = "extension_checkpoint.json"

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
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        return None

async def generate_resume(title, content):
    """Generate a resume using the LLM."""
    prompt = f"""You are generating a database-optimized factual summary of "{title}" ({MIN_CONTENT_LENGTH} characters).

OUTPUT FORMAT: Bullet list of key facts only.
* Start each point with an asterisk
* Include all names, dates, URLs, and precise details
* No introductions, conclusions, or questions
* No headings or sections
* Use plain text only (no bold/formatting)

CONTENT:
{content[:MAX_CONTENT_LENGTH]}
"""

    try:
        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 2048
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_API_URL,
                json=payload,
                timeout=120.0  # Increased timeout for larger content
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                error_msg = f"Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return error_msg
    except Exception as e:
        error_msg = f"Error generating resume: {str(e)}"
        logger.error(error_msg)
        return error_msg

async def generate_keywords(title, content):
    """Generate searchable keywords using the LLM."""
    prompt = f"""You are generating searchable keywords for a database index of "{title}".

Extract ONLY terms and phrases that ACTUALLY APPEAR in the content. Focus on:

1. Names of people, organizations, projects, and places
2. Technical terms and their variations
3. Important dates, versions, and events
4. Relationship patterns (e.g., person-role, project-version combinations)

RULES:
- Include ONLY terms present in the original content
- Use space separation between terms
- Keep keywords concise (1-3 words per concept)
- Do not invent or add any terms not in the original text
- Use commas to separate terms (no line breaks)
- Between 20-50 words total
- Generate diverse, non-repetitive keywords. Each concept, name, or date should appear only once, regardless of how frequently it appears in the source. Only repeat a term when it appears in different contextual combinations.
- Do not include explanatory text or descriptions in your response

CONTENT:
{content[:MAX_CONTENT_LENGTH]}
"""

    try:
        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 1024
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OLLAMA_API_URL,
                json=payload,
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                error_msg = f"Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return error_msg
    except Exception as e:
        error_msg = f"Error generating keywords: {str(e)}"
        logger.error(error_msg)
        return error_msg

def count_words(text):
    """Count the number of words in text."""
    return len(re.findall(r'\w+', text))

def insert_or_update_page_extension(conn, wiki_url, page_title, resume, keywords):
    """Insert or update a record in the page_extensions table."""
    try:
        with conn.cursor() as cur:
            # Check if the page already exists in the extensions table
            cur.execute("SELECT id FROM page_extensions WHERE wiki_url = %s", (wiki_url,))
            result = cur.fetchone()
            
            if result:
                # Update existing record
                page_id = result[0]
                cur.execute("""
                    UPDATE page_extensions 
                    SET resume = %s, keywords = %s, last_updated = CURRENT_TIMESTAMP 
                    WHERE id = %s
                """, (resume, keywords, page_id))
                logger.info(f"Updated extension for page: {page_title}")
                return "updated"
            else:
                # Insert new record
                cur.execute("""
                    INSERT INTO page_extensions (wiki_url, page_title, resume, keywords)
                    VALUES (%s, %s, %s, %s)
                """, (wiki_url, page_title, resume, keywords))
                logger.info(f"Inserted new extension for page: {page_title}")
                return "inserted"
    except Exception as e:
        logger.error(f"Database error for {page_title}: {e}")
        return "error"

async def process_page(conn, page_id, title, url, content, content_length, force=False):
    """Process a single page and insert/update its extension."""
    try:
        # Check if we should skip this page based on content length
        if content_length < MIN_CONTENT_LENGTH:
            logger.info(f"Skipping {title} - content too short ({content_length} chars)")
            
            # For very short content, we'll just use the original content as the resume
            # and extract minimal keywords
            if force:
                logger.info(f"Force processing enabled, storing original content as resume")
                status = insert_or_update_page_extension(
                    conn, 
                    url, 
                    title, 
                    content, 
                    title.replace(" ", ", ")  # Simple keywords from title
                )
                return status
            return "skipped"
        
        # Check if page is already processed and we're not forcing an update
        if not force:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM page_extensions WHERE wiki_url = %s", (url,))
                if cur.fetchone():
                    logger.info(f"Skipping {title} - already processed")
                    return "skipped"
        
        # Generate resume
        logger.info(f"Generating resume for {title}...")
        resume = await generate_resume(title, content)
        resume_word_count = count_words(resume)
        resume_char_count = len(resume)
        
        # Check if resume generation failed or is suspicious
        if "Error:" in resume or resume_word_count < 10:
            logger.warning(f"Resume generation may have failed for {title}: {resume[:100]}...")
            if force:
                # Use the original content as a fallback
                resume = content
        
        # Generate keywords
        logger.info(f"Generating keywords for {title}...")
        keywords = await generate_keywords(title, content)
        keywords_word_count = count_words(keywords)
        
        # Check if keyword generation failed
        if "Error:" in keywords or keywords_word_count < 5:
            logger.warning(f"Keyword generation may have failed for {title}: {keywords[:100]}...")
            if force:
                # Use the title words as a fallback
                keywords = title.replace(" ", ", ")
        
        # Log statistics
        logger.info(f"Generated resume: {resume_word_count} words, {resume_char_count} chars")
        logger.info(f"Generated keywords: {keywords_word_count} words, {len(keywords)} chars")
        
        # Insert or update in database
        return insert_or_update_page_extension(conn, url, title, resume, keywords)
    
    except Exception as e:
        logger.error(f"Error processing {title}: {e}")
        return "error"

def get_pages_to_process(conn, limit=None, last_id=0, already_processed=False, random_order=False):
    """Get pages that need processing using ID-based pagination."""
    try:
        with conn.cursor() as cur:
            # Base query to get pages
            query = """
                SELECT p.id, p.title, p.url, 
                       string_agg(pc.chunk_text, ' ' ORDER BY pc.chunk_index) as full_content,
                       COUNT(pc.id) as chunk_count
                FROM pages p
                JOIN page_chunks pc ON p.id = pc.page_id
            """
            
            # Add conditions
            conditions = []
            
            # Add condition for ID-based pagination
            if last_id > 0:
                conditions.append(f"p.id > {last_id}")
            
            # Add condition for already processed pages if requested
            if not already_processed:
                conditions.append("NOT EXISTS (SELECT 1 FROM page_extensions pe WHERE pe.wiki_url = p.url)")
            
            # Add WHERE clause if we have conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            # Group by page
            query += " GROUP BY p.id, p.title, p.url"
            
            # Add ordering
            if random_order:
                query += " ORDER BY RANDOM()"
            else:
                query += " ORDER BY p.id"  # Ensures we process in ID order
            
            # Add limit if specified
            if limit:
                query += f" LIMIT {limit}"
            
            # Execute query
            cur.execute(query)
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Error getting pages to process: {e}")
        return []

def save_checkpoint(checkpoint_file, data):
    """Save checkpoint to a file."""
    try:
        checkpoint_path = os.path.abspath(checkpoint_file)
        with open(checkpoint_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nCheckpoint saved to {checkpoint_path}")
        logger.info(f"Checkpoint saved to {checkpoint_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving checkpoint: {e}")
        return False

def load_checkpoint(checkpoint_file):
    """Load checkpoint from a file."""
    try:
        checkpoint_path = os.path.abspath(checkpoint_file)
        with open(checkpoint_path, 'r') as f:
            data = json.load(f)
        logger.info(f"Checkpoint loaded from {checkpoint_path}")
        return data
    except FileNotFoundError:
        logger.warning(f"Checkpoint file {checkpoint_path} not found. Starting new run.")
        return None
    except Exception as e:
        logger.error(f"Error loading checkpoint: {e}")
        return None

def get_total_pages(conn, already_processed=False):
    """Get the total number of pages that match the criteria."""
    try:
        with conn.cursor() as cur:
            query = "SELECT COUNT(*) FROM pages"
            
            if not already_processed:
                query += """ WHERE NOT EXISTS (
                    SELECT 1 FROM page_extensions pe WHERE pe.wiki_url = pages.url
                )"""
            
            cur.execute(query)
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Error getting total pages: {e}")
        return 0

async def main_async(args):
    """Process pages asynchronously."""
    print(f"=== Populating page_extensions table ===")
    checkpoint_path = os.path.abspath(args.checkpoint_file)
    print(f"Checkpoint file: {checkpoint_path}")
    
    # Connect to database
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return
    
    try:
        # Initialize or load checkpoint
        last_id = 0
        stats = {"inserted": 0, "updated": 0, "skipped": 0, "error": 0}
        start_time = time.time()
        processed_count = 0
        
        if args.resume and os.path.exists(args.checkpoint_file):
            checkpoint_data = load_checkpoint(args.checkpoint_file)
            if checkpoint_data:
                last_id = checkpoint_data.get("last_id", 0)
                stats = checkpoint_data.get("stats", stats)
                start_time = checkpoint_data.get("start_time", start_time)
                processed_count = checkpoint_data.get("processed_count", 0)
                
                logger.info(f"Resuming from checkpoint: {processed_count} pages processed, last ID: {last_id}")
        
        # Get total pages for progress tracking
        total_eligible = get_total_pages(conn, already_processed=args.force)
        logger.info(f"Total eligible pages: {total_eligible}")
        
        # Process pages in batches to avoid memory issues
        batch_size = min(100, args.limit if args.limit else 100)
        remaining = args.limit if args.limit else total_eligible
        
        # Main processing loop
        while remaining > 0:
            current_batch = min(batch_size, remaining)
            
            # Get batch of pages to process using ID-based pagination
            logger.info(f"Fetching batch of {current_batch} pages (last_id={last_id}, force={args.force}, random={args.random})")
            pages = get_pages_to_process(
                conn, 
                limit=current_batch,
                last_id=last_id,
                already_processed=args.force,
                random_order=args.random
            )
            
            if not pages:
                logger.info("No pages to process")
                break
            
            # Log number of pages found
            logger.info(f"Found {len(pages)} pages to process")
            
            # Track highest ID in this batch (for checkpoint)
            batch_highest_id = last_id
            
            # Process each page in the batch
            for idx, (page_id, title, url, content, chunk_count) in enumerate(pages, 1):
                global_idx = processed_count + idx
                logger.info(f"Processing {global_idx}/{total_eligible}: {title} (ID: {page_id})")
                content_length = len(content) if content else 0
                
                # Update highest ID
                batch_highest_id = max(batch_highest_id, page_id)
                
                # Log page details
                print(f"\nPage: {title}")
                print(f"Page ID: {page_id}")
                print(f"Wiki URL: {url}")
                print(f"Content length: ({count_words(content)} words, {content_length} characters)")
                
                # Process the page
                result = await process_page(conn, page_id, title, url, content, content_length, args.force)
                stats[result] = stats.get(result, 0) + 1
                
                # Update checkpoint after every 10 pages
                if idx % 10 == 0 or idx == len(pages):
                    checkpoint = {
                        "timestamp": datetime.now().isoformat(),
                        "last_id": batch_highest_id,
                        "processed_count": processed_count + idx,
                        "stats": stats,
                        "start_time": start_time,
                        "last_processed_title": title,
                        "last_processed_url": url
                    }
                    save_checkpoint(args.checkpoint_file, checkpoint)
                
                # Progress information
                elapsed = time.time() - start_time
                pages_per_second = global_idx / elapsed if elapsed > 0 else 0
                remaining_pages = total_eligible - global_idx
                eta_seconds = remaining_pages / pages_per_second if pages_per_second > 0 else 0
                
                # Display progress
                print(f"Progress: {global_idx}/{total_eligible} pages")
                print(f"Stats: {stats}")
                print(f"Speed: {pages_per_second:.2f} pages/sec, ETA: {eta_seconds/3600:.1f} hours")
                
                # Respect rate limits for the LLM service
                if idx < len(pages) and args.delay > 0:
                    await asyncio.sleep(args.delay)
            
            # Update counters for next batch
            processed_count += len(pages)
            last_id = batch_highest_id
            remaining -= len(pages)
            
            # Final checkpoint for this batch
            checkpoint = {
                "timestamp": datetime.now().isoformat(),
                "last_id": last_id,
                "processed_count": processed_count,
                "stats": stats,
                "start_time": start_time,
                "last_processed_title": pages[-1][1] if pages else "",
                "last_processed_url": pages[-1][2] if pages else ""
            }
            save_checkpoint(args.checkpoint_file, checkpoint)
        
        # Log final statistics
        elapsed = time.time() - start_time
        print("\n=== Processing complete ===")
        print(f"Elapsed time: {elapsed:.2f} seconds")
        print(f"Pages processed: {processed_count}")
        print(f"Results: {stats}")
        
    finally:
        if conn:
            conn.close()

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Populate page_extensions table with LLM-generated content")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of pages to process")
    parser.add_argument("--force", action="store_true", help="Force processing even if pages are already in the extensions table")
    parser.add_argument("--random", action="store_true", help="Process pages in random order")
    parser.add_argument("--delay", type=float, default=6.0, help="Delay between page processing (seconds)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint file")
    parser.add_argument("--checkpoint-file", default=DEFAULT_CHECKPOINT_FILE, help="Checkpoint file path")
    parser.add_argument("--show-checkpoint", action="store_true", help="Display the contents of the checkpoint file and exit")
    parser.add_argument("--init-checkpoint", action="store_true", help="Create initial checkpoint immediately")
    
    args = parser.parse_args()
    
    # Show checkpoint if requested
    if args.show_checkpoint:
        if os.path.exists(args.checkpoint_file):
            try:
                with open(args.checkpoint_file, 'r') as f:
                    checkpoint = json.load(f)
                    print("\nCheckpoint Contents:")
                    print(f"Timestamp: {checkpoint.get('timestamp')}")
                    print(f"Last ID: {checkpoint.get('last_id')}")
                    print(f"Pages Processed: {checkpoint.get('processed_count')}")
                    print(f"Statistics: {checkpoint.get('stats')}")
                    print(f"Last Processed Page: {checkpoint.get('last_processed_title')}")
                    print(f"Last Processed URL: {checkpoint.get('last_processed_url')}")
                    
                    # Show full checkpoint in debug mode
                    if os.getenv("DEBUG"):
                        print("\nFull Checkpoint Data:")
                        print(json.dumps(checkpoint, indent=2))
            except Exception as e:
                print(f"Error reading checkpoint file: {e}")
        else:
            print(f"Checkpoint file not found: {args.checkpoint_file}")
        return
    
    # Create initial checkpoint if requested
    if args.init_checkpoint:
        initial_checkpoint = {
            "timestamp": datetime.now().isoformat(),
            "last_id": 0,
            "processed_count": 0,
            "stats": {"inserted": 0, "updated": 0, "skipped": 0, "error": 0},
            "start_time": time.time(),
            "last_processed_title": "",
            "last_processed_url": ""
        }
        print(f"Creating initial checkpoint file at {os.path.abspath(args.checkpoint_file)}...")
        save_checkpoint(args.checkpoint_file, initial_checkpoint)
        print("Initial checkpoint created.")
        if not args.resume:
            return
    
    # Run the async main function
    asyncio.run(main_async(args))

if __name__ == "__main__":
    main()
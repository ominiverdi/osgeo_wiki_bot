#!/usr/bin/env python3
# db/populate_extension.py - Simplified production version
import os
import psycopg2
import asyncio
import httpx
from pathlib import Path
import json
import argparse
import logging
from datetime import datetime
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("populate_extension.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')



# Configuration
OLLAMA_BASE_URL = "http://localhost:8080"
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"
LLM_MODEL = "mistral-small-128k"

MAX_CONTENT_LENGTH = 20000  # Truncate at 20KB
LLM_TIMEOUT = 300  # 5 minutes timeout
CHECKPOINT_FILE = "extension_checkpoint.json"

WIKI_DUMP_PATH = Path(os.getenv('WIKI_DUMP_PATH', './wiki_dump'))


def get_db_connection():
    """Connect to PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "osgeo_wiki"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            port=os.getenv("DB_PORT", "5432")
        )
        conn.autocommit = True
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None


def log_error(conn, page_id, title, url, error_type, message, content_size, was_truncated=False, original_size=None):
    """Log processing error to page_processing_errors table."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO page_processing_errors 
                (page_id, page_title, wiki_url, error_type, error_message, 
                 content_size, was_truncated, original_size)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (page_id, title, url, error_type, message, content_size, was_truncated, original_size))
    except Exception as e:
        logger.error(f"Failed to log error: {e}")


async def call_llm(prompt, timeout=LLM_TIMEOUT):
    """Call LLM with timeout handling."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OLLAMA_API_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 4096
                }
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
    except asyncio.TimeoutError:
        raise TimeoutError(f"LLM call timed out after {timeout}s")
    except Exception as e:
        raise Exception(f"LLM call failed: {str(e)}")


async def generate_resume(content):
    """Generate resume from content."""
    prompt = f"""Extract ONLY the facts that appear in this text. Do not explain or expand.

Rules:
- Start each line with "* "
- Copy names, dates, URLs exactly
- If text is 1-2 sentences, just repeat it with "* " prefix
- Never explain what terms mean

Text:
{content}

BULLET POINTS:"""
    
    return await call_llm(prompt)


async def generate_keywords(content):
    """Generate keywords from content."""
    prompt = f"""Extract keywords that appear in this text. Do not add related terms.

Include: names, organizations, projects, technical terms, dates.
Maximum 30 keywords, comma-separated.
If minimal content, write: placeholder

Text:
{content}

KEYWORDS:"""
    
    return await call_llm(prompt)


def load_checkpoint():
    """Load checkpoint or return default."""
    try:
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_id": 0, "processed": 0, "timestamp": None}


def save_checkpoint(last_id, processed):
    """Save checkpoint."""
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump({
            "last_id": last_id,
            "processed": processed,
            "timestamp": datetime.now().isoformat()
        }, f)


def get_pages(conn, last_id=0, limit=None):
    """Get pages to process."""
    with conn.cursor() as cur:
        query = """
            SELECT p.id, p.title, p.url
            FROM pages p
            LEFT JOIN page_extensions pe ON p.url = pe.wiki_url
            WHERE p.id > %s AND pe.wiki_url IS NULL
            ORDER BY p.id
        """
        if limit:
            query += f" LIMIT {limit}"
        
        cur.execute(query, (last_id,))
        return cur.fetchall()


def get_content(conn, url):
    """Get page content from chunks."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT content 
            FROM page_chunks 
            WHERE page_id = (SELECT id FROM pages WHERE url = %s)
            ORDER BY chunk_number
        """, (url,))
        
        chunks = cur.fetchall()
        if not chunks:
            return None, 0
        
        full_content = ' '.join(chunk[0] for chunk in chunks)
        original_size = len(full_content)
        
        # Truncate if needed
        was_truncated = False
        if len(full_content) > MAX_CONTENT_LENGTH:
            full_content = full_content[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated at 20KB]"
            was_truncated = True
        
        return full_content, original_size, was_truncated


def save_extension(conn, url, title, resume, keywords):
    """Save to page_extensions table."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO page_extensions (wiki_url, page_title, resume, keywords, last_updated)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (wiki_url) 
            DO UPDATE SET 
                resume = EXCLUDED.resume,
                keywords = EXCLUDED.keywords,
                last_updated = CURRENT_TIMESTAMP
        """, (url, title, resume, keywords))


async def process_page(conn, page_id, title, url):
    """Process a single page."""
    try:
        # Get content
        # result = get_content(conn, url)
        result = get_content_from_dump(WIKI_DUMP_PATH, url)
        if not result or result[0] is None:
            log_error(conn, page_id, title, url, "no_content", "No content found", 0)
            return "error"
        
        content, original_size, was_truncated = result
        content_size = len(content)
        
        # Generate resume
        logger.info(f"  Generating resume...")
        try:
            resume = await generate_resume(content)
            if len(resume) < 50:
                raise Exception("Resume too short")
        except TimeoutError as e:
            log_error(conn, page_id, title, url, "timeout", str(e), content_size, was_truncated, original_size)
            return "timeout"
        except Exception as e:
            log_error(conn, page_id, title, url, "llm_error", str(e), content_size, was_truncated, original_size)
            return "error"
        
        # Generate keywords
        logger.info(f"  Generating keywords...")
        try:
            keywords = await generate_keywords(content)
            if len(keywords) < 10:
                raise Exception("Keywords too short")
        except TimeoutError as e:
            log_error(conn, page_id, title, url, "timeout", str(e), content_size, was_truncated, original_size)
            return "timeout"
        except Exception as e:
            log_error(conn, page_id, title, url, "llm_error", str(e), content_size, was_truncated, original_size)
            return "error"
        
        # Save
        save_extension(conn, url, title, resume, keywords)
        
        # Log if truncated
        if was_truncated:
            log_error(conn, page_id, title, url, "truncated", 
                     f"Content truncated from {original_size} to {content_size} chars",
                     content_size, True, original_size)
        
        logger.info(f"  ✓ Saved (resume: {len(resume)} chars, keywords: {len(keywords)} chars)")
        return "success"
        
    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        log_error(conn, page_id, title, url, "other", str(e), 0)
        return "error"
def get_content_from_dump(wiki_dump_path, url):
    """Get page content from wiki dump file."""
    try:
        # Find the file by matching URL
        for filepath in wiki_dump_path.glob('*'):
            if filepath.name == 'url_map.json':
                continue
            
            with open(filepath, 'r', encoding='utf-8') as f:
                first_line = f.readline()
                if first_line.strip() == f'URL: {url}':
                    # Found the right file, read full content
                    f.seek(0)
                    content = f.read()
                    
                    # Extract content after "Content:" line
                    lines = content.split('\n')
                    content_start = 0
                    for i, line in enumerate(lines):
                        if line.strip() == 'Content:':
                            content_start = i + 1
                            break
                    
                    page_content = '\n'.join(lines[content_start:]).strip()
                    original_size = len(page_content)
                    
                    # Truncate if needed
                    was_truncated = False
                    if len(page_content) > MAX_CONTENT_LENGTH:
                        page_content = page_content[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated at 20KB]"
                        was_truncated = True
                    
                    return page_content, original_size, was_truncated
        
        return None, 0, False
        
    except Exception as e:
        logger.error(f"Error reading wiki dump: {e}")
        return None, 0, False

async def main():
    parser = argparse.ArgumentParser(description="Populate page extensions with LLM summaries")
    parser.add_argument("--limit", type=int, help="Limit number of pages to process")
    parser.add_argument("--delay", type=float, default=0, help="Delay between pages (seconds)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()
    
    # Connect to database
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return
    
    # Load checkpoint
    checkpoint = load_checkpoint() if args.resume else {"last_id": 0, "processed": 0}
    last_id = checkpoint["last_id"]
    total_processed = checkpoint["processed"]
    
    logger.info("="*70)
    logger.info(f"OSGeo Wiki Extension Population")
    logger.info("="*70)
    logger.info(f"Model: {LLM_MODEL}")
    logger.info(f"Max content size: {MAX_CONTENT_LENGTH} chars")
    logger.info(f"Timeout: {LLM_TIMEOUT}s")
    if args.resume:
        logger.info(f"Resuming from ID: {last_id} ({total_processed} already processed)")
    logger.info("="*70 + "\n")
    
    # Get pages to process
    pages = get_pages(conn, last_id, args.limit)
    if not pages:
        logger.info("No pages to process")
        conn.close()
        return
    
    logger.info(f"Found {len(pages)} pages to process\n")
    
    # Process pages
    start_time = asyncio.get_event_loop().time()
    for i, (page_id, title, url) in enumerate(pages, 1):
        logger.info(f"[{i}/{len(pages)}] {title}")
        
        result = await process_page(conn, page_id, title, url)
        
        if result == "success":
            total_processed += 1
        
        # Save checkpoint every 10 pages
        if i % 10 == 0:
            save_checkpoint(page_id, total_processed)
            elapsed = asyncio.get_event_loop().time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            logger.info(f"  Checkpoint saved. Rate: {rate:.2f} pages/sec\n")
        
        # Delay if specified
        if args.delay > 0:
            await asyncio.sleep(args.delay)
    
    # Final save
    save_checkpoint(pages[-1][0], total_processed)
    
    elapsed = asyncio.get_event_loop().time() - start_time
    logger.info("\n" + "="*70)
    logger.info(f"COMPLETE: {len(pages)} pages in {elapsed/60:.1f} minutes")
    logger.info(f"Total processed this session: {len(pages)}")
    logger.info(f"Total processed overall: {total_processed}")
    logger.info("="*70)
    
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
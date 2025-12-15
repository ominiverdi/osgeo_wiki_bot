#!/usr/bin/env python3
"""
Process Extensions - Worker for generating LLM summaries and keywords

Picks up 'extensions' tasks from the processing queue and generates
semantic summaries and keywords using OpenRouter free models.

Features:
- Uses OpenRouter API with free models
- Fallback chain if primary model fails
- Skips unchanged content (content_hash check)
- Rate limiting (5s between requests)
- Tracks which model was used
"""

import os
import sys
import time
import hashlib
import logging
import asyncio
import psycopg2
import httpx
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("process_extensions.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# OpenRouter Configuration
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Model fallback chain (in priority order)
# Based on evaluation: reliable models that work with free tier
MODEL_CHAIN = [
    "mistralai/devstral-2512:free",  # Primary: fast (8s), reliable, score 80
    "google/gemma-3-12b-it:free",  # Fallback: reliable (score 60), 28s
]

# Rate limiting
REQUEST_DELAY = 5  # seconds between requests (safe for 20 req/min limit)
LLM_TIMEOUT = 120  # seconds

# Content limits
MAX_CONTENT_LENGTH = 20000


def get_db_connection():
    """Connect to PostgreSQL database."""
    try:
        # Use None for host to enable Unix socket (peer auth)
        db_host = os.getenv("DB_HOST", "localhost")
        conn = psycopg2.connect(
            host=db_host if db_host else None,
            database=os.getenv("DB_NAME", "osgeo_wiki"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            port=os.getenv("DB_PORT", "5432"),
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        return None


def compute_content_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def call_openrouter(model: str, prompt: str, timeout: int = LLM_TIMEOUT) -> str:
    """
    Call OpenRouter API with a specific model.

    Raises:
        Exception on rate limit (429) or other errors
    """
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set in environment")

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://github.com/osgeo/wiki_bot",
                "X-Title": "OSGeo Wiki Bot",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 2048,
            },
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise Exception(f"Rate limited (429), retry after {retry_after}s")

        response.raise_for_status()
        result = response.json()

        return result["choices"][0]["message"]["content"].strip()


async def call_llm_with_fallback(prompt: str) -> tuple[str, str]:
    """
    Call LLM with fallback chain.

    Returns:
        Tuple of (response_text, model_used)
    """
    last_error = None

    for model in MODEL_CHAIN:
        try:
            logger.debug(f"  Trying model: {model}")
            response = await call_openrouter(model, prompt)
            return response, model
        except Exception as e:
            last_error = e
            logger.warning(f"  Model {model} failed: {e}")
            # Wait before trying next model
            await asyncio.sleep(REQUEST_DELAY)

    raise Exception(f"All models failed. Last error: {last_error}")


async def generate_resume(content: str) -> tuple[str, str]:
    """Generate resume/summary from content."""
    prompt = f"""Extract ONLY the facts that appear in this text. Do not explain or expand.

Rules:
- Start each line with "* "
- Copy names, dates, URLs exactly
- If text is 1-2 sentences, just repeat it with "* " prefix
- Never explain what terms mean
- Maximum 15 bullet points

Text:
{content}

BULLET POINTS:"""

    return await call_llm_with_fallback(prompt)


async def generate_keywords(content: str) -> tuple[str, str]:
    """Generate keywords from content."""
    prompt = f"""Extract keywords that appear in this text. Do not add related terms.

Include: names, organizations, projects, technical terms, dates.
Maximum 30 keywords, comma-separated.
If minimal content, write: placeholder

Text:
{content}

KEYWORDS:"""

    return await call_llm_with_fallback(prompt)


def get_page_content_with_hash(
    conn, page_id: int, source_page_id: int | None = None
) -> tuple[str, str, str, str] | None:
    """
    Get page content from source_pages table.

    Returns:
        Tuple of (title, url, content, content_hash) or None
    """
    with conn.cursor() as cur:
        # Get from source_pages
        if source_page_id:
            cur.execute(
                """SELECT title, url, content_text, content_hash 
                   FROM source_pages WHERE id = %s""",
                (source_page_id,),
            )
            result = cur.fetchone()
            if result and result[2]:
                content = result[2]
                if len(content) > MAX_CONTENT_LENGTH:
                    content = content[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated]"
                content_hash = result[3] or compute_content_hash(content)
                return result[0], result[1], content, content_hash

        # Fallback: get from source_pages via pages.url join
        cur.execute(
            """
            SELECT sp.title, sp.url, sp.content_text, sp.content_hash
            FROM source_pages sp
            JOIN pages p ON sp.url = p.url
            WHERE p.id = %s
            """,
            (page_id,),
        )
        result = cur.fetchone()
        if result and result[2]:
            content = result[2]
            if len(content) > MAX_CONTENT_LENGTH:
                content = content[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated]"
            content_hash = result[3] or compute_content_hash(content)
            return result[0], result[1], content, content_hash

        # Last fallback: just get title/url from pages
        cur.execute("SELECT title, url FROM pages WHERE id = %s", (page_id,))
        result = cur.fetchone()
        if result:
            logger.warning(
                f"No content in source_pages for page {page_id}: {result[0]}"
            )
            return result[0], result[1], "", ""

        return None


def get_existing_extension_hash(conn, url: str) -> str | None:
    """Get content_hash of existing extension for this URL."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content_hash FROM page_extensions WHERE url = %s",
            (url,),
        )
        result = cur.fetchone()
        return result[0] if result else None


def save_extension(
    conn,
    url: str,
    title: str,
    resume: str,
    keywords: str,
    content_hash: str,
    model_used: str,
):
    """Save to page_extensions table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO page_extensions 
                (url, page_title, resume, keywords, content_hash, model_used, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (url) 
            DO UPDATE SET 
                page_title = EXCLUDED.page_title,
                resume = EXCLUDED.resume,
                keywords = EXCLUDED.keywords,
                content_hash = EXCLUDED.content_hash,
                model_used = EXCLUDED.model_used,
                last_updated = CURRENT_TIMESTAMP
            """,
            (url, title, resume, keywords, content_hash, model_used),
        )


async def process_extensions_task(
    conn, queue_id: int, page_id: int, source_page_id: int | None = None
) -> bool:
    """
    Process a single extensions task.

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get page content with hash
        result = get_page_content_with_hash(conn, page_id, source_page_id)
        if not result:
            raise ValueError(f"Page {page_id} not found")

        title, url, content, content_hash = result

        if not content:
            logger.warning(f"Empty content for page {page_id}: {title}")
            save_extension(
                conn, url, title, "* No content available", "placeholder", "", "none"
            )
            conn.commit()
            return True

        # Check if content has changed
        existing_hash = get_existing_extension_hash(conn, url)
        if existing_hash and existing_hash == content_hash:
            logger.info(
                f"Skipping {title} - content unchanged (hash: {content_hash[:8]}...)"
            )
            return True

        # Generate resume
        logger.info(f"  Generating resume for {title}...")
        resume, resume_model = await generate_resume(content)
        if len(resume) < 20:
            logger.warning(f"Resume too short for {title}, using placeholder")
            resume = f"* {title}"

        # Rate limit delay
        await asyncio.sleep(REQUEST_DELAY)

        # Generate keywords
        logger.info(f"  Generating keywords for {title}...")
        keywords, keywords_model = await generate_keywords(content)
        if len(keywords) < 5:
            logger.warning(f"Keywords too short for {title}, using placeholder")
            keywords = "placeholder"

        # Use the model from resume (primary task)
        model_used = resume_model

        # Save to database
        save_extension(conn, url, title, resume, keywords, content_hash, model_used)
        conn.commit()

        logger.info(
            f"Generated extension for page {page_id} ({title}): "
            f"resume={len(resume)} chars, keywords={len(keywords)} chars, "
            f"model={model_used.split('/')[-1]}"
        )

        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing extensions for page {page_id}: {e}")
        raise


def claim_and_process_task(conn) -> bool:
    """
    Claim and process a single task.

    Returns:
        True if a task was processed, False if no tasks available
    """
    with conn.cursor() as cur:
        # Claim next task
        cur.execute("SELECT * FROM claim_task('extensions')")
        result = cur.fetchone()

        if not result:
            return False

        queue_id, page_id, source_page_id, attempts = result
        logger.info(f"Claimed task {queue_id} for page {page_id} (attempt {attempts})")

        try:
            success = asyncio.run(
                process_extensions_task(conn, queue_id, page_id, source_page_id)
            )
            cur.execute("SELECT complete_task(%s, %s, %s)", (queue_id, success, None))
            conn.commit()
            return True

        except Exception as e:
            error_msg = str(e)[:500]
            cur.execute(
                "SELECT complete_task(%s, %s, %s)", (queue_id, False, error_msg)
            )
            conn.commit()
            logger.error(f"Task {queue_id} failed: {error_msg}")
            return True


def process_queue(conn, limit: int = 10) -> dict:
    """
    Process multiple tasks from the queue.

    Args:
        conn: Database connection
        limit: Maximum number of tasks to process

    Returns:
        Statistics dict
    """
    stats = {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}

    for _ in range(limit):
        try:
            if not claim_and_process_task(conn):
                break
            stats["processed"] += 1
            stats["succeeded"] += 1
        except Exception:
            stats["processed"] += 1
            stats["failed"] += 1

        # Rate limit between tasks
        time.sleep(REQUEST_DELAY)

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process extensions tasks from queue")
    parser.add_argument(
        "--limit", type=int, default=10, help="Maximum tasks to process (default: 10)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not set in .env file")
        sys.exit(1)

    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        sys.exit(1)

    try:
        logger.info(f"Starting extension processing (limit={args.limit})")
        logger.info(f"Model chain: {', '.join(m.split('/')[-1] for m in MODEL_CHAIN)}")

        stats = process_queue(conn, limit=args.limit)

        print(f"\nProcessed: {stats['processed']}")
        print(f"Succeeded: {stats['succeeded']}")
        print(f"Failed: {stats['failed']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

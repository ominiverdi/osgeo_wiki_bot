#!/usr/bin/env python3
"""
Process Chunks - Worker for chunking wiki pages

Picks up 'chunks' tasks from the processing queue and splits page content
into searchable chunks with tsvector indexing.
"""

import os
import sys
import re
import logging
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("process_chunks.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Configuration
CHUNK_SIZE = 500  # Characters per chunk


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


def chunk_content(content: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split content into chunks of approximately chunk_size characters."""
    chunks = []
    current_chunk = ""

    # Split by paragraphs
    paragraphs = re.split(r"\n\n+", content)

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
                sentences = re.split(r"(?<=[.!?])\s+", para)
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


def get_page_content(
    conn, page_id: int, source_page_id: int | None = None
) -> tuple[str, str] | None:
    """Get page content from source_pages table (source of truth)."""
    with conn.cursor() as cur:
        # First try to get from source_pages using source_page_id
        if source_page_id:
            cur.execute(
                "SELECT title, content_text FROM source_pages WHERE id = %s",
                (source_page_id,),
            )
            result = cur.fetchone()
            if result and result[1]:
                return result[0], result[1]

        # Fallback: get from source_pages via pages.url join
        cur.execute(
            """
            SELECT sp.title, sp.content_text 
            FROM source_pages sp
            JOIN pages p ON sp.url = p.url
            WHERE p.id = %s
            """,
            (page_id,),
        )
        result = cur.fetchone()
        if result and result[1]:
            return result[0], result[1]

        # Last fallback: just get title from pages
        cur.execute("SELECT title FROM pages WHERE id = %s", (page_id,))
        result = cur.fetchone()
        if result:
            logger.warning(
                f"No content in source_pages for page {page_id}: {result[0]}"
            )
            return result[0], ""

        return None


def process_chunks_task(
    conn, queue_id: int, page_id: int, source_page_id: int | None = None
) -> bool:
    """
    Process a single chunks task.

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get page content from source_pages
        result = get_page_content(conn, page_id, source_page_id)
        if not result:
            raise ValueError(f"Page {page_id} not found")

        title, content = result

        if not content:
            logger.warning(f"Empty content for page {page_id}: {title}")
            # Still mark as success - nothing to chunk
            return True

        with conn.cursor() as cur:
            # Delete existing chunks
            cur.execute("DELETE FROM page_chunks WHERE page_id = %s", (page_id,))
            deleted = cur.rowcount

            # Create new chunks
            chunks = chunk_content(content)

            for i, chunk_text in enumerate(chunks):
                cur.execute(
                    """
                    INSERT INTO page_chunks (page_id, chunk_index, chunk_text)
                    VALUES (%s, %s, %s)
                    """,
                    (page_id, i, chunk_text),
                )

            conn.commit()

            logger.info(
                f"Chunked page {page_id} ({title}): "
                f"deleted {deleted}, created {len(chunks)} chunks"
            )

        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing chunks for page {page_id}: {e}")
        raise


def claim_and_process_task(conn) -> bool:
    """
    Claim and process a single task.

    Returns:
        True if a task was processed, False if no tasks available
    """
    with conn.cursor() as cur:
        # Claim next task
        cur.execute("SELECT * FROM claim_task('chunks')")
        result = cur.fetchone()

        if not result:
            return False

        queue_id, page_id, source_page_id, attempts = result
        logger.info(f"Claimed task {queue_id} for page {page_id} (attempt {attempts})")

        try:
            success = process_chunks_task(conn, queue_id, page_id, source_page_id)
            cur.execute("SELECT complete_task(%s, %s, %s)", (queue_id, success, None))
            conn.commit()
            return True

        except Exception as e:
            error_msg = str(e)[:500]  # Truncate error message
            cur.execute(
                "SELECT complete_task(%s, %s, %s)", (queue_id, False, error_msg)
            )
            conn.commit()
            logger.error(f"Task {queue_id} failed: {error_msg}")
            return True  # Task was processed (even if failed)


def process_queue(conn, limit: int = 10) -> dict:
    """
    Process multiple tasks from the queue.

    Args:
        conn: Database connection
        limit: Maximum number of tasks to process

    Returns:
        Statistics dict
    """
    stats = {"processed": 0, "succeeded": 0, "failed": 0}

    for _ in range(limit):
        try:
            if not claim_and_process_task(conn):
                break  # No more tasks
            stats["processed"] += 1
            stats["succeeded"] += 1
        except Exception:
            stats["processed"] += 1
            stats["failed"] += 1

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process chunks tasks from queue")
    parser.add_argument(
        "--limit", type=int, default=10, help="Maximum tasks to process (default: 10)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        sys.exit(1)

    try:
        stats = process_queue(conn, limit=args.limit)
        print(f"\nProcessed: {stats['processed']}")
        print(f"Succeeded: {stats['succeeded']}")
        print(f"Failed: {stats['failed']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

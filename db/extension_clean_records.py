#!/usr/bin/env python3
# db/clean_existing_records.py
import os
import psycopg2
import argparse
import time
import logging
from pathlib import Path
from dotenv import load_dotenv
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("clean_extensions.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Import the cleaning functions
from populate_extension import clean_resume, clean_keywords

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
        conn.autocommit = False  # We'll manage transactions manually
        return conn
    except psycopg2.Error as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        return None

def fetch_records(conn, batch_size=100, offset=0, limit=None):
    """Fetch a batch of records from page_extensions."""
    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, page_title, wiki_url, resume, keywords
                FROM page_extensions
                ORDER BY id
                LIMIT %s OFFSET %s
            """
            
            # If limit is specified, adjust the query
            if limit is not None:
                query = """
                    SELECT id, page_title, wiki_url, resume, keywords
                    FROM page_extensions
                    ORDER BY id
                    LIMIT %s OFFSET %s
                """
                cur.execute(query, (min(batch_size, limit), offset))
            else:
                cur.execute(query, (batch_size, offset))
                
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Error fetching records: {e}")
        return []

def update_record(conn, record_id, clean_resume_text, clean_keywords_text, dry_run=False):
    """Update a single record with cleaned text."""
    try:
        with conn.cursor() as cur:
            if not dry_run:
                cur.execute("""
                    UPDATE page_extensions
                    SET resume = %s, keywords = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (clean_resume_text, clean_keywords_text, record_id))
            return True
    except Exception as e:
        logger.error(f"Error updating record {record_id}: {e}")
        return False

def count_records(conn):
    """Count total records in page_extensions."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM page_extensions")
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Error counting records: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(description="Clean existing page_extensions records")
    parser.add_argument("--batch-size", type=int, default=100, help="Number of records to process in each batch")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of records to process")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without updating")
    parser.add_argument("--start-id", type=int, default=None, help="ID to start processing from")
    args = parser.parse_args()

    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return

    try:
        total_records = count_records(conn)
        if args.limit:
            total_to_process = min(args.limit, total_records)
        else:
            total_to_process = total_records

        logger.info(f"Found {total_records} total records, will process {total_to_process}")
        
        # Statistics
        stats = {
            "processed": 0,
            "updated_resume": 0,
            "updated_keywords": 0,
            "errors": 0
        }
        
        # Process in batches
        offset = 0
        if args.start_id:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM page_extensions WHERE id < %s", (args.start_id,))
                offset = cur.fetchone()[0]
                logger.info(f"Starting from ID {args.start_id} (offset {offset})")

        start_time = time.time()

        while stats["processed"] < total_to_process:
            batch = fetch_records(conn, args.batch_size, offset, 
                                limit=total_to_process - stats["processed"])
            
            if not batch:
                break
                
            # Process each record in the batch
            for record in batch:
                record_id, title, url, resume, keywords = record
                
                # Clean the resume
                clean_resume_text = clean_resume(resume)
                resume_changed = clean_resume_text != resume
                
                # Clean the keywords
                clean_keywords_text = clean_keywords(keywords)
                keywords_changed = clean_keywords_text != keywords
                
                # Only update if something changed
                if resume_changed or keywords_changed:
                    if args.dry_run:
                        if resume_changed:
                            logger.info(f"Would update resume for {title} (ID: {record_id})")
                            logger.info(f"  Old: {resume[:100]}...")
                            logger.info(f"  New: {clean_resume_text[:100]}...")
                        if keywords_changed:
                            logger.info(f"Would update keywords for {title} (ID: {record_id})")
                            logger.info(f"  Old: {keywords[:100]}...")
                            logger.info(f"  New: {clean_keywords_text[:100]}...")
                    else:
                        success = update_record(conn, record_id, clean_resume_text, clean_keywords_text)
                        if success:
                            if resume_changed:
                                stats["updated_resume"] += 1
                            if keywords_changed:
                                stats["updated_keywords"] += 1
                        else:
                            stats["errors"] += 1
                
                stats["processed"] += 1
                
                # Show progress
                if stats["processed"] % 100 == 0 or stats["processed"] == total_to_process:
                    elapsed = time.time() - start_time
                    records_per_second = stats["processed"] / elapsed if elapsed > 0 else 0
                    remaining = (total_to_process - stats["processed"]) / records_per_second if records_per_second > 0 else 0
                    
                    logger.info(f"Progress: {stats['processed']}/{total_to_process} records "
                                f"({records_per_second:.1f} records/sec, ETA: {remaining/60:.1f} minutes)")
                    logger.info(f"Updates: {stats['updated_resume']} resumes, {stats['updated_keywords']} keywords, {stats['errors']} errors")
            
            # Commit the transaction for this batch
            if not args.dry_run:
                conn.commit()
                
            # Update offset for next batch
            offset += len(batch)
        
        # Final statistics
        logger.info("\nProcessing complete!")
        logger.info(f"Processed {stats['processed']} records")
        logger.info(f"Updated {stats['updated_resume']} resumes and {stats['updated_keywords']} keywords")
        logger.info(f"Encountered {stats['errors']} errors")
        
    except Exception as e:
        logger.error(f"Error in main processing: {e}")
        if not args.dry_run:
            conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
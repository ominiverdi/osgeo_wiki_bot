# db/populate_user_entities.py
#!/usr/bin/env python3
import os
import psycopg2
from pathlib import Path
import logging
from datetime import datetime
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("populate_user_entities.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Whitelist of fields to extract
ENTITY_FIELDS = {
    'name': ('person', 'is_alias_of'),
    'address': ('location', 'lives_at'),
    'city': ('location', 'lives_in_city'),
    'state': ('location', 'lives_in_state'),
    'country': ('location', 'lives_in_country'),
    'company': ('organization', 'works_for'),
    'local_chapter': ('organization', 'member_of'),
}

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
        conn.autocommit = False  # Use transactions
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None

def is_placeholder(value):
    """Check if a value is a placeholder/empty."""
    if not value:
        return True
    if value.startswith('[[') or value.startswith('{{{'):
        return True
    if value in ['Loading map...', 'OSGeo Member']:
        return True
    return False

def parse_user_page(title, chunk_text):
    """Extract fields from user page template."""
    fields = {'username': title.replace('User:', '')}
    lines = chunk_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        if line.endswith(':'):
            field_name = line[:-1].lower().replace(' ', '_').replace('(', '').replace(')', '')
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line.endswith(':') and not is_placeholder(next_line):
                    fields[field_name] = next_line
        i += 1
    
    return fields

def insert_entity(cur, entity_type, entity_name, source_page_id, wiki_url):
    """Insert entity and return its ID."""
    cur.execute("""
        INSERT INTO entities (entity_type, entity_name, source_page_id, wiki_url, confidence)
        VALUES (%s, %s, %s, %s, 1.0)
        ON CONFLICT (entity_name, entity_type) DO UPDATE 
        SET entity_name = EXCLUDED.entity_name
        RETURNING id
    """, (entity_type, entity_name, source_page_id, wiki_url))
    
    entity_id = cur.fetchone()[0]
    return entity_id

def insert_relationship(cur, subject_id, predicate, object_id, source_page_id):
    """Insert relationship between entities."""
    try:
        cur.execute("""
            INSERT INTO entity_relationships (subject_id, predicate, object_id, source_page_id, confidence)
            VALUES (%s, %s, %s, %s, 1.0)
            ON CONFLICT DO NOTHING
        """, (subject_id, predicate, object_id, source_page_id))
        return True
    except Exception as e:
        logger.error(f"Failed to insert relationship: {e}")
        return False

def process_user_page(conn, page_id, title, chunk_text, url):
    """Process a single user page."""
    cur = conn.cursor()
    
    try:
        # Parse template
        fields = parse_user_page(title, chunk_text)
        username = fields.get('username')
        
        if not username:
            logger.warning(f"No username found for {title}")
            return False
        
        # Insert username entity
        username_id = insert_entity(cur, 'person', username, page_id, url)
        logger.debug(f"  Created entity: {username} (id={username_id})")
        
        entities_created = 1
        relationships_created = 0
        
        # Process whitelisted fields
        for field_name, (entity_type, predicate) in ENTITY_FIELDS.items():
            if field_name in fields:
                value = fields[field_name]
                
                # Create entity
                entity_id = insert_entity(cur, entity_type, value, page_id, url)
                entities_created += 1
                logger.debug(f"  Created entity: {value} ({entity_type}, id={entity_id})")
                
                # Create relationship
                if insert_relationship(cur, username_id, predicate, entity_id, page_id):
                    relationships_created += 1
                    logger.debug(f"  Created relationship: {username} | {predicate} | {value}")
        
        conn.commit()
        logger.info(f"✓ {title}: {entities_created} entities, {relationships_created} relationships")
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error(f"✗ Failed to process {title}: {e}")
        return False
    finally:
        cur.close()

def populate_user_entities():
    """Main function to populate user entities."""
    start_time = datetime.now()
    logger.info("=" * 70)
    logger.info("Starting User Entity Population")
    logger.info("=" * 70)
    
    conn = get_db_connection()
    if not conn:
        logger.error("Could not connect to database")
        return
    
    try:
        # Get all user pages
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.title, pc.chunk_text, p.url
            FROM pages p
            JOIN page_chunks pc ON p.id = pc.page_id
            WHERE p.title LIKE 'User:%'
            AND pc.chunk_index = 0
            ORDER BY p.title
        """)
        
        pages = cur.fetchall()
        total_pages = len(pages)
        cur.close()
        
        logger.info(f"Found {total_pages} User: pages to process")
        logger.info("")
        
        # Process each page
        success_count = 0
        error_count = 0
        
        for idx, (page_id, title, chunk_text, url) in enumerate(pages, 1):
            logger.info(f"[{idx}/{total_pages}] Processing {title}")
            
            if process_user_page(conn, page_id, title, chunk_text, url):
                success_count += 1
            else:
                error_count += 1
        
        # Summary
        elapsed = datetime.now() - start_time
        logger.info("")
        logger.info("=" * 70)
        logger.info("SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total pages: {total_pages}")
        logger.info(f"Successful: {success_count}")
        logger.info(f"Errors: {error_count}")
        logger.info(f"Time elapsed: {elapsed}")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    populate_user_entities()
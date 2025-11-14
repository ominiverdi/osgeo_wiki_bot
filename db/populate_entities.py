#!/usr/bin/env python3
# db/populate_entities.py - Extract entities and relationships from wiki pages
import os
import re
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
        logging.FileHandler("populate_entities.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Configuration
OLLAMA_BASE_URL = "http://localhost:8080"
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"
LLM_MODEL = "mistral-small-128k"

MAX_CONTENT_LENGTH = 20000
LLM_TIMEOUT = 300
CHECKPOINT_FILE = "entities_checkpoint.json"
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


async def call_llm(prompt, timeout=LLM_TIMEOUT):
    """Call LLM with timeout handling."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OLLAMA_API_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2048
                }
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
    except asyncio.TimeoutError:
        raise TimeoutError(f"LLM call timed out after {timeout}s")
    except Exception as e:
        raise Exception(f"LLM call failed: {str(e)}")


def extract_year_from_name(entity_name):
    """Extract 4-digit year from entity name."""
    match = re.search(r'\b(19|20)\d{2}\b', entity_name)
    return match.group(0) if match else None


async def extract_entities(title, content):
    """Extract named entities from wiki page."""
    prompt = f"""Extract entities from this OSGeo wiki page: "{title}"

ONLY extract entities explicitly mentioned in the text.

Return ONLY valid JSON:
{{
  "people": ["First Last", "First Last"],
  "projects": ["ProjectName", "ProjectName"],
  "organizations": ["Org Name", "Org Name"],
  "conferences": ["FOSS4G 2022", "Regional Conference 2023"],
  "meetings": ["Board Meeting March 2023", "General Assembly 2022"],
  "sprints": ["Code Sprint 2023", "Developer Sprint 2022"],
  "locations": ["City, Country", "City, Country"]
}}

Rules:
- Extract names exactly as written
- Conferences: FOSS4G events and regional conferences
- Meetings: Board meetings, committee meetings, assemblies
- Sprints: Code sprints, development events
- No explanations, just JSON
- Empty arrays if none found
- Maximum 20 entities per type

Text:
{content[:8000]}

JSON:"""
    
    try:
        response = await call_llm(prompt, timeout=120)
        response = response.replace('```json', '').replace('```', '').strip()
        entities = json.loads(response)
        
        # Validate structure
        required_keys = ['people', 'projects', 'organizations', 'conferences', 
                        'meetings', 'sprints', 'locations']
        if not all(k in entities for k in required_keys):
            raise ValueError("Missing required entity types")
        
        return entities
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}, Response: {response[:200]}")
        return {
            "people": [], "projects": [], "organizations": [], 
            "conferences": [], "meetings": [], "sprints": [], "locations": []
        }
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        return {
            "people": [], "projects": [], "organizations": [], 
            "conferences": [], "meetings": [], "sprints": [], "locations": []
        }


async def extract_relationships(title, content, entities):
    """Extract relationships between entities."""
    all_entities = []
    for entity_type, names in entities.items():
        all_entities.extend(names)
    
    if len(all_entities) < 2:
        return []
    
    prompt = f"""From "{title}", extract relationships between these entities:

Entities: {', '.join(all_entities[:30])}

Format each relationship as:
Subject | predicate | Object

Common predicates:
- is_member_of, works_for
- is_project_of, founded_by
- located_in, happened_in
- contributed_to, created
- organized_by, hosted_by

Return ONLY relationships found in text. One per line.
If none found, return: NONE

Text:
{content[:8000]}

RELATIONSHIPS:"""
    
    try:
        response = await call_llm(prompt, timeout=120)
        if "NONE" in response.upper():
            return []
        
        relationships = []
        for line in response.split('\n'):
            line = line.strip()
            if '|' not in line:
                continue
            
            parts = [p.strip() for p in line.split('|')]
            if len(parts) == 3:
                subject, predicate, obj = parts
                if subject in all_entities and obj in all_entities:
                    relationships.append({
                        "subject": subject,
                        "predicate": predicate.lower().replace(' ', '_'),
                        "object": obj
                    })
        
        return relationships[:50]
        
    except Exception as e:
        logger.error(f"Relationship extraction failed: {e}")
        return []


def get_content_from_dump(wiki_dump_path, url):
    """Get page content from wiki dump file."""
    try:
        for filepath in wiki_dump_path.glob('*'):
            if filepath.name == 'url_map.json':
                continue
            
            with open(filepath, 'r', encoding='utf-8') as f:
                first_line = f.readline()
                if first_line.strip() == f'URL: {url}':
                    f.seek(0)
                    content = f.read()
                    
                    lines = content.split('\n')
                    content_start = 0
                    for i, line in enumerate(lines):
                        if line.strip() == 'Content:':
                            content_start = i + 1
                            break
                    
                    page_content = '\n'.join(lines[content_start:]).strip()
                    
                    if len(page_content) > MAX_CONTENT_LENGTH:
                        page_content = page_content[:MAX_CONTENT_LENGTH]
                    
                    return page_content
        
        return None
        
    except Exception as e:
        logger.error(f"Error reading wiki dump: {e}")
        return None


def store_entity(conn, entity_type, entity_name, page_id, wiki_url):
    """Store entity in database, return entity_id."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO entities (entity_type, entity_name, source_page_id, wiki_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (entity_name, entity_type) 
                DO UPDATE SET source_page_id = EXCLUDED.source_page_id
                RETURNING id
            """, (entity_type, entity_name, page_id, wiki_url))
            
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Error storing entity {entity_name}: {e}")
        return None


def store_relationship(conn, subject_id, predicate, object_id, page_id):
    """Store relationship in database."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO entity_relationships 
                (subject_id, predicate, object_id, source_page_id, confidence)
                VALUES (%s, %s, %s, %s, 1.0)
                ON CONFLICT DO NOTHING
            """, (subject_id, predicate, object_id, page_id))
    except Exception as e:
        logger.error(f"Error storing relationship: {e}")


async def process_page(conn, page_id, title, url):
    """Process a single page for entity extraction."""
    try:
        content = get_content_from_dump(WIKI_DUMP_PATH, url)
        if not content:
            logger.warning(f"  No content found")
            return "no_content"
        
        logger.info(f"  Extracting entities...")
        entities = await extract_entities(title, content)
        
        entity_count = sum(len(v) for v in entities.values())
        if entity_count == 0:
            logger.info(f"  No entities found")
            return "no_entities"
        
        logger.info(f"  Found {entity_count} entities")
        
        # Store entities and build ID map
        entity_ids = {}
        years_to_create = set()
        
        # Map entity types (remove plural 's')
        type_mapping = {
            'people': 'person',
            'projects': 'project',
            'organizations': 'organization',
            'conferences': 'conference',
            'meetings': 'meeting',
            'sprints': 'sprint',
            'locations': 'location'
        }
        
        for entity_type, names in entities.items():
            singular_type = type_mapping.get(entity_type, entity_type)
            
            for name in names:
                entity_id = store_entity(conn, singular_type, name, page_id, url)
                if entity_id:
                    entity_ids[name] = entity_id
                    
                    # Extract year from temporal entities
                    if singular_type in ['conference', 'meeting', 'sprint']:
                        year = extract_year_from_name(name)
                        if year:
                            years_to_create.add((year, name, entity_id))
        
        # Create year entities and relationships
        for year, source_name, source_id in years_to_create:
            year_id = store_entity(conn, 'year', year, page_id, url)
            if year_id:
                store_relationship(conn, source_id, 'happened_in', year_id, page_id)
                logger.info(f"  Created year relationship: {source_name} -> {year}")
        
        # Extract relationships
        logger.info(f"  Extracting relationships...")
        relationships = await extract_relationships(title, content, entities)
        
        if relationships:
            logger.info(f"  Found {len(relationships)} relationships")
            
            for rel in relationships:
                subject_id = entity_ids.get(rel['subject'])
                object_id = entity_ids.get(rel['object'])
                
                if subject_id and object_id:
                    store_relationship(conn, subject_id, rel['predicate'], object_id, page_id)
        
        logger.info(f"  ✓ Saved {entity_count} entities, {len(relationships)} relationships")
        return "success"
        
    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        return "error"


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
            SELECT DISTINCT p.id, p.title, p.url
            FROM pages p
            WHERE p.id > %s
            AND NOT EXISTS (
                SELECT 1 FROM entities e WHERE e.source_page_id = p.id
            )
            ORDER BY p.id
        """
        if limit:
            query += f" LIMIT {limit}"
        
        cur.execute(query, (last_id,))
        return cur.fetchall()


async def main():
    parser = argparse.ArgumentParser(description="Extract entities and relationships from wiki pages")
    parser.add_argument("--limit", type=int, help="Limit number of pages to process")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()
    
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return
    
    create_tables(conn)
    
    checkpoint = load_checkpoint() if args.resume else {"last_id": 0, "processed": 0}
    last_id = checkpoint["last_id"]
    total_processed = checkpoint["processed"]
    
    logger.info("="*70)
    logger.info(f"OSGeo Wiki Entity Extraction")
    logger.info("="*70)
    logger.info(f"Model: {LLM_MODEL}")
    logger.info(f"Entity types: Person, Project, Organization, Conference, Meeting, Sprint, Location, Year")
    logger.info(f"Max content size: {MAX_CONTENT_LENGTH} chars")
    if args.resume:
        logger.info(f"Resuming from ID: {last_id} ({total_processed} already processed)")
    logger.info("="*70 + "\n")
    
    pages = get_pages(conn, last_id, args.limit)
    if not pages:
        logger.info("No pages to process")
        conn.close()
        return
    
    logger.info(f"Found {len(pages)} pages to process\n")
    
    start_time = asyncio.get_event_loop().time()
    for i, (page_id, title, url) in enumerate(pages, 1):
        logger.info(f"[{i}/{len(pages)}] {title}")
        
        result = await process_page(conn, page_id, title, url)
        
        if result == "success":
            total_processed += 1
        
        if i % 10 == 0:
            save_checkpoint(page_id, total_processed)
            elapsed = asyncio.get_event_loop().time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            logger.info(f"  Checkpoint saved. Rate: {rate:.2f} pages/sec\n")
    
    save_checkpoint(pages[-1][0], total_processed)
    
    elapsed = asyncio.get_event_loop().time() - start_time
    logger.info("\n" + "="*70)
    logger.info(f"COMPLETE: {len(pages)} pages in {elapsed/60:.1f} minutes")
    logger.info(f"Total entities extracted: {total_processed}")
    logger.info("="*70)
    
    with conn.cursor() as cur:
        cur.execute("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC")
        logger.info("\nEntity counts by type:")
        for entity_type, count in cur.fetchall():
            logger.info(f"  {entity_type}: {count}")
        
        cur.execute("SELECT COUNT(*) FROM entity_relationships")
        rel_count = cur.fetchone()[0]
        logger.info(f"\nTotal relationships: {rel_count}")
    
    conn.close()


def create_tables(conn):
    """Create entity tables if they don't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id SERIAL PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                source_page_id INTEGER REFERENCES pages(id),
                wiki_url TEXT,
                confidence FLOAT DEFAULT 1.0,
                UNIQUE(entity_name, entity_type)
            );
            
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(entity_name);
            
            CREATE TABLE IF NOT EXISTS entity_relationships (
                id SERIAL PRIMARY KEY,
                subject_id INTEGER REFERENCES entities(id),
                predicate TEXT NOT NULL,
                object_id INTEGER REFERENCES entities(id),
                source_page_id INTEGER REFERENCES pages(id),
                confidence FLOAT DEFAULT 1.0
            );
            
            CREATE INDEX IF NOT EXISTS idx_relationships_subject ON entity_relationships(subject_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_object ON entity_relationships(object_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_predicate ON entity_relationships(predicate);
        """)


if __name__ == "__main__":
    asyncio.run(main())
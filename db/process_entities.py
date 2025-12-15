#!/usr/bin/env python3
"""
Process Entities - Worker for extracting entities and relationships

Picks up 'entities' tasks from the processing queue and extracts
named entities and their relationships using an LLM.
"""

import os
import sys
import re
import json
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
        logging.FileHandler("process_entities.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:8080")
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"
LLM_MODEL = os.getenv("LLM_MODEL", "mistral-small-128k")
MAX_CONTENT_LENGTH = 8000
LLM_TIMEOUT = 120
WIKI_DUMP_PATH = Path(os.getenv("WIKI_DUMP_PATH", "./wiki_dump"))


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


async def call_llm(prompt: str, timeout: int = LLM_TIMEOUT) -> str:
    """Call LLM with timeout handling."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OLLAMA_API_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                },
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
    except asyncio.TimeoutError:
        raise TimeoutError(f"LLM call timed out after {timeout}s")
    except Exception as e:
        raise Exception(f"LLM call failed: {str(e)}")


async def extract_entities(title: str, content: str) -> dict:
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
{content[:MAX_CONTENT_LENGTH]}

JSON:"""

    try:
        response = await call_llm(prompt)
        response = response.replace("```json", "").replace("```", "").strip()
        entities = json.loads(response)

        # Validate structure
        required_keys = [
            "people",
            "projects",
            "organizations",
            "conferences",
            "meetings",
            "sprints",
            "locations",
        ]
        for key in required_keys:
            if key not in entities:
                entities[key] = []

        return entities
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return {
            "people": [],
            "projects": [],
            "organizations": [],
            "conferences": [],
            "meetings": [],
            "sprints": [],
            "locations": [],
        }
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}")
        return {
            "people": [],
            "projects": [],
            "organizations": [],
            "conferences": [],
            "meetings": [],
            "sprints": [],
            "locations": [],
        }


async def extract_relationships(title: str, content: str, entities: dict) -> list[dict]:
    """Extract relationships between entities."""
    all_entities = []
    for entity_type, names in entities.items():
        all_entities.extend(names)

    if len(all_entities) < 2:
        return []

    prompt = f"""From "{title}", extract relationships between these entities:

Entities: {", ".join(all_entities[:30])}

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
{content[:MAX_CONTENT_LENGTH]}

RELATIONSHIPS:"""

    try:
        response = await call_llm(prompt)
        if "NONE" in response.upper():
            return []

        relationships = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    relationships.append(
                        {
                            "subject": parts[0],
                            "predicate": parts[1].lower().replace(" ", "_"),
                            "object": parts[2],
                        }
                    )

        return relationships[:50]
    except Exception as e:
        logger.error(f"Relationship extraction failed: {e}")
        return []


def get_or_create_entity(cur, entity_name: str, entity_type: str) -> int | None:
    """Get or create an entity, return its ID."""
    try:
        cur.execute(
            """
            INSERT INTO entities (entity_type, entity_name)
            VALUES (%s, %s)
            ON CONFLICT (entity_type, entity_name) DO UPDATE SET entity_name = EXCLUDED.entity_name
            RETURNING id
            """,
            (entity_type, entity_name),
        )
        return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Error creating entity {entity_name}: {e}")
        return None


def store_relationship(
    cur, subject_id: int, predicate: str, object_id: int, page_id: int
):
    """Store relationship in database."""
    try:
        cur.execute(
            """
            INSERT INTO entity_relationships (subject_id, predicate, object_id, source_page_id, confidence)
            VALUES (%s, %s, %s, %s, 0.8)
            ON CONFLICT DO NOTHING
            """,
            (subject_id, predicate, object_id, page_id),
        )
    except Exception as e:
        logger.error(f"Error storing relationship: {e}")


def get_page_content(
    conn, page_id: int, source_page_id: int | None = None
) -> tuple[str, str, str] | None:
    """Get page content from source_pages table (source of truth)."""
    with conn.cursor() as cur:
        # First try to get from source_pages using source_page_id
        if source_page_id:
            cur.execute(
                "SELECT title, url, content_text FROM source_pages WHERE id = %s",
                (source_page_id,),
            )
            result = cur.fetchone()
            if result and result[2]:
                return result[0], result[1], result[2]

        # Fallback: get from source_pages via pages.url join
        cur.execute(
            """
            SELECT sp.title, sp.url, sp.content_text 
            FROM source_pages sp
            JOIN pages p ON sp.url = p.url
            WHERE p.id = %s
            """,
            (page_id,),
        )
        result = cur.fetchone()
        if result and result[2]:
            return result[0], result[1], result[2]

        # Last fallback: just get title/url from pages
        cur.execute("SELECT title, url FROM pages WHERE id = %s", (page_id,))
        result = cur.fetchone()
        if result:
            logger.warning(
                f"No content in source_pages for page {page_id}: {result[0]}"
            )
            return result[0], result[1], ""

        return None


# Entity type mapping
ENTITY_TYPE_MAP = {
    "people": "person",
    "projects": "project",
    "organizations": "organization",
    "conferences": "event",
    "meetings": "event",
    "sprints": "event",
    "locations": "location",
}


async def process_entities_task(conn, queue_id: int, page_id: int) -> bool:
    """
    Process a single entities task.

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get page content
        result = get_page_content(conn, page_id)
        if not result:
            raise ValueError(f"Page {page_id} not found")

        title, url, content = result

        if not content:
            logger.warning(f"Empty content for page {page_id}: {title}")
            return True

        # Extract entities
        logger.info(f"  Extracting entities from {title}...")
        entities = await extract_entities(title, content)

        # Count entities
        total_entities = sum(len(v) for v in entities.values())
        if total_entities == 0:
            logger.info(f"  No entities found in {title}")
            return True

        # Extract relationships
        logger.info(f"  Extracting relationships from {title}...")
        relationships = await extract_relationships(title, content, entities)

        # Store entities and relationships
        with conn.cursor() as cur:
            entities_created = 0
            relationships_created = 0

            # Create entities
            entity_ids = {}  # name -> id mapping
            for entity_type_plural, names in entities.items():
                entity_type = ENTITY_TYPE_MAP.get(entity_type_plural)
                if not entity_type:
                    entity_type = entity_type_plural  # fallback to plural form
                for name in names:
                    if name and len(name) > 1:
                        entity_id = get_or_create_entity(cur, name, entity_type)
                        if entity_id:
                            entity_ids[name] = entity_id
                            entities_created += 1

            # Create relationships
            for rel in relationships:
                subject_name = rel["subject"]
                object_name = rel["object"]
                predicate = rel["predicate"]

                subject_id = entity_ids.get(subject_name)
                object_id = entity_ids.get(object_name)

                if subject_id and object_id:
                    store_relationship(cur, subject_id, predicate, object_id, page_id)
                    relationships_created += 1

            conn.commit()

            logger.info(
                f"Processed page {page_id} ({title}): "
                f"{entities_created} entities, {relationships_created} relationships"
            )

        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing entities for page {page_id}: {e}")
        raise


def claim_and_process_task(conn) -> bool:
    """
    Claim and process a single task.

    Returns:
        True if a task was processed, False if no tasks available
    """
    with conn.cursor() as cur:
        # Claim next task
        cur.execute("SELECT * FROM claim_task('entities')")
        result = cur.fetchone()

        if not result:
            return False

        queue_id, page_id, source_page_id, attempts = result
        logger.info(f"Claimed task {queue_id} for page {page_id} (attempt {attempts})")

        try:
            success = asyncio.run(process_entities_task(conn, queue_id, page_id))
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
    stats = {"processed": 0, "succeeded": 0, "failed": 0}

    for _ in range(limit):
        try:
            if not claim_and_process_task(conn):
                break
            stats["processed"] += 1
            stats["succeeded"] += 1
        except Exception:
            stats["processed"] += 1
            stats["failed"] += 1

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process entities tasks from queue")
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

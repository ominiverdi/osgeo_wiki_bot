#!/usr/bin/env python3
"""
Planet OSGeo Sync - Fetch blog posts from Planet OSGeo RSS/Atom feed

Planet OSGeo (https://planet.osgeo.org/) aggregates blog posts from
100+ OSGeo community members and projects. This script syncs those
posts into our knowledge base.

Stores content in source_pages and queues tasks for processing.
"""

import os
import sys
import hashlib
import logging
import re
import requests
import psycopg2
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional
from html.parser import HTMLParser
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
PLANET_RSS_URL = "https://planet.osgeo.org/rss20.xml"
PLANET_ATOM_URL = "https://planet.osgeo.org/atom.xml"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# Namespaces for Atom parsing
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


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


def html_to_text(html: str) -> str:
    """Convert HTML to plain text, preserving structure."""

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []
            self.in_script = False
            self.in_style = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.in_script = True
            elif tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
                self.text.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.in_script = False
            elif tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
                self.text.append("\n")

        def handle_data(self, data):
            if not self.in_script and not self.in_style:
                self.text.append(data)

    parser = TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        # If HTML parsing fails, return as-is
        return html
    text = "".join(parser.text)
    # Clean up multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse RSS date string to datetime."""
    # Try common RSS date formats
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",  # RFC 822
        "%a, %d %b %Y %H:%M:%S %Z",  # RFC 822 with timezone name
        "%Y-%m-%dT%H:%M:%S%z",  # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 UTC
        "%Y-%m-%d %H:%M:%S",  # Simple format
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Try parsing without timezone
    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    logger.warning(f"Could not parse date: {date_str}")
    return None


class PlanetSyncClient:
    """Client for syncing Planet OSGeo content."""

    def __init__(self, db_connection=None):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "OSGeoWikiBot/1.0 (https://github.com/osgeo/wiki_bot)"}
        )
        self.db = db_connection

    def fetch_feed(self) -> Optional[str]:
        """Fetch the RSS feed XML."""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(PLANET_RSS_URL, timeout=60)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                logger.warning(
                    f"Failed to fetch feed (attempt {attempt + 1}/{MAX_RETRIES}): {e}"
                )
                if attempt < MAX_RETRIES - 1:
                    import time

                    time.sleep(RETRY_DELAY * (attempt + 1))
        return None

    def parse_rss_feed(self, xml_content: str) -> list[dict]:
        """
        Parse RSS 2.0 feed and extract entries.

        Returns list of dicts with:
        - id: Unique identifier (guid)
        - title: Post title
        - link: URL to original post
        - content: HTML content
        - published: Publication date
        - author: Author name
        - source_blog: Name of the source blog
        - source_url: URL of the source blog
        """
        entries = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML: {e}")
            return entries

        channel = root.find("channel")
        if channel is None:
            logger.error("No channel element found in RSS feed")
            return entries

        for item in channel.findall("item"):
            try:
                # Get basic fields
                guid = item.findtext("guid", "")
                title = item.findtext("title", "")
                link = item.findtext("link", "")

                # Get content - try description first
                content = item.findtext("description", "")

                # Get publication date
                pub_date_str = item.findtext("pubDate", "")
                pub_date = parse_rss_date(pub_date_str) if pub_date_str else None

                # Extract source blog from title (format: "Blog Name: Post Title")
                source_blog = ""
                if ": " in title:
                    parts = title.split(": ", 1)
                    if len(parts) == 2:
                        source_blog = parts[0]
                        # Keep the full title for searchability

                # Skip if no content
                if not content or len(content.strip()) < 50:
                    logger.debug(f"Skipping {title}: insufficient content")
                    continue

                entries.append(
                    {
                        "id": guid,
                        "title": title,
                        "link": link,
                        "content": content,
                        "published": pub_date,
                        "source_blog": source_blog,
                    }
                )

            except Exception as e:
                logger.warning(f"Error parsing item: {e}")
                continue

        return entries

    def compute_content_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def sync(
        self,
        modified_after: Optional[datetime] = None,
        dry_run: bool = False,
        max_entries: Optional[int] = None,
    ) -> dict:
        """
        Run sync from Planet OSGeo.

        Args:
            modified_after: Only sync entries published after this date
            dry_run: If True, don't actually update database
            max_entries: Maximum number of entries to process (for testing)

        Returns:
            Dict with sync statistics
        """
        stats = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "entries_fetched": 0,
            "entries_created": 0,
            "entries_updated": 0,
            "entries_skipped": 0,
            "tasks_queued": 0,
            "errors": [],
        }

        # Fetch feed
        logger.info(f"Fetching Planet OSGeo feed from {PLANET_RSS_URL}")
        xml_content = self.fetch_feed()
        if not xml_content:
            logger.error("Failed to fetch feed")
            stats["errors"].append("Failed to fetch RSS feed")
            stats["completed_at"] = datetime.now(timezone.utc).isoformat()
            return stats

        # Parse feed
        entries = self.parse_rss_feed(xml_content)
        stats["entries_fetched"] = len(entries)
        logger.info(f"Parsed {len(entries)} entries from feed")

        if not entries:
            logger.info("No entries to process")
            stats["completed_at"] = datetime.now(timezone.utc).isoformat()
            return stats

        # Filter by date if specified
        if modified_after:
            original_count = len(entries)
            entries = [
                e
                for e in entries
                if e.get("published") and e["published"] >= modified_after
            ]
            logger.info(
                f"Filtered to {len(entries)} entries after {modified_after.isoformat()} "
                f"(from {original_count})"
            )

        # Limit entries if specified
        if max_entries and len(entries) > max_entries:
            entries = entries[:max_entries]
            logger.info(f"Limited to {max_entries} entries")

        # Process each entry
        for entry in entries:
            try:
                entry_id = entry["id"]
                title = entry["title"]
                link = entry["link"]
                html_content = entry["content"]
                source_blog = entry.get("source_blog", "")

                logger.info(f"Processing: {title[:60]}...")

                if dry_run:
                    logger.info(f"  [DRY RUN] Would sync: {title[:60]}")
                    stats["entries_updated"] += 1
                    continue

                # Convert HTML to text
                text_content = html_to_text(html_content)

                # Check if we already have this version
                content_hash = self.compute_content_hash(text_content)
                stored_hash = self._get_stored_hash(entry_id)

                if stored_hash == content_hash:
                    logger.debug(f"  Skipping (content unchanged)")
                    stats["entries_skipped"] += 1
                    continue

                is_new = stored_hash is None

                # Update database
                tasks_queued = self._update_entry(
                    entry_id=entry_id,
                    title=title,
                    url=link,
                    html_content=html_content,
                    text_content=text_content,
                    content_hash=content_hash,
                    source_blog=source_blog,
                    published=entry.get("published"),
                )
                stats["tasks_queued"] += tasks_queued

                if is_new:
                    stats["entries_created"] += 1
                else:
                    stats["entries_updated"] += 1

            except Exception as e:
                title = entry.get("title", entry.get("id", "unknown"))
                logger.error(f"Error processing {title}: {e}")
                stats["errors"].append(f"{title[:50]}: {str(e)}")

        stats["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"Sync complete: {stats['entries_created']} created, "
            f"{stats['entries_updated']} updated, {stats['entries_skipped']} skipped, "
            f"{stats['tasks_queued']} tasks queued"
        )

        return stats

    def _get_stored_hash(self, entry_id: str) -> Optional[str]:
        """Get stored content hash for a Planet entry."""
        if self.db is None:
            return None

        try:
            with self.db.cursor() as cur:
                cur.execute(
                    """
                    SELECT content_hash FROM source_pages
                    WHERE source_type = 'planet_post' AND source_id = %s
                    """,
                    (entry_id,),
                )
                result = cur.fetchone()
                return result[0] if result else None
        except psycopg2.Error as e:
            logger.error(f"Error getting stored hash: {e}")
            return None

    def _update_entry(
        self,
        entry_id: str,
        title: str,
        url: str,
        html_content: str,
        text_content: str,
        content_hash: str,
        source_blog: str,
        published: Optional[datetime],
    ) -> int:
        """
        Update entry in database and queue processing tasks.

        Returns:
            Number of tasks queued
        """
        if self.db is None:
            logger.warning("No database connection, skipping database update")
            return 0

        tasks_queued = 0

        try:
            with self.db.cursor() as cur:
                # 1. Upsert into pages table (lightweight reference)
                cur.execute(
                    """
                    INSERT INTO pages (title, url)
                    VALUES (%s, %s)
                    ON CONFLICT (url) DO UPDATE SET
                        title = EXCLUDED.title,
                        last_crawled = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (title, url),
                )
                pages_table_id = cur.fetchone()[0]

                # 2. Upsert into source_pages with full content
                # Note: source_id is the guid from the RSS feed (string)
                cur.execute(
                    """
                    INSERT INTO source_pages (
                        source_type, source_id, title, url,
                        content_hash, content_text, content_html, last_synced
                    )
                    VALUES ('planet_post', %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (source_type, source_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        url = EXCLUDED.url,
                        content_hash = EXCLUDED.content_hash,
                        content_text = EXCLUDED.content_text,
                        content_html = EXCLUDED.content_html,
                        last_synced = CURRENT_TIMESTAMP,
                        status = 'active'
                    RETURNING id
                    """,
                    (
                        entry_id,
                        title,
                        url,
                        content_hash,
                        text_content,
                        html_content,
                    ),
                )
                source_page_id = cur.fetchone()[0]

                # 3. Queue processing tasks
                for task_type in ["chunks", "extensions"]:
                    cur.execute(
                        "SELECT queue_task(%s, %s, %s, %s)",
                        (pages_table_id, source_page_id, task_type, 0),
                    )
                    queue_id = cur.fetchone()[0]
                    if queue_id:
                        tasks_queued += 1
                        logger.debug(f"  Queued {task_type} task (id={queue_id})")

                self.db.commit()

                logger.info(
                    f"  Updated (hash={content_hash[:8]}..., blog={source_blog[:20] if source_blog else 'N/A'}, tasks={tasks_queued})"
                )

        except psycopg2.Error as e:
            self.db.rollback()
            logger.error(f"Database error: {e}")
            raise

        return tasks_queued

    def prune_old_entries(self, days: int, dry_run: bool = False) -> int:
        """
        Remove planet_post entries older than specified days.

        This keeps the database from growing indefinitely with old blog posts.
        Cascading deletes will remove associated chunks and extensions.

        Args:
            days: Remove entries not synced in this many days
            dry_run: If True, just count without deleting

        Returns:
            Number of entries deleted (or would be deleted in dry run)
        """
        if self.db is None:
            logger.warning("No database connection, cannot prune")
            return 0

        try:
            with self.db.cursor() as cur:
                if dry_run:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM source_pages
                        WHERE source_type = 'planet_post'
                        AND last_synced < NOW() - INTERVAL '%s days'
                        """,
                        (days,),
                    )
                    count = cur.fetchone()[0]
                    logger.info(
                        f"[DRY RUN] Would prune {count} entries older than {days} days"
                    )
                    return count
                else:
                    # First get the IDs to delete from pages table too
                    cur.execute(
                        """
                        DELETE FROM source_pages
                        WHERE source_type = 'planet_post'
                        AND last_synced < NOW() - INTERVAL '%s days'
                        RETURNING id, title
                        """,
                        (days,),
                    )
                    deleted = cur.fetchall()
                    count = len(deleted)

                    if count > 0:
                        self.db.commit()
                        logger.info(f"Pruned {count} entries older than {days} days")
                        for row in deleted[:5]:
                            logger.debug(f"  Deleted: {row[1][:50]}...")

                    return count

        except psycopg2.Error as e:
            self.db.rollback()
            logger.error(f"Error pruning old entries: {e}")
            return 0


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Sync Planet OSGeo blog posts")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Fetch posts from last N days (default: 30)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Sync all entries in the feed (no date filter)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Maximum number of entries to process (for testing)",
    )
    parser.add_argument(
        "--prune-days",
        type=int,
        default=60,
        help="Remove entries older than N days (default: 60, 0 to disable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without making changes",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize database connection
    db = get_db_connection()
    if db is None and not args.dry_run:
        logger.warning("No database connection, running in dry-run mode")
        args.dry_run = True

    # Create client and run sync
    client = PlanetSyncClient(db_connection=db)

    if args.all:
        stats = client.sync(dry_run=args.dry_run, max_entries=args.max)
    else:
        modified_after = datetime.now(timezone.utc) - timedelta(days=args.days)
        stats = client.sync(
            modified_after=modified_after,
            dry_run=args.dry_run,
            max_entries=args.max,
        )

    # Prune old entries (after sync, so we don't delete then re-add)
    pruned = 0
    if args.prune_days > 0:
        pruned = client.prune_old_entries(args.prune_days, dry_run=args.dry_run)

    # Print summary
    print(f"\nSync Summary:")
    print(f"  Entries fetched: {stats['entries_fetched']}")
    print(f"  Entries created: {stats['entries_created']}")
    print(f"  Entries updated: {stats['entries_updated']}")
    print(f"  Entries skipped: {stats['entries_skipped']}")
    print(f"  Tasks queued:    {stats['tasks_queued']}")
    print(f"  Entries pruned:  {pruned}")
    if stats["errors"]:
        print(f"  Errors: {len(stats['errors'])}")
        for err in stats["errors"][:5]:
            print(f"    - {err}")

    if db:
        db.close()


if __name__ == "__main__":
    main()

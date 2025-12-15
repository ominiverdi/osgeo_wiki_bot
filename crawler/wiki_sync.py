#!/usr/bin/env python3
"""
Wiki Sync - Incremental update from OSGeo MediaWiki

Uses the MediaWiki recentchanges API to detect and sync only modified pages.
Tracks revision IDs to avoid duplicate processing.
Queues tasks for async processing (chunks, extensions, entities).
"""

import os
import sys
import json
import hashlib
import logging
import re
import requests
import psycopg2
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass
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
WIKI_API_URL = "https://wiki.osgeo.org/w/api.php"
WIKI_BASE_URL = "https://wiki.osgeo.org/wiki/"
DEFAULT_LIMIT = 50
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
WIKI_DUMP_PATH = Path(os.getenv("WIKI_DUMP_PATH", "./wiki_dump"))


@dataclass
class PageChange:
    """Represents a page change from recentchanges API"""

    pageid: int
    title: str
    revid: int
    old_revid: int
    timestamp: str
    user: str
    comment: str = ""


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


def sanitize_filename(title: str) -> str:
    """Convert page title to safe filename."""
    # Replace problematic characters
    safe = re.sub(r'[<>:"/\\|?*]', "_", title)
    safe = re.sub(r"\s+", "_", safe)
    return safe[:200]  # Limit length


def html_to_text(html: str) -> str:
    """Convert HTML to plain text, preserving structure."""
    from html.parser import HTMLParser

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
    parser.feed(html)
    text = "".join(parser.text)
    # Clean up multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class WikiSyncClient:
    """Client for syncing wiki changes"""

    def __init__(self, db_connection=None):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "OSGeoWikiBot/1.0 (https://github.com/osgeo/wiki_bot)"}
        )
        self.db = db_connection

    def fetch_recent_changes(
        self, since: Optional[datetime] = None, limit: int = DEFAULT_LIMIT
    ) -> list[PageChange]:
        """
        Fetch recent changes from MediaWiki API

        Args:
            since: Only fetch changes after this timestamp
            limit: Maximum number of results

        Returns:
            List of PageChange objects
        """
        params = {
            "action": "query",
            "list": "recentchanges",
            "rcprop": "title|timestamp|ids|user|comment",
            "rclimit": limit,
            "rctype": "edit|new",  # Only edits and new pages, not logs
            "rcnamespace": 0,  # Main namespace only
            "format": "json",
        }

        if since:
            # rcend is the older boundary (confusingly named)
            params["rcend"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        changes = []
        continue_token = None

        while True:
            if continue_token:
                params["rccontinue"] = continue_token

            response = self._api_request(params)
            if not response:
                break

            for rc in response.get("query", {}).get("recentchanges", []):
                changes.append(
                    PageChange(
                        pageid=rc["pageid"],
                        title=rc["title"],
                        revid=rc["revid"],
                        old_revid=rc.get("old_revid", 0),
                        timestamp=rc["timestamp"],
                        user=rc.get("user", ""),
                        comment=rc.get("comment", ""),
                    )
                )

            # Check for more results
            if "continue" in response:
                continue_token = response["continue"].get("rccontinue")
            else:
                break

        return changes

    def deduplicate_changes(self, changes: list[PageChange]) -> dict[int, PageChange]:
        """
        Deduplicate changes, keeping only the latest revision per page

        Args:
            changes: List of all changes

        Returns:
            Dict mapping pageid to latest PageChange
        """
        latest_by_page = {}

        for change in changes:
            pageid = change.pageid
            if (
                pageid not in latest_by_page
                or change.revid > latest_by_page[pageid].revid
            ):
                latest_by_page[pageid] = change

        logger.info(
            f"Deduplicated {len(changes)} changes to {len(latest_by_page)} unique pages"
        )
        return latest_by_page

    def filter_already_processed(
        self, changes: dict[int, PageChange]
    ) -> list[PageChange]:
        """
        Filter out pages we've already processed at this revision

        Args:
            changes: Dict of pageid -> PageChange

        Returns:
            List of PageChange that need processing
        """
        to_update = []

        for pageid, change in changes.items():
            stored_revid = self._get_stored_revid(pageid)

            if stored_revid is None:
                logger.debug(f"New page: {change.title} (pageid={pageid})")
                to_update.append(change)
            elif change.revid > stored_revid:
                logger.debug(
                    f"Updated page: {change.title} (revid {stored_revid} -> {change.revid})"
                )
                to_update.append(change)
            else:
                logger.debug(
                    f"Skipping {change.title} (revid {change.revid} already processed)"
                )

        logger.info(f"Filtered to {len(to_update)} pages needing update")
        return to_update

    def fetch_page_content(self, title: str) -> Optional[dict]:
        """
        Fetch full page content from MediaWiki API

        Args:
            title: Page title

        Returns:
            Dict with page content and metadata, or None on error
        """
        params = {
            "action": "parse",
            "page": title,
            "prop": "text|categories|revid",
            "format": "json",
        }

        response = self._api_request(params)
        if not response or "parse" not in response:
            return None

        parse = response["parse"]
        html_content = parse.get("text", {}).get("*", "")

        return {
            "title": parse.get("title", title),
            "revid": parse.get("revid"),
            "html": html_content,
            "text": html_to_text(html_content),
            "categories": [c["*"] for c in parse.get("categories", [])],
        }

    def compute_content_hash(self, content: str) -> str:
        """Compute SHA256 hash of content"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def sync(self, since: Optional[datetime] = None, dry_run: bool = False) -> dict:
        """
        Run incremental sync

        Args:
            since: Only sync changes after this timestamp (default: last 24 hours)
            dry_run: If True, don't actually update database

        Returns:
            Dict with sync statistics
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=1)

        logger.info(f"Starting sync for changes since {since.isoformat()}")

        stats = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "since": since.isoformat(),
            "pages_checked": 0,
            "pages_updated": 0,
            "pages_created": 0,
            "pages_skipped": 0,
            "tasks_queued": 0,
            "errors": [],
        }

        # 1. Fetch recent changes
        changes = self.fetch_recent_changes(since=since)
        stats["pages_checked"] = len(changes)

        if not changes:
            logger.info("No changes found")
            stats["completed_at"] = datetime.now(timezone.utc).isoformat()
            return stats

        # 2. Deduplicate
        unique_changes = self.deduplicate_changes(changes)

        # 3. Filter already processed
        to_update = self.filter_already_processed(unique_changes)
        stats["pages_skipped"] = len(unique_changes) - len(to_update)

        if not to_update:
            logger.info("All pages already up to date")
            stats["completed_at"] = datetime.now(timezone.utc).isoformat()
            return stats

        # 4. Process each page
        for change in to_update:
            try:
                logger.info(f"Processing: {change.title}")

                if dry_run:
                    logger.info(f"  [DRY RUN] Would update {change.title}")
                    stats["pages_updated"] += 1
                    continue

                # Fetch full content
                page_data = self.fetch_page_content(change.title)
                if not page_data:
                    stats["errors"].append(
                        f"Failed to fetch content for {change.title}"
                    )
                    continue

                # Check if this is new or update
                is_new = self._get_stored_revid(change.pageid) is None

                # Update database and queue tasks
                tasks_queued = self._update_page(change, page_data)
                stats["tasks_queued"] += tasks_queued

                if is_new:
                    stats["pages_created"] += 1
                else:
                    stats["pages_updated"] += 1

            except Exception as e:
                logger.error(f"Error processing {change.title}: {e}")
                stats["errors"].append(f"{change.title}: {str(e)}")

        stats["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"Sync complete: {stats['pages_created']} created, "
            f"{stats['pages_updated']} updated, {stats['tasks_queued']} tasks queued"
        )

        return stats

    def _api_request(self, params: dict, retries: int = MAX_RETRIES) -> Optional[dict]:
        """Make API request with retry logic"""
        for attempt in range(retries):
            try:
                response = self.session.get(WIKI_API_URL, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                logger.warning(
                    f"API request failed (attempt {attempt + 1}/{retries}): {e}"
                )
                if attempt < retries - 1:
                    import time

                    time.sleep(RETRY_DELAY * (attempt + 1))
        return None

    def _get_stored_revid(self, pageid: int) -> Optional[int]:
        """Get the last processed revision ID for a page."""
        if self.db is None:
            return None

        try:
            with self.db.cursor() as cur:
                cur.execute(
                    """
                    SELECT last_revid FROM source_pages
                    WHERE source_type = 'wiki' AND source_id = %s
                    """,
                    (pageid,),
                )
                result = cur.fetchone()
                return result[0] if result else None
        except psycopg2.Error as e:
            logger.error(f"Error getting stored revid: {e}")
            return None

    def _save_to_wiki_dump(self, change: PageChange, page_data: dict):
        """Save page content to wiki_dump directory (for compatibility with existing scripts)."""
        WIKI_DUMP_PATH.mkdir(parents=True, exist_ok=True)

        filename = sanitize_filename(change.title)
        filepath = WIKI_DUMP_PATH / filename

        # Format similar to existing crawler output
        content = f"""URL: {WIKI_BASE_URL}{change.title.replace(" ", "_")}
Title: {page_data["title"]}

Categories:
{chr(10).join("- " + c for c in page_data["categories"])}

Content:
{page_data["text"]}
"""
        filepath.write_text(content, encoding="utf-8")
        logger.debug(f"  Saved to {filepath}")

    def _update_page(self, change: PageChange, page_data: dict) -> int:
        """
        Update page in database and queue processing tasks.

        Stores full content in source_pages table (source of truth for all processing).

        Returns:
            Number of tasks queued
        """
        content_hash = self.compute_content_hash(page_data["text"])
        url = f"{WIKI_BASE_URL}{change.title.replace(' ', '_')}"

        # Optionally save to wiki_dump for compatibility with legacy scripts
        if WIKI_DUMP_PATH.exists():
            self._save_to_wiki_dump(change, page_data)

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
                    (page_data["title"], url),
                )
                page_id = cur.fetchone()[0]

                # 2. Upsert into source_pages with full content
                # This is the source of truth - stores latest version of every page
                cur.execute(
                    """
                    INSERT INTO source_pages (
                        source_type, source_id, title, url, last_revid, 
                        content_hash, content_text, content_html, categories, last_synced
                    )
                    VALUES ('wiki', %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (source_type, source_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        url = EXCLUDED.url,
                        last_revid = EXCLUDED.last_revid,
                        content_hash = EXCLUDED.content_hash,
                        content_text = EXCLUDED.content_text,
                        content_html = EXCLUDED.content_html,
                        categories = EXCLUDED.categories,
                        last_synced = CURRENT_TIMESTAMP,
                        status = 'active'
                    RETURNING id
                    """,
                    (
                        change.pageid,
                        page_data["title"],
                        url,
                        change.revid,
                        content_hash,
                        page_data["text"],
                        page_data["html"],
                        page_data["categories"],
                    ),
                )
                source_page_id = cur.fetchone()[0]

                # 3. Queue processing tasks (uses function that avoids duplicates)
                # Note: entities disabled until smarter extraction is implemented
                for task_type in ["chunks", "extensions"]:
                    cur.execute(
                        "SELECT queue_task(%s, %s, %s, %s)",
                        (page_id, source_page_id, task_type, 0),
                    )
                    queue_id = cur.fetchone()[0]
                    if queue_id:
                        tasks_queued += 1
                        logger.debug(f"  Queued {task_type} task (id={queue_id})")

                self.db.commit()

                logger.info(
                    f"  Updated {change.title} (revid={change.revid}, "
                    f"hash={content_hash[:8]}..., tasks={tasks_queued})"
                )

        except psycopg2.Error as e:
            self.db.rollback()
            logger.error(f"Database error updating {change.title}: {e}")
            raise

        return tasks_queued


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Sync OSGeo Wiki changes")
    parser.add_argument(
        "--since", type=str, help="ISO timestamp to sync from (default: 24h ago)"
    )
    parser.add_argument(
        "--days", type=int, default=1, help="Number of days to look back (default: 1)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine sync start time
    if args.since:
        since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    else:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    # Initialize database connection
    db = get_db_connection()
    if db is None and not args.dry_run:
        logger.warning("No database connection, running in dry-run mode")
        args.dry_run = True

    client = WikiSyncClient(db_connection=db)
    stats = client.sync(since=since, dry_run=args.dry_run)

    print("\nSync Statistics:")
    print(json.dumps(stats, indent=2))

    if db:
        db.close()


if __name__ == "__main__":
    main()

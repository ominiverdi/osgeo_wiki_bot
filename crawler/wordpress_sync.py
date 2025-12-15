#!/usr/bin/env python3
"""
WordPress Sync - Fetch pages from OSGeo WordPress site

Uses WordPress REST API to get page list and metadata, then scrapes
the actual HTML content from each page's <main> tag to capture
dynamically generated content (shortcodes, templates, etc.).

Stores content in source_pages and queues tasks for processing.
"""

import os
import sys
import hashlib
import logging
import re
import requests
import psycopg2
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
WP_API_URL = "https://www.osgeo.org/wp-json/wp/v2"
WP_BASE_URL = "https://www.osgeo.org"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
REQUEST_DELAY = 1  # seconds between requests to be nice to the server


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
    parser.feed(html)
    text = "".join(parser.text)
    # Clean up multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_main_content(html: str) -> Optional[str]:
    """
    Extract content from <main> tag in HTML.

    Returns the inner HTML of the <main> tag, or None if not found.
    """
    # Find <main ...> tag and extract content until </main>
    main_match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    if main_match:
        return main_match.group(1)
    return None


class WordPressSyncClient:
    """Client for syncing WordPress content."""

    def __init__(self, db_connection=None):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "OSGeoWikiBot/1.0 (https://github.com/osgeo/wiki_bot)"}
        )
        self.db = db_connection

    def get_total_pages(self) -> int:
        """Get total number of pages from WordPress."""
        try:
            response = self.session.head(
                f"{WP_API_URL}/pages", params={"per_page": 1}, timeout=30
            )
            response.raise_for_status()
            return int(response.headers.get("X-WP-Total", 0))
        except requests.RequestException as e:
            logger.error(f"Failed to get total pages: {e}")
            return 0

    def fetch_pages(
        self,
        per_page: int = 100,
        modified_after: Optional[datetime] = None,
    ) -> list[dict]:
        """
        Fetch pages from WordPress REST API.

        Args:
            per_page: Number of pages per request (max 100)
            modified_after: Only fetch pages modified after this date

        Returns:
            List of page data dicts
        """
        all_pages = []
        page_num = 1

        # Fields to request - we only need metadata, content comes from HTML scrape
        fields = "id,title,link,modified,date,slug,status"

        while True:
            params = {
                "per_page": min(per_page, 100),
                "page": page_num,
                "_fields": fields,
                "status": "publish",  # Only published pages
            }

            if modified_after:
                params["modified_after"] = modified_after.strftime("%Y-%m-%dT%H:%M:%S")

            response = self._api_request(f"{WP_API_URL}/pages", params)
            if not response:
                break

            pages = response
            if not pages:
                break

            all_pages.extend(pages)
            logger.info(
                f"Fetched page {page_num} ({len(pages)} pages, total: {len(all_pages)})"
            )

            # Check if there are more pages
            if len(pages) < per_page:
                break

            page_num += 1

            # Be nice to the server
            import time

            time.sleep(REQUEST_DELAY)

        return all_pages

    def compute_content_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def fetch_page_html(self, url: str) -> Optional[str]:
        """
        Fetch the full HTML of a page and extract <main> content.

        Args:
            url: Page URL to fetch

        Returns:
            HTML content from <main> tag, or None on error
        """
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()

            main_content = extract_main_content(response.text)
            if main_content:
                return main_content
            else:
                logger.warning(f"No <main> tag found in {url}")
                return None

        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def sync(
        self,
        modified_after: Optional[datetime] = None,
        dry_run: bool = False,
        full_sync: bool = False,
    ) -> dict:
        """
        Run sync from WordPress.

        Args:
            modified_after: Only sync pages modified after this date
            dry_run: If True, don't actually update database
            full_sync: If True, fetch all pages regardless of modified date

        Returns:
            Dict with sync statistics
        """
        stats = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pages_fetched": 0,
            "pages_created": 0,
            "pages_updated": 0,
            "pages_skipped": 0,
            "tasks_queued": 0,
            "errors": [],
        }

        # Get total count
        total_pages = self.get_total_pages()
        logger.info(f"WordPress has {total_pages} published pages")

        # Fetch pages
        if full_sync:
            logger.info("Running full sync (all pages)")
            pages = self.fetch_pages()
        elif modified_after:
            logger.info(f"Fetching pages modified after {modified_after.isoformat()}")
            pages = self.fetch_pages(modified_after=modified_after)
        else:
            # Default: last 7 days
            modified_after = datetime.now(timezone.utc) - timedelta(days=7)
            logger.info(f"Fetching pages modified after {modified_after.isoformat()}")
            pages = self.fetch_pages(modified_after=modified_after)

        stats["pages_fetched"] = len(pages)
        logger.info(f"Fetched {len(pages)} pages")

        if not pages:
            logger.info("No pages to process")
            stats["completed_at"] = datetime.now(timezone.utc).isoformat()
            return stats

        # Process each page
        for page in pages:
            try:
                page_id = page["id"]
                title = page["title"]["rendered"]
                url = page["link"]
                modified = page["modified"]

                logger.info(f"Processing: {title}")

                if dry_run:
                    logger.info(f"  [DRY RUN] Would sync {title}")
                    stats["pages_updated"] += 1
                    continue

                # Fetch actual page HTML and extract <main> content
                # This captures dynamically generated content from shortcodes/templates
                html_content = self.fetch_page_html(url)

                if not html_content:
                    logger.warning(f"  No content extracted for {title}")
                    stats["errors"].append(f"{title}: No <main> content found")
                    continue

                text_content = html_to_text(html_content)

                # Be nice to the server
                import time

                time.sleep(REQUEST_DELAY)

                # Check if we already have this version
                content_hash = self.compute_content_hash(text_content)
                stored_hash = self._get_stored_hash(page_id)

                if stored_hash == content_hash:
                    logger.debug(f"  Skipping {title} (content unchanged)")
                    stats["pages_skipped"] += 1
                    continue

                is_new = stored_hash is None

                # Update database
                tasks_queued = self._update_page(
                    page_id=page_id,
                    title=title,
                    url=url,
                    html_content=html_content,
                    text_content=text_content,
                    content_hash=content_hash,
                    modified=modified,
                )
                stats["tasks_queued"] += tasks_queued

                if is_new:
                    stats["pages_created"] += 1
                else:
                    stats["pages_updated"] += 1

            except Exception as e:
                title = page.get("title", {}).get("rendered", f"ID:{page.get('id')}")
                logger.error(f"Error processing {title}: {e}")
                stats["errors"].append(f"{title}: {str(e)}")

        stats["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"Sync complete: {stats['pages_created']} created, "
            f"{stats['pages_updated']} updated, {stats['pages_skipped']} skipped, "
            f"{stats['tasks_queued']} tasks queued"
        )

        return stats

    def _api_request(
        self, url: str, params: dict, retries: int = MAX_RETRIES
    ) -> Optional[list | dict]:
        """Make API request with retry logic."""
        for attempt in range(retries):
            try:
                response = self.session.get(url, params=params, timeout=60)
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

    def _get_stored_hash(self, wp_page_id: int) -> Optional[str]:
        """Get stored content hash for a WordPress page."""
        if self.db is None:
            return None

        try:
            with self.db.cursor() as cur:
                cur.execute(
                    """
                    SELECT content_hash FROM source_pages
                    WHERE source_type = 'wordpress_page' AND source_id = %s
                    """,
                    (wp_page_id,),
                )
                result = cur.fetchone()
                return result[0] if result else None
        except psycopg2.Error as e:
            logger.error(f"Error getting stored hash: {e}")
            return None

    def _update_page(
        self,
        page_id: int,
        title: str,
        url: str,
        html_content: str,
        text_content: str,
        content_hash: str,
        modified: str,
    ) -> int:
        """
        Update page in database and queue processing tasks.

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
                cur.execute(
                    """
                    INSERT INTO source_pages (
                        source_type, source_id, title, url,
                        content_hash, content_text, content_html, last_synced
                    )
                    VALUES ('wordpress_page', %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
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
                        page_id,
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
                    f"  Updated {title} (hash={content_hash[:8]}..., tasks={tasks_queued})"
                )

        except psycopg2.Error as e:
            self.db.rollback()
            logger.error(f"Database error updating {title}: {e}")
            raise

        return tasks_queued


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Sync OSGeo WordPress pages")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Fetch pages modified in last N days (default: 7)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full sync - fetch all pages regardless of modification date",
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
    client = WordPressSyncClient(db_connection=db)

    if args.full:
        stats = client.sync(dry_run=args.dry_run, full_sync=True)
    else:
        modified_after = datetime.now(timezone.utc) - timedelta(days=args.days)
        stats = client.sync(modified_after=modified_after, dry_run=args.dry_run)

    # Print summary
    print(f"\nSync Summary:")
    print(f"  Pages fetched: {stats['pages_fetched']}")
    print(f"  Pages created: {stats['pages_created']}")
    print(f"  Pages updated: {stats['pages_updated']}")
    print(f"  Pages skipped: {stats['pages_skipped']}")
    print(f"  Tasks queued:  {stats['tasks_queued']}")
    if stats["errors"]:
        print(f"  Errors: {len(stats['errors'])}")
        for err in stats["errors"][:5]:
            print(f"    - {err}")

    if db:
        db.close()


if __name__ == "__main__":
    main()

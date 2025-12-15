# Operations Guide

This document describes how to run and maintain the OSGeo Wiki Database sync pipeline.

## Prerequisites

- Python 3.9+
- PostgreSQL 12+ with pg_trgm extension
- Environment variables configured in `.env` (see `.env.template`)

### Required Environment Variables

```bash
DB_HOST=localhost
DB_NAME=osgeo_wiki
DB_USER=your_user
DB_PASSWORD=your_password
DB_PORT=5432
OPENROUTER_API_KEY=your_api_key  # Required for LLM summaries
```

## Pipeline Overview

The sync pipeline runs in stages:

| Stage | Script | Description |
|-------|--------|-------------|
| 1a | `crawler/wiki_sync.py` | Fetch changed pages from wiki, queue tasks |
| 1b | `crawler/wordpress_sync.py` | Fetch pages from WordPress, queue tasks |
| 2 | `db/process_chunks.py` | Split content into searchable chunks |
| 3 | `db/process_extensions.py` | Generate LLM summaries and keywords |
| 4 | `db/process_entities.py` | Extract entities and relationships (disabled) |

Each stage queues work for the next via the `processing_queue` table.

## Running the Pipeline

### Step 1: Sync Wiki Changes

Fetch recent changes from the wiki and queue processing tasks:

```bash
# Sync changes from the last 24 hours (default)
python3 crawler/wiki_sync.py

# Sync changes from the last 7 days
python3 crawler/wiki_sync.py --days=7

# Sync from a specific timestamp
python3 crawler/wiki_sync.py --since="2025-12-01T00:00:00Z"

# Dry run - show what would be synced without making changes
python3 crawler/wiki_sync.py --dry-run --days=3

# Verbose output
python3 crawler/wiki_sync.py -v
```

**Options:**
- `--since` - ISO timestamp to sync from
- `--days` - Number of days to look back (default: 1)
- `--dry-run` - Preview changes without updating database
- `--verbose, -v` - Enable debug logging

### Step 1b: Sync WordPress Pages

Fetch pages from www.osgeo.org and queue processing tasks:

```bash
# Full sync (all pages)
python3 crawler/wordpress_sync.py --full

# Sync pages modified in last 7 days (default)
python3 crawler/wordpress_sync.py

# Sync pages modified in last N days
python3 crawler/wordpress_sync.py --days=30

# Dry run
python3 crawler/wordpress_sync.py --dry-run --full

# Verbose output
python3 crawler/wordpress_sync.py --full -v
```

**Options:**
- `--full` - Sync all pages regardless of modification date
- `--days` - Number of days to look back (default: 7)
- `--dry-run` - Preview changes without updating database
- `--verbose, -v` - Enable debug logging

**Notes:**
- Uses REST API for page metadata, HTML scraping for content
- Extracts content from `<main>` tag to capture dynamic content
- ~8 archive template pages have no content and are skipped
- See [WordPress Integration](wordpress_integration.md) for details

### Step 2: Process Chunks

Split synced pages into searchable chunks with tsvector indexing:

```bash
# Process up to 10 pending chunk tasks (default)
python3 db/process_chunks.py

# Process more tasks in one run
python3 db/process_chunks.py --limit=50

# Verbose output
python3 db/process_chunks.py -v
```

**Options:**
- `--limit` - Maximum tasks to process (default: 10)
- `--verbose, -v` - Enable debug logging

### Step 3: Generate Extensions (Summaries/Keywords)

Generate LLM-powered summaries and keywords via OpenRouter:

```bash
# Process up to 10 pending extension tasks (default)
python3 db/process_extensions.py

# Process more tasks
python3 db/process_extensions.py --limit=50

# Verbose output
python3 db/process_extensions.py -v
```

**Options:**
- `--limit` - Maximum tasks to process (default: 10)
- `--verbose, -v` - Enable debug logging

**Notes:**
- Requires `OPENROUTER_API_KEY` in `.env`
- Uses free models with 5-second delay between requests
- Primary model: `mistralai/devstral-2512:free`
- Fallback model: `google/gemma-3-12b-it:free`

### Step 4: Extract Entities (Optional)

Extract named entities and relationships:

```bash
# Process up to 10 pending entity tasks (default)
python3 db/process_entities.py

# Process more tasks
python3 db/process_entities.py --limit=50
```

**Note:** Entity extraction is currently disabled pending improvements to the extraction approach.

## Full Pipeline Example

Run all stages in sequence:

```bash
# 1. Sync recent wiki changes
python3 crawler/wiki_sync.py --days=1

# 2. Process all pending chunks
python3 db/process_chunks.py --limit=100

# 3. Generate summaries (may take a while due to rate limits)
python3 db/process_extensions.py --limit=100

# 4. (Optional) Extract entities
# python3 db/process_entities.py --limit=100
```

## Monitoring

### Check Queue Status

```sql
-- View pending tasks by type
SELECT task_type, status, COUNT(*)
FROM processing_queue
GROUP BY task_type, status
ORDER BY task_type, status;

-- View recent completions
SELECT task_type, source_page_id, completed_at
FROM processing_queue
WHERE status = 'done'
ORDER BY completed_at DESC
LIMIT 20;
```

### Check Sync Status

```sql
-- Recently synced pages
SELECT title, last_revid, last_synced, status
FROM source_pages
ORDER BY last_synced DESC
LIMIT 20;

-- Pages with errors
SELECT title, status, last_synced
FROM source_pages
WHERE status != 'active';
```

### Check Data Quality

```sql
-- Extension coverage
SELECT
  COUNT(*) as total_pages,
  COUNT(pe.id) as with_extensions,
  ROUND(100.0 * COUNT(pe.id) / COUNT(*), 1) as coverage_pct
FROM pages p
LEFT JOIN page_extensions pe ON pe.page_title = p.title;

-- Chunk statistics
SELECT
  COUNT(*) as total_chunks,
  ROUND(AVG(LENGTH(chunk_text))) as avg_length,
  MIN(LENGTH(chunk_text)) as min_length,
  MAX(LENGTH(chunk_text)) as max_length
FROM page_chunks;
```

## Production Deployment

### Initial Setup

```bash
# 1. Clone repository
git clone https://github.com/osgeo/osgeo_wiki_bot.git
cd osgeo_wiki_bot

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.template .env
# Edit .env with your credentials

# 4. Initialize database schema
psql -d osgeo_wiki -f schema/tables.sql
psql -d osgeo_wiki -f schema/triggers.sql
psql -d osgeo_wiki -f schema/extension.sql
psql -d osgeo_wiki -f schema/sync_tracking.sql
```

### Cron Setup

Example crontab for automated syncing:

```bash
# Edit crontab
crontab -e

# Add these lines:

# Daily wiki sync at 2 AM
0 2 * * * cd /path/to/osgeo_wiki_bot && /path/to/venv/bin/python3 crawler/wiki_sync.py >> logs/sync.log 2>&1

# Process chunks after sync
30 2 * * * cd /path/to/osgeo_wiki_bot && /path/to/venv/bin/python3 db/process_chunks.py --limit=100 >> logs/chunks.log 2>&1

# Process extensions (staggered to avoid rate limits)
0 3 * * * cd /path/to/osgeo_wiki_bot && /path/to/venv/bin/python3 db/process_extensions.py --limit=50 >> logs/extensions.log 2>&1

# Weekly database maintenance on Sunday at 4 AM
0 4 * * 0 psql -d osgeo_wiki -c "VACUUM ANALYZE;" >> logs/maintenance.log 2>&1

# Monthly full crawl on 1st at 3 AM (catches deletions, missed changes)
0 3 1 * * cd /path/to/osgeo_wiki_bot && /path/to/venv/bin/python3 crawler/crawler.py >> logs/full_crawl.log 2>&1
```

### Log Files

Workers create log files in the project directory:
- `process_chunks.log`
- `process_extensions.log`
- `process_entities.log`

Consider rotating these logs or redirecting to a central location.

## Troubleshooting

### Common Issues

**"OPENROUTER_API_KEY not set"**
- Ensure `.env` file exists and contains `OPENROUTER_API_KEY=your_key`
- Check the key is valid at https://openrouter.ai/keys

**"Database connection failed"**
- Verify PostgreSQL is running
- Check credentials in `.env`
- Ensure database and user exist

**"Rate limited (429)"**
- OpenRouter free tier has rate limits
- The script automatically handles this with retries and fallback models
- Consider increasing delay between requests or using paid tier

**Tasks stuck in "pending"**
- Check worker logs for errors
- Verify database connection
- Run workers manually with `-v` for debug output

### Manual Queue Management

```sql
-- Reset stuck tasks (claimed but not completed)
UPDATE processing_queue
SET status = 'pending', claimed_at = NULL, worker_id = NULL
WHERE status = 'claimed'
  AND claimed_at < NOW() - INTERVAL '1 hour';

-- Clear failed tasks for retry
UPDATE processing_queue
SET status = 'pending', error_message = NULL
WHERE status = 'failed';

-- View errors
SELECT task_type, source_page_id, error_message, created_at
FROM processing_queue
WHERE status = 'failed'
ORDER BY created_at DESC;
```

## Schema Migrations

When updating to a new version, check for schema changes:

```bash
# Apply sync tracking tables (if not present)
psql -d osgeo_wiki -f schema/sync_tracking.sql
```

The schema files are idempotent (use `IF NOT EXISTS`) and safe to re-run.

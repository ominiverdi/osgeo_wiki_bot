# Data Pipeline

This document describes the data import and update strategies for the OSGeo Wiki Database.

## Content Sources

### 1. OSGeo Wiki (wiki.osgeo.org)
- MediaWiki instance
- Primary source for project documentation, governance, events

### 2. OSGeo WordPress (osgeo.org)
- Main website content
- News, announcements, organizational info

### 3. OSGeo Blog (blog.osgeo.org)
- Blog posts, community updates
- Event reports, project highlights

## Initial Import

### Phase 1: Wiki Content
1. **Crawl** - Fetch all wiki pages using MediaWiki API
2. **Parse** - Extract clean text content, metadata, categories
3. **Chunk** - Split content into searchable chunks (optimized size)
4. **Index** - Generate tsvector for full-text search
5. **Store** - Insert into PostgreSQL

### Phase 2: Entity Extraction
1. **Identify** - Extract named entities (people, projects, organizations, events)
2. **Classify** - Assign entity types
3. **Link** - Create relationships between entities
4. **Store** - Populate entity and relationship tables

### Phase 3: WordPress Content
1. **Crawl** - Fetch posts and pages via WordPress REST API
2. **Parse** - Extract content, author, date, categories
3. **Chunk** - Split into searchable chunks
4. **Merge** - Integrate with existing wiki entities where applicable
5. **Store** - Insert into PostgreSQL

## Continuous Update Strategy

### MediaWiki Recent Changes API

We use the MediaWiki `recentchanges` API for efficient change detection:

```
https://wiki.osgeo.org/w/api.php?action=query&list=recentchanges&rcprop=title|timestamp|ids|user|comment&rclimit=50&format=json
```

**Response fields:**
| Field | Description |
|-------|-------------|
| `pageid` | Unique page ID (stable across renames) |
| `title` | Page title |
| `revid` | New revision ID |
| `old_revid` | Previous revision ID |
| `timestamp` | When the change occurred |
| `user` | Who made the edit |
| `comment` | Edit summary |

**Filtering by date:**
```
&rcend=2025-12-10T00:00:00Z  # Only changes after this timestamp
```

### Avoiding Duplicate Updates

**Problem scenarios:**
1. Multiple edits to same page in one sync (e.g., 4 edits to "Osgeo8")
2. Page updated again after we already synced it today

**Solution: Track revision ID per page**

We store the last processed `revid` for each page. On sync:
1. Deduplicate changes by `pageid`, keeping only the latest `revid`
2. Compare against stored `revid` - skip if already processed
3. Optionally hash content to detect identical content across revisions

### Sync Algorithm

```python
def sync_changes(since_timestamp):
    # 1. Get recent changes from API
    changes = fetch_recentchanges(since=since_timestamp)
    
    # 2. Deduplicate - keep only latest revid per pageid
    latest_by_page = {}
    for change in changes:
        pageid = change['pageid']
        if pageid not in latest_by_page or change['revid'] > latest_by_page[pageid]['revid']:
            latest_by_page[pageid] = change
    
    # 3. Filter out already-processed revisions
    to_update = []
    for pageid, change in latest_by_page.items():
        stored_revid = db.get_last_revid(pageid)
        if stored_revid is None or change['revid'] > stored_revid:
            to_update.append(change)
    
    # 4. Process only what's actually new
    for change in to_update:
        content = fetch_page_content(change['title'])
        update_chunks(change['pageid'], content)
        db.set_last_revid(change['pageid'], change['revid'])
    
    return len(to_update)
```

### Update Scenarios

| Scenario | What happens |
|----------|--------------|
| First sync | All pages processed, revids stored |
| Same page edited 4 times | Only latest revid processed |
| Sync twice, no changes | Second sync skips (revid unchanged) |
| Sync, edit, sync again | Second sync processes new revid |
| Page deleted | Detected via `rctype=log` or periodic full scan |

### Update Pipeline

```
[Poll recentchanges API]
        |
        v
[Deduplicate by pageid]
        |
        v
[Filter: revid > stored_revid?]
        |
        v
[Fetch full page content]
        |
        v
[Compare content hash (optional)]
        |
        v
[Update Chunks] --> [Regenerate Search Vectors]
        |
        v
[Update Entities] --> [Update Knowledge Graph]
        |
        v
[Store new revid + Log Change]
```

### Chunk Update Strategy

When a page is modified:
1. **Soft delete** - Mark existing chunks as `outdated`
2. **Re-chunk** - Process new content into chunks
3. **Compare** - Match new chunks to existing where possible (preserve IDs)
4. **Update** - Insert new/modified chunks, remove orphaned ones
5. **Reindex** - Regenerate tsvector for affected chunks

### Knowledge Graph Updates

When entities change:
1. **Re-extract** - Run entity extraction on modified content
2. **Diff** - Compare with existing entities
3. **Merge** - Update existing entities, add new ones
4. **Prune** - Remove relationships no longer supported by content
5. **Validate** - Check graph consistency

## Database Tables

### Tracking Tables

```sql
-- Track source page sync status
CREATE TABLE source_pages (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,           -- 'wiki', 'wordpress_page', 'wordpress_post'
    source_id INTEGER,                   -- pageid from MediaWiki, post ID from WordPress
    title TEXT NOT NULL,
    url TEXT,
    last_revid INTEGER,                  -- Last revision ID we processed
    content_hash TEXT,                   -- SHA256 of content for change detection
    last_synced TIMESTAMP,               -- When we last synced this page
    status TEXT DEFAULT 'active',        -- 'active', 'outdated', 'deleted'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, source_id)
);

-- Track sync operations
CREATE TABLE sync_log (
    id SERIAL PRIMARY KEY,
    sync_type TEXT NOT NULL,             -- 'incremental', 'full'
    source_type TEXT NOT NULL,           -- 'wiki', 'wordpress'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    pages_checked INTEGER DEFAULT 0,
    pages_updated INTEGER DEFAULT 0,
    pages_created INTEGER DEFAULT 0,
    pages_deleted INTEGER DEFAULT 0,
    errors TEXT[],                       -- Array of error messages
    status TEXT DEFAULT 'running'        -- 'running', 'completed', 'failed'
);

-- Track individual page updates
CREATE TABLE update_log (
    id SERIAL PRIMARY KEY,
    sync_id INTEGER REFERENCES sync_log(id),
    source_page_id INTEGER REFERENCES source_pages(id),
    update_type TEXT NOT NULL,           -- 'created', 'modified', 'deleted'
    old_revid INTEGER,
    new_revid INTEGER,
    chunks_added INTEGER DEFAULT 0,
    chunks_removed INTEGER DEFAULT 0,
    chunks_modified INTEGER DEFAULT 0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_source_pages_type_id ON source_pages(source_type, source_id);
CREATE INDEX idx_source_pages_status ON source_pages(status);
CREATE INDEX idx_sync_log_started ON sync_log(started_at);
CREATE INDEX idx_update_log_sync ON update_log(sync_id);
```

## Scheduling

### Recommended Schedule

| Task | Frequency | Description |
|------|-----------|-------------|
| Wiki incremental sync | Daily | Check recentchanges API |
| WordPress sync | Daily | Fetch new/updated posts |
| Full wiki crawl | Monthly | Catch any missed changes, detect deletions |
| Entity re-extraction | Weekly | Refresh entity relationships |
| Database maintenance | Weekly | VACUUM, reindex |

### Cron Examples

```bash
# Daily wiki sync at 2 AM
0 2 * * * cd /path/to/project && python crawler/wiki_sync.py

# Monthly full crawl on 1st at 3 AM
0 3 1 * * cd /path/to/project && python crawler/crawler.py --full

# Weekly maintenance on Sunday at 4 AM
0 4 * * 0 psql -d osgeo_wiki -c "VACUUM ANALYZE;"
```

## Error Handling

- Retry failed fetches with exponential backoff (max 3 retries)
- Log all failures to `sync_log.errors`
- Continue processing other pages on single-page failure
- Alert on repeated failures (configurable threshold)
- Mark pages as 'error' status after max retries

## WordPress Update Strategy

Similar approach using REST API:

```
https://www.osgeo.org/wp-json/wp/v2/posts?modified_after=2025-12-10T00:00:00Z
```

Track by post ID and `modified` timestamp instead of revid.

## Future Considerations

- Webhook integration for real-time updates (if sources support)
- Distributed crawling for large-scale content
- ML-based change significance scoring (skip trivial edits)
- Cross-source entity resolution improvements

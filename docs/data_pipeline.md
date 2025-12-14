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

### Change Detection

#### Wiki
- Use MediaWiki API `recentchanges` endpoint
- Track `last_modified` timestamp per page
- Poll interval: configurable (e.g., hourly, daily)

#### WordPress
- Use REST API with `modified_after` parameter
- Track `last_modified` per post/page
- Poll interval: configurable

### Update Pipeline

```
[Source Change Detected]
        |
        v
[Fetch Updated Content]
        |
        v
[Compare with Stored Version]
        |
        v
[Update Chunks] --> [Regenerate Search Vectors]
        |
        v
[Update Entities] --> [Update Knowledge Graph]
        |
        v
[Log Change]
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
-- Track source page status
source_pages (
    id,
    source_type,      -- 'wiki', 'wordpress_page', 'wordpress_post'
    source_url,
    last_fetched,
    last_modified,
    content_hash,     -- For change detection
    status            -- 'active', 'outdated', 'deleted'
)

-- Track update history
update_log (
    id,
    source_page_id,
    update_type,      -- 'created', 'modified', 'deleted'
    timestamp,
    chunks_affected,
    entities_affected
)
```

## Scheduling

### Recommended Schedule

| Task | Frequency | Description |
|------|-----------|-------------|
| Wiki recent changes | Hourly | Check for wiki edits |
| WordPress sync | Daily | Fetch new/updated posts |
| Full wiki crawl | Weekly | Catch any missed changes |
| Entity re-extraction | Weekly | Refresh entity relationships |
| Database maintenance | Weekly | VACUUM, reindex |

## Error Handling

- Retry failed fetches with exponential backoff
- Log all failures for manual review
- Continue processing other sources on single-source failure
- Alert on repeated failures (configurable threshold)

## Future Considerations

- Webhook integration for real-time updates (if sources support)
- Distributed crawling for large-scale content
- ML-based change significance scoring (skip trivial edits)
- Cross-source entity resolution improvements

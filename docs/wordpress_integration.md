# WordPress Integration (www.osgeo.org)

This document describes the OSGeo WordPress site structure and integration approach.

## Site Overview

- **URL**: https://www.osgeo.org/
- **Platform**: WordPress
- **REST API**: Available at `https://www.osgeo.org/wp-json/wp/v2/`

## Content Types

### Pages (~97 published)
- Standard WordPress pages
- REST API provides metadata (id, title, link, modified)
- **Content scraped from HTML** (REST API content field misses dynamic content)

### News (Custom Post Type)
- Archive URL: https://www.osgeo.org/foundation-news/
- **NOT exposed via REST API** (custom post type `news` not registered for REST)
- Approximately 830 articles (83 pages x ~10 per page)
- RSS Feed: https://www.osgeo.org/foundation-news/feed/ (10 most recent)
- API access requested from webmaster (pending)

### Media (2,718 items)
- REST API: `GET /wp-json/wp/v2/media`
- Images, documents, etc. (not currently synced)

## Implementation

### Page Sync (`crawler/wordpress_sync.py`)

The sync script uses a hybrid approach:

1. **REST API for metadata**: Get page list with id, title, link, modified date
2. **HTML scraping for content**: Fetch each page and extract `<main>` tag content

This approach captures dynamically generated content (shortcodes, templates, member lists, etc.) that the REST API `content` field misses.

#### Why HTML Scraping?

Many WordPress pages use shortcodes or custom templates that generate content server-side. The REST API only returns the raw post content, not the rendered output. For example:

| Page | REST API content | HTML `<main>` content |
|------|------------------|----------------------|
| Charter Members | 0 bytes | 25KB (full member list) |
| Events History | 0 bytes | 8KB (event listings) |
| Board | 0 bytes | 3KB (board members) |

#### Usage

```bash
# Full sync (all pages)
python3 crawler/wordpress_sync.py --full

# Incremental sync (last 7 days, default)
python3 crawler/wordpress_sync.py

# Sync pages modified in last N days
python3 crawler/wordpress_sync.py --days=30

# Dry run
python3 crawler/wordpress_sync.py --dry-run --full

# Verbose output
python3 crawler/wordpress_sync.py --full -v
```

#### Output

- Pages stored in `source_pages` with `source_type='wordpress_page'`
- Processing tasks queued for chunks and extensions
- ~8 pages have no `<main>` tag (archive templates) and are skipped

### News Sync (Not Yet Implemented)

Options for syncing news articles:

1. **RSS Feed**: Limited to 10 most recent items
2. **HTML Scraping**: Full archive access, requires parsing
3. **REST API**: Pending webmaster enabling `show_in_rest` for news post type

## Data Flow

```
WordPress REST API          WordPress HTML Pages
       |                            |
       v                            v
  Page metadata              <main> content
  (id, title, link)          (rendered HTML)
       |                            |
       +------------+---------------+
                    |
                    v
              source_pages
         (source_type='wordpress_page')
                    |
                    v
        +----------+----------+
        |                     |
        v                     v
   page_chunks         page_extensions
   (searchable)        (LLM summaries)
```

## Content Overlap with Wiki

Some content exists in both wiki and WordPress:
- Project descriptions
- Committee information  
- Event pages

Current approach:
- Store all content from both sources
- Flag with `source_type` for filtering/weighting
- Search can prioritize WordPress (official) over wiki (working drafts)

## Schema

Uses existing `source_pages` table:
```sql
source_type TEXT NOT NULL  -- 'wiki', 'wordpress_page', 'wordpress_news'
```

## Monitoring

```sql
-- Check WordPress pages in database
SELECT COUNT(*), 
       AVG(LENGTH(content_text)) as avg_content_len
FROM source_pages 
WHERE source_type = 'wordpress_page';

-- Check processing status
SELECT task_type, status, COUNT(*)
FROM processing_queue pq
JOIN source_pages sp ON pq.source_page_id = sp.id
WHERE sp.source_type = 'wordpress_page'
GROUP BY task_type, status;
```

## Next Steps

- [x] Implement WordPress page sync with HTML scraping
- [ ] Add news sync when REST API access is enabled
- [ ] Process extensions for WordPress pages (LLM summaries)
- [ ] Test search with combined wiki + WordPress content

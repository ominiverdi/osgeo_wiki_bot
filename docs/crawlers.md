# Crawlers

This document describes the content crawlers for fetching data from OSGeo sources.

## Wiki Crawler

**Status**: Implemented

**Location**: `crawler/crawler.py`

### How it works

1. Fetches page list from MediaWiki API
2. Retrieves full content for each page
3. Extracts clean text, removing wiki markup
4. Saves to local dump files for processing

### Usage

```bash
python crawler/crawler.py
```

### Configuration

- Base URL: `https://wiki.osgeo.org`
- Output: `wiki_dump/` directory

### API Endpoints Used

- `api.php?action=query&list=allpages` - List all pages
- `api.php?action=parse&page=X` - Get parsed page content

## WordPress Crawler

**Status**: Planned

### Target Sites

- `https://www.osgeo.org` - Main website
- `https://blog.osgeo.org` - Blog

### Approach

Use WordPress REST API:
- `/wp-json/wp/v2/posts` - Blog posts
- `/wp-json/wp/v2/pages` - Static pages

### Planned Features

- Pagination handling
- Author extraction
- Category/tag mapping
- Featured image references

## Common Features (Planned)

### Rate Limiting

- Configurable delay between requests
- Respect robots.txt
- Back-off on errors

### Caching

- Store raw responses for debugging
- Skip unchanged content (ETag/Last-Modified)

### Logging

- Track crawl progress
- Record errors and retries
- Generate crawl reports

## Output Format

Crawlers output to `wiki_dump/` with structure:

```
wiki_dump/
├── wiki/
│   ├── Page_Name.json
│   └── ...
├── wordpress_pages/
│   └── ...
└── wordpress_posts/
    └── ...
```

Each JSON file contains:
```json
{
  "title": "Page Title",
  "url": "https://...",
  "content": "...",
  "metadata": {
    "last_modified": "...",
    "categories": [],
    "author": "..."
  }
}
```

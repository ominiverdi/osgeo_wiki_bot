# OSGeo Wiki Database

A PostgreSQL database for OSGeo wiki content, designed to power AI assistants and search interfaces with full-text search, entity extraction, and relationship queries.

## Project Overview

This project crawls the OSGeo wiki, processes content into searchable chunks, extracts entities and relationships, and stores everything in a PostgreSQL database. It serves as the knowledge backend for AI agents that answer questions about OSGeo projects, people, events, and governance.

**Primary use case**: Powering chatbots and AI assistants (e.g., Matrix bots) that need to answer questions like:
- "What is QGIS?" (full-text search on summaries)
- "Who is strk?" (entity lookup with fuzzy matching)
- "Who is president of OSGeo?" (relationship query by predicate)
- "List all FOSS4G conferences with their locations" (batch entity info with prefix matching)

## Architecture

### Components

- **Crawler**: Extracts content from wiki.osgeo.org
- **Database**: PostgreSQL with full-text search capabilities
- **Entity Extraction**: Identifies and indexes people, projects, and organizations
- **Analysis Tools**: Scripts for evaluating search quality and content metrics

### Data Flow

1. **Crawling**: Python crawler extracts content from OSGeo wiki
2. **Processing**: Content analyzed and divided into chunks
3. **Entity Extraction**: Named entities identified and linked
4. **Storage**: Data indexed in PostgreSQL with full-text search vectors
5. **Integration**: External clients query the database directly

## Key Features

- **Full-Text Search**: PostgreSQL tsvector indexing on content, summaries, and keywords
- **LLM-Enhanced Summaries**: AI-generated page summaries and keywords for better search relevance
- **Entity Extraction**: People, projects, organizations, events, and years
- **Entity Relationships**: Subject-predicate-object triples (e.g., "FOSS4G 2023" -> "located_in" -> "Kosovo")
- **Fuzzy Matching**: Trigram similarity for typo-tolerant entity search
- **Incremental Sync**: Track wiki changes via MediaWiki API to keep data fresh

## Database Schema

### Core Tables

- `pages` - Page content and metadata
- `page_chunks` - Searchable content chunks with tsvector indexes
- `page_categories` - Category assignments
- `code_snippets` - Extracted code blocks

### Entity Tables

- `entities` - Extracted named entities (people, projects, organizations, events)
- `entity_relationships` - Subject-predicate-object triples linking entities

### Extension Tables

- `page_extensions` - LLM-generated summaries and keywords for improved search
- `source_pages` - Sync tracking for incremental updates (see `schema/sync_tracking.sql`)

## Setup and Usage

### Prerequisites

- Python 3.9+
- PostgreSQL 12+ with pg_trgm extension

### Quick Start

```bash
# Setup environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure database connection
cp .env.template .env
# Edit .env with your PostgreSQL credentials

# Initialize database schema
psql -f schema/tables.sql
psql -f schema/triggers.sql
psql -f schema/extension.sql

# Crawl wiki content
python crawler/crawler.py

# Populate database
python db/populate_wiki_db.py

# Extract entities
python db/populate_entities.py
```

For incremental updates and production deployment, see [docs/operations.md](docs/operations.md).

## Project Structure

```
osgeo_wiki_bot/
├── analysis/        # Content analysis and search evaluation scripts
├── crawler/         # Wiki crawling components
├── db/              # Database population and test scripts
├── docs/            # Documentation and roadmap
├── modelfiles/      # Ollama model configurations
├── schema/          # PostgreSQL schema definitions
├── tests/           # Query and search tests
└── wiki_dump/       # Raw crawled content (gitignored)
```

## Integration

External clients query the database using standard PostgreSQL connections. The schema supports three main query patterns:

### 1. Full-Text Search (page content and summaries)

```sql
-- Search LLM-generated summaries and keywords
SELECT page_title, url, resume
FROM page_extensions
WHERE resume_tsv @@ websearch_to_tsquery('english', 'QGIS geographic information')
   OR keywords_tsv @@ websearch_to_tsquery('english', 'QGIS geographic information')
ORDER BY ts_rank(resume_tsv, websearch_to_tsquery('english', 'QGIS')) DESC
LIMIT 5;
```

### 2. Entity Search (fuzzy matching)

```sql
-- Find entities by name with trigram similarity
SELECT entity_name, entity_type, url
FROM entities
WHERE entity_name % 'strk'  -- trigram similarity
   OR entity_name ILIKE '%strk%'
ORDER BY similarity(entity_name, 'strk') DESC
LIMIT 10;
```

### 3. Relationship Queries

```sql
-- Find relationships by predicate (e.g., conference locations)
SELECT s.entity_name AS subject, r.predicate, o.entity_name AS object
FROM entity_relationships r
JOIN entities s ON r.subject_id = s.id
JOIN entities o ON r.object_id = o.id
WHERE r.predicate = 'located_in'
  AND s.entity_name LIKE 'FOSS4G%'
ORDER BY s.entity_name;
```

### 4. Batch Entity Info (prefix matching)

```sql
-- Get all FOSS4G conferences with their locations and years
SELECT e.entity_name, e.entity_type, r.predicate, o.entity_name AS related_to
FROM entities e
JOIN entity_relationships r ON e.id = r.subject_id
JOIN entities o ON r.object_id = o.id
WHERE e.entity_name LIKE 'FOSS4G%'
  AND r.predicate IN ('located_in', 'happened_in')
ORDER BY e.entity_name, r.predicate;
```

### Client Integration

See [matrix-llmagent](https://github.com/osgeo/matrix-llmagent) for a reference implementation that uses this database as a knowledge backend for an AI chatbot.

## Analysis Tools

The `analysis/` directory contains scripts for:

- Search quality evaluation
- Content metrics and statistics
- Chunking strategy comparison
- Entity distribution analysis

## TODO

### Content Sources
- [ ] Crawl OSGeo Wiki (wiki.osgeo.org) - current
- [ ] Crawl OSGeo WordPress instances (osgeo.org, blog.osgeo.org)
- [x] Incremental updates (detect and fetch only changed content via MediaWiki API)

### Data Processing
- [ ] Update content chunks when source pages change
- [ ] Regenerate semantic embeddings for modified chunks
- [ ] Update entity relationships on content changes

### Entity Management
- [ ] Improve entity extraction pipeline
- [ ] Entity deduplication and merging
- [ ] Relationship update triggers on content modification

### Infrastructure
- [ ] Scheduled sync jobs (cron)
- [ ] Change detection and notification
- [ ] Database maintenance and optimization

See [docs/data_pipeline.md](docs/data_pipeline.md) for detailed implementation plans.

See [docs/knowledge_graph.md](docs/knowledge_graph.md) for options on evolving to a full knowledge graph.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

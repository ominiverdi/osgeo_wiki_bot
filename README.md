# OSGeo Wiki Database

A PostgreSQL database for OSGeo wiki content with full-text search capabilities, entity extraction, and content analysis tools.

## Project Overview

This project crawls the OSGeo wiki, processes content into searchable chunks, and stores it in a PostgreSQL database optimized for full-text search. It provides the data layer that can be integrated with external clients (chatbots, search interfaces, etc.).

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

- **Full-Text Search**: PostgreSQL tsvector indexing for efficient text search
- **Content Chunking**: Optimized chunk sizes for search precision
- **Entity Recognition**: Extraction of people, projects, events, and organizations
- **Category Classification**: Wiki categories preserved for filtering
- **Graph Relationships**: Entity connections for contextual queries

## Database Schema

### Core Tables

- `wiki_pages` - Full page content and metadata
- `wiki_chunks` - Searchable content chunks with tsvector indexes
- `wiki_entities` - Extracted named entities
- `wiki_categories` - Category assignments

### Extensions

- `extension_*` tables for additional entity types and relationships

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

External clients can query the database using standard PostgreSQL connections. Example search query:

```sql
SELECT title, content, ts_rank(search_vector, query) AS rank
FROM wiki_chunks, plainto_tsquery('english', 'FOSS4G conference') AS query
WHERE search_vector @@ query
ORDER BY rank DESC
LIMIT 10;
```

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
- [ ] Incremental updates (detect and fetch only changed content)

### Data Processing
- [ ] Update content chunks when source pages change
- [ ] Regenerate semantic embeddings for modified chunks
- [ ] Update knowledge graph relationships on content changes

### Knowledge Graph
- [ ] Entity relationship extraction pipeline
- [ ] Graph update triggers on content modification
- [ ] Entity deduplication and merging

### Infrastructure
- [ ] Scheduled crawl jobs
- [ ] Change detection and notification
- [ ] Database maintenance and optimization

See [docs/data_pipeline.md](docs/data_pipeline.md) for detailed implementation plans.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

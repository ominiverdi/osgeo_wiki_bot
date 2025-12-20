# Search Capabilities

This document describes the search features available in the OSGeo Wiki Database.

## Search Types

### Full-Text Search

PostgreSQL tsvector-based search for keyword matching. NOTE: broken

```sql
SELECT title, content, ts_rank(search_vector, query) AS rank
FROM wiki_chunks, plainto_tsquery('english', 'FOSS4G conference') AS query
WHERE search_vector @@ query
ORDER BY rank DESC
LIMIT 10;
```

**Features**:
- Stemming (matches "configure", "configuration", "configured")
- Stop word removal
- Ranking by relevance
- Phrase matching with `phraseto_tsquery`

### Fuzzy Search

Trigram-based similarity search for typo tolerance.

```sql
SELECT title, similarity(title, 'QQGIS') AS sim
FROM pages
WHERE title % 'QQGIS'
ORDER BY sim DESC;
```

### Semantic Search (Planned)

Vector similarity search using embeddings.

```sql
SELECT title, content
FROM wiki_chunks
ORDER BY embedding <-> query_embedding
LIMIT 10;
```

### Graph Search

Traverse entity relationships.

```sql
-- Find all contributors to a project
SELECT e.name
FROM wiki_entities e
JOIN wiki_relationships r ON e.id = r.subject_id
WHERE r.object_id = (SELECT id FROM wiki_entities WHERE name = 'GDAL')
  AND r.predicate = 'contributes_to';
```

## Search Strategies

### Simple Query
Direct keyword search against content.

### Entity-Aware Query
1. Identify entities in query
2. Search entity table first
3. Expand to related content

### Hybrid Search (Planned)
Combine full-text and semantic search results with weighted ranking.

## Query Optimization

### Indexing
- GIN index on tsvector columns
- GIN index for trigram operations
- HNSW index for vector search (planned)

### Query Analysis
- `analysis/analyze_postgres_search.py` - Evaluate search quality
- `analysis/benchmark_search.py` - Performance testing

## Integration Examples

### Basic Search Function

```python
def search(query: str, limit: int = 10):
    sql = """
        SELECT title, content, ts_rank(search_vector, query) AS rank
        FROM wiki_chunks, plainto_tsquery('english', %s) AS query
        WHERE search_vector @@ query
        ORDER BY rank DESC
        LIMIT %s
    """
    return execute(sql, [query, limit])
```

### Entity + Content Search

```python
def search_with_entities(query: str):
    # 1. Check if query matches an entity
    entity = find_entity(query)
    if entity:
        # 2. Get entity info + related content
        return get_entity_context(entity)
    else:
        # 3. Fall back to content search
        return search_content(query)
```

## Performance Considerations

- Use `LIMIT` to avoid large result sets
- Consider `ts_headline` for snippet generation (expensive)
- Cache frequent queries
- Monitor slow query log

## Current Indexes (pages)

    "pages_pkey" PRIMARY KEY, btree (id)
    "pages_url_unique" UNIQUE, btree (url)
Referenced by:
    TABLE "code_snippets" CONSTRAINT "code_snippets_page_id_fkey" FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE
    TABLE "entities" CONSTRAINT "entities_source_page_id_fkey" FOREIGN KEY (source_page_id) REFERENCES pages(id)
    TABLE "entity_relationships" CONSTRAINT "entity_relationships_source_page_id_fkey" FOREIGN KEY (source_page_id) REFERENCES pages(id)
    TABLE "message_contexts" CONSTRAINT "message_contexts_page_id_fkey" FOREIGN KEY (page_id) REFERENCES pages(id)
    TABLE "page_categories" CONSTRAINT "page_categories_page_id_fkey" FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE
    TABLE "page_chunks" CONSTRAINT "page_chunks_page_id_fkey" FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE
    TABLE "page_processing_errors" CONSTRAINT "page_processing_errors_page_id_fkey" FOREIGN KEY (page_id) REFERENCES pages(id)
    TABLE "processing_queue" CONSTRAINT "processing_queue_page_id_fkey" FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE


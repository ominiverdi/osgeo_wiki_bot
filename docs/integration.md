# Integration Guide

This document describes how external clients can integrate with the OSGeo Wiki Database.

## Connection

### Direct PostgreSQL Connection

```python
import psycopg2

conn = psycopg2.connect(
    dbname="osgeo_wiki",
    user="your_user",
    password="your_password",
    host="localhost",
    port="5432"
)
```

### Connection Pooling (Recommended)

```python
from psycopg2 import pool

connection_pool = pool.SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dbname="osgeo_wiki",
    user="your_user",
    password="your_password",
    host="localhost"
)
```

## Common Queries

### Search Content

```sql
-- Full-text search
SELECT 
    p.title,
    p.url,
    c.content,
    ts_rank(c.search_vector, query) AS rank
FROM wiki_chunks c
JOIN wiki_pages p ON c.page_id = p.id,
plainto_tsquery('english', $1) AS query
WHERE c.search_vector @@ query
ORDER BY rank DESC
LIMIT 10;
```

### Get Entity Information

```sql
-- Find entity by name
SELECT * FROM wiki_entities
WHERE name ILIKE $1 OR $1 = ANY(aliases);

-- Get entity relationships
SELECT 
    e2.name AS related_entity,
    r.predicate AS relationship
FROM wiki_relationships r
JOIN wiki_entities e2 ON r.object_id = e2.id
WHERE r.subject_id = $1;
```

### Get Page with Chunks

```sql
SELECT 
    p.*,
    json_agg(c.content ORDER BY c.chunk_index) AS chunks
FROM wiki_pages p
JOIN wiki_chunks c ON c.page_id = p.id
WHERE p.id = $1
GROUP BY p.id;
```

## Client Examples

### Python Client

```python
class OSGeoWikiDB:
    def __init__(self, connection_string):
        self.conn = psycopg2.connect(connection_string)
    
    def search(self, query: str, limit: int = 10):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT title, content, ts_rank(search_vector, q) as rank
                FROM wiki_chunks, plainto_tsquery('english', %s) q
                WHERE search_vector @@ q
                ORDER BY rank DESC
                LIMIT %s
            """, [query, limit])
            return cur.fetchall()
    
    def get_entity(self, name: str):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM wiki_entities
                WHERE name ILIKE %s
            """, [name])
            return cur.fetchone()
```

### Chatbot Integration

For chatbot clients (e.g., Matrix bot):

1. Receive user query
2. Extract intent and entities from query
3. Build appropriate SQL query
4. Execute against database
5. Format results for response

```python
async def handle_query(user_message: str):
    # 1. Classify query type
    query_type = classify_query(user_message)
    
    # 2. Search database
    if query_type == "entity_lookup":
        results = db.get_entity(extract_entity(user_message))
    else:
        results = db.search(user_message)
    
    # 3. Format response
    return format_response(results, query_type)
```

## Read-Only Access

For security, integration clients should use read-only database credentials:

```sql
CREATE USER wiki_reader WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE osgeo_wiki TO wiki_reader;
GRANT USAGE ON SCHEMA public TO wiki_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO wiki_reader;
```

## Rate Limiting

Clients should implement rate limiting to prevent database overload:
- Recommended: 100 queries/minute per client
- Use connection pooling
- Cache frequent queries

## Error Handling

```python
from psycopg2 import OperationalError, DatabaseError

try:
    results = db.search(query)
except OperationalError:
    # Connection issue - retry or reconnect
    pass
except DatabaseError:
    # Query error - log and return error message
    pass
```

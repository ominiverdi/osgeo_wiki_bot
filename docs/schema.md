# Database Schema

This document describes the PostgreSQL database schema for the OSGeo Wiki Database.

## Overview

The database uses PostgreSQL with the following extensions:
- `pg_trgm` - Trigram similarity for fuzzy text matching
- `vector` - pgvector for semantic embeddings (planned)

## Core Tables

### wiki_pages

Stores full page content and metadata from source systems.

```sql
-- See schema/tables.sql for full definition
```

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| title | TEXT | Page title |
| url | TEXT | Source URL |
| content | TEXT | Full page content |
| source_type | TEXT | 'wiki', 'wordpress_page', 'wordpress_post' |
| last_modified | TIMESTAMP | Last modification time at source |
| created_at | TIMESTAMP | When record was created |
| updated_at | TIMESTAMP | When record was last updated |

### wiki_chunks

Searchable content chunks with full-text search vectors.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| page_id | INTEGER | Foreign key to wiki_pages |
| content | TEXT | Chunk content |
| chunk_index | INTEGER | Position within page |
| search_vector | TSVECTOR | Full-text search vector |
| embedding | VECTOR | Semantic embedding (planned) |

### wiki_entities

Extracted named entities.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| name | TEXT | Entity name |
| entity_type | TEXT | 'person', 'project', 'organization', 'event' |
| description | TEXT | Brief description |
| aliases | TEXT[] | Alternative names |

### wiki_relationships

Knowledge graph relationships between entities.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| subject_id | INTEGER | Source entity |
| predicate | TEXT | Relationship type |
| object_id | INTEGER | Target entity |
| source_page_id | INTEGER | Page where relationship was found |

## Indexes

- Full-text search: GIN index on `search_vector`
- Trigram: GIN index for fuzzy matching
- Entity lookups: B-tree on entity names and types

## Triggers

See `schema/triggers.sql` for automatic tsvector generation.

## Extension Tables

See `schema/extension.sql` for additional entity types and specialized tables.

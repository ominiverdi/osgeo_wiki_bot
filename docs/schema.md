# Database Schema

This document describes the PostgreSQL database schema for the OSGeo Wiki Database.

## Overview

The database uses PostgreSQL with the following extensions:
- `pg_trgm` - Trigram similarity for fuzzy text matching

## Schema Files

- `schema/tables.sql` - Core tables (pages, chunks, entities)
- `schema/triggers.sql` - Automatic tsvector generation
- `schema/extension.sql` - LLM-generated summaries and keywords
- `schema/sync_tracking.sql` - Incremental sync tracking and processing queue

## Core Tables

### pages

Stores page metadata from source systems.  ** Note : is this current?

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| title | TEXT | Page title |
| url | TEXT | Source URL |
| source_type | TEXT | 'wiki', 'wordpress_page', 'wordpress_post' |
| last_modified | TIMESTAMP | Last modification time at source |
| created_at | TIMESTAMP | When record was created |

### page_chunks

Searchable content chunks with full-text search vectors.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| page_id | INTEGER | Foreign key to pages |
| chunk_text | TEXT | Chunk content |
| chunk_index | INTEGER | Position within page |
| tsv | TSVECTOR | Full-text search vector (auto-generated) |

### page_categories

Category assignments for pages.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| page_id | INTEGER | Foreign key to pages |
| category | TEXT | Category name |

## Entity Tables

### entities

Extracted named entities.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| entity_name | TEXT | Entity name |
| entity_type | TEXT | 'person', 'project', 'organization', 'conference', 'location', etc. |
| url | TEXT | Source page URL |

### entity_relationships

Knowledge graph relationships between entities.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| subject_id | INTEGER | Source entity (foreign key) |
| predicate | TEXT | Relationship type ('is_member_of', 'located_in', 'works_for', etc.) |
| object_id | INTEGER | Target entity (foreign key) |
| url | TEXT | Page where relationship was found |

## Extension Tables

### page_extensions

LLM-generated summaries and keywords for improved search.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| url | TEXT | Page URL (unique) |
| page_title | TEXT | Page title |
| resume | TEXT | LLM-generated semantic summary |
| keywords | TEXT | LLM-generated searchable terms |
| last_updated | TIMESTAMP | When record was last updated |
| content_hash | TEXT | SHA256 hash for change detection |
| model_used | TEXT | Which LLM model generated this |
| resume_tsv | TSVECTOR | Full-text search vector (auto-generated) |
| keywords_tsv | TSVECTOR | Full-text search vector (auto-generated) |
| page_title_tsv | TSVECTOR | Full-text search vector (auto-generated) |

## Sync Tracking Tables

### source_pages

Tracks source page sync status and stores latest content.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| source_type | TEXT | 'wiki', 'wordpress_page', 'wordpress_post' |
| source_id | INTEGER | Page ID from source system |
| title | TEXT | Page title |
| url | TEXT | Page URL |
| last_revid | INTEGER | Last processed revision ID |
| content_hash | TEXT | SHA256 hash of content |
| content_text | TEXT | Full page content (plain text) |
| content_html | TEXT | Full page content (HTML) |
| categories | TEXT[] | Page categories |
| last_synced | TIMESTAMP | When last synced |
| status | TEXT | 'active', 'outdated', 'deleted' |

### processing_queue

Queue for async processing tasks.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| source_page_id | INTEGER | Foreign key to source_pages |
| page_id | INTEGER | Foreign key to pages (optional) |
| task_type | TEXT | 'chunks', 'extensions', 'entities' |
| priority | INTEGER | Higher = more urgent |
| status | TEXT | 'pending', 'processing', 'done', 'failed' |
| claimed_at | TIMESTAMP | When a worker claimed this task |
| completed_at | TIMESTAMP | When processing completed |
| worker_id | TEXT | Identifier of processing worker |
| error_message | TEXT | Error details if failed |

### sync_log

Tracks sync operations.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| sync_type | TEXT | 'incremental', 'full' |
| source_type | TEXT | 'wiki', 'wordpress' |
| started_at | TIMESTAMP | When sync started |
| completed_at | TIMESTAMP | When sync finished |
| pages_checked | INTEGER | Number of pages checked |
| pages_updated | INTEGER | Number of pages updated |
| pages_created | INTEGER | Number of pages created |
| pages_deleted | INTEGER | Number of pages deleted |
| errors | TEXT[] | Array of error messages |
| status | TEXT | 'running', 'completed', 'failed' |

## Indexes

- **Full-text search**: GIN indexes on all tsvector columns
- **Trigram**: GIN index on entity_name for fuzzy matching
- **Queue processing**: Index on (status, priority, created_at) for efficient task claiming
- **Sync tracking**: Indexes on source_type, source_id, and last_synced

## Functions

### claim_task(task_type TEXT)

Claims the next pending task of the specified type. Returns task details or NULL if no tasks available.

### complete_task(task_id INTEGER, success BOOLEAN, error_msg TEXT)

Marks a task as completed (done or failed).

### queue_page_tasks(source_page_id INTEGER)

Queues processing tasks (chunks, extensions, entities) for a newly synced page.

## Triggers

- `update_chunk_tsv_trigger` - Auto-generates tsvector on page_chunks insert/update
- `source_pages_updated_at` - Updates timestamp on source_pages modification

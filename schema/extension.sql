-- Page Extensions table for LLM-generated summaries and keywords
-- Used for improved search relevance

CREATE TABLE IF NOT EXISTS page_extensions (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,                -- Direct link to wiki page
    page_title TEXT NOT NULL,         -- Page title for reference
    resume TEXT NOT NULL,             -- LLM-generated semantic summary
    keywords TEXT NOT NULL,           -- LLM-generated searchable terms
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content_hash TEXT,                -- SHA256 hash for change detection
    model_used TEXT,                  -- Which LLM model generated this
    CONSTRAINT page_extensions_url_unique UNIQUE (url)
);

-- Generated tsvector columns for full-text search
ALTER TABLE page_extensions 
ADD COLUMN IF NOT EXISTS resume_tsv tsvector
GENERATED ALWAYS AS (to_tsvector('english', resume)) STORED;

ALTER TABLE page_extensions 
ADD COLUMN IF NOT EXISTS keywords_tsv tsvector
GENERATED ALWAYS AS (to_tsvector('english', keywords)) STORED;

ALTER TABLE page_extensions 
ADD COLUMN IF NOT EXISTS page_title_tsv tsvector
GENERATED ALWAYS AS (to_tsvector('english', page_title)) STORED;

-- GIN indexes for fast text search
CREATE INDEX IF NOT EXISTS idx_page_extensions_resume ON page_extensions USING GIN(to_tsvector('english', resume));
CREATE INDEX IF NOT EXISTS idx_page_extensions_keywords ON page_extensions USING GIN(to_tsvector('english', keywords));
CREATE INDEX IF NOT EXISTS idx_page_extensions_resume_tsv ON page_extensions USING GIN(resume_tsv);
CREATE INDEX IF NOT EXISTS idx_page_extensions_keywords_tsv ON page_extensions USING GIN(keywords_tsv);
CREATE INDEX IF NOT EXISTS idx_page_extensions_title_tsv ON page_extensions USING GIN(page_title_tsv);

-- Migration: rename wiki_url to url if needed (for existing installations)
-- ALTER TABLE page_extensions RENAME COLUMN wiki_url TO url;
-- ALTER TABLE page_extensions ADD COLUMN IF NOT EXISTS content_hash TEXT;
-- ALTER TABLE page_extensions ADD COLUMN IF NOT EXISTS model_used TEXT;

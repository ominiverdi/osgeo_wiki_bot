-- A table to search with contextual LLM generated resume and keywords
CREATE TABLE page_extensions (
    id SERIAL PRIMARY KEY,
    wiki_url TEXT NOT NULL,          -- Direct link to wiki page
    page_title TEXT NOT NULL,        -- Page title for reference
    resume TEXT NOT NULL,            -- LLM-generated semantic summary
    keywords TEXT NOT NULL,          -- LLM-generated searchable terms for improved matching
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_page_extensions_resume ON page_extensions USING GIN(to_tsvector('english', resume));
CREATE INDEX idx_page_extensions_keywords ON page_extensions USING GIN(to_tsvector('english', keywords));


-- extension_search.sql
-- SQL for searching the page_extensions table with weighted ranking

-- Create extension tsvector columns (run once)
ALTER TABLE page_extensions 
ADD COLUMN IF NOT EXISTS resume_tsv tsvector
GENERATED ALWAYS AS (to_tsvector('english', resume)) STORED;

ALTER TABLE page_extensions 
ADD COLUMN IF NOT EXISTS keywords_tsv tsvector
GENERATED ALWAYS AS (to_tsvector('english', keywords)) STORED;

ALTER TABLE page_extensions 
ADD COLUMN IF NOT EXISTS page_title_tsv tsvector
GENERATED ALWAYS AS (to_tsvector('english', page_title)) STORED;

-- Create GIN indexes for fast text search (run once)
CREATE INDEX IF NOT EXISTS idx_page_extensions_resume_tsv 
ON page_extensions USING GIN(resume_tsv);

CREATE INDEX IF NOT EXISTS idx_page_extensions_keywords_tsv 
ON page_extensions USING GIN(keywords_tsv);

CREATE INDEX IF NOT EXISTS idx_page_extensions_title_tsv 
ON page_extensions USING GIN(page_title_tsv);

-- Count total records
SELECT COUNT(*) FROM page_extensions;

-- Search query with weighted ranking - Both fields
-- Parameters: 1=query (3 occurrences), 2=limit
SELECT 
    pe.id, 
    pe.page_title,
    pe.wiki_url,
    pe.resume,
    pe.keywords,
    ((0.6 * ts_rank(pe.resume_tsv, websearch_to_tsquery('english', $1))) + 
     (0.4 * ts_rank(pe.keywords_tsv, websearch_to_tsquery('english', $1))) + 
     CASE WHEN pe.page_title_tsv @@ websearch_to_tsquery('english', $1) THEN 2.5 ELSE 0 END) AS rank,
    ts_headline('english', pe.resume, websearch_to_tsquery('english', $1), 
               'MaxFragments=2, MaxWords=30, MinWords=5, StartSel=<<, StopSel=>>') AS resume_headline
FROM 
    page_extensions pe
WHERE 
    (pe.resume_tsv @@ websearch_to_tsquery('english', $1) OR 
     pe.keywords_tsv @@ websearch_to_tsquery('english', $1) OR 
     pe.page_title_tsv @@ websearch_to_tsquery('english', $1))
ORDER BY 
    rank DESC
LIMIT $2;

-- Search query with weighted ranking - Resume only
-- Parameters: 1=query (2 occurrences), 2=limit
SELECT 
    pe.id, 
    pe.page_title,
    pe.wiki_url,
    pe.resume,
    pe.keywords,
    (ts_rank(pe.resume_tsv, websearch_to_tsquery('english', $1)) + 
     CASE WHEN pe.page_title_tsv @@ websearch_to_tsquery('english', $1) THEN 2.5 ELSE 0 END) AS rank,
    ts_headline('english', pe.resume, websearch_to_tsquery('english', $1), 
               'MaxFragments=2, MaxWords=30, MinWords=5, StartSel=<<, StopSel=>>') AS resume_headline
FROM 
    page_extensions pe
WHERE 
    pe.resume_tsv @@ websearch_to_tsquery('english', $1)
ORDER BY 
    rank DESC
LIMIT $2;

-- Search query with weighted ranking - Keywords only
-- Parameters: 1=query (2 occurrences), 2=limit
SELECT 
    pe.id, 
    pe.page_title,
    pe.wiki_url,
    pe.resume,
    pe.keywords,
    (ts_rank(pe.keywords_tsv, websearch_to_tsquery('english', $1)) + 
     CASE WHEN pe.page_title_tsv @@ websearch_to_tsquery('english', $1) THEN 2.5 ELSE 0 END) AS rank,
    ts_headline('english', pe.resume, websearch_to_tsquery('english', $1), 
               'MaxFragments=2, MaxWords=30, MinWords=5, StartSel=<<, StopSel=>>') AS resume_headline
FROM 
    page_extensions pe
WHERE 
    pe.keywords_tsv @@ websearch_to_tsquery('english', $1)
ORDER BY 
    rank DESC
LIMIT $2;
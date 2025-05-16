-- Now recreate the tables
CREATE TABLE pages (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    last_crawled TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE page_chunks (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    tsv TSVECTOR,
    UNIQUE(page_id, chunk_index)
);

CREATE TABLE code_snippets (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    snippet TEXT NOT NULL,
    language TEXT,
    snippet_index INTEGER
);

-- Indexes for fast retrieval
CREATE INDEX idx_page_chunks_tsv ON page_chunks USING GIN(tsv);
CREATE INDEX idx_page_chunks_page_id ON page_chunks(page_id);

CREATE TABLE page_categories (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    category_name TEXT NOT NULL,
    UNIQUE(page_id, category_name)
);

CREATE INDEX idx_page_categories_page_id ON page_categories(page_id);
CREATE INDEX idx_page_categories_name ON page_categories(category_name);
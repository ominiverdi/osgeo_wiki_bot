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

-- Entity tables
CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,         -- 'person', 'project', 'organization', 'event', 'year'
    entity_name TEXT NOT NULL,
    description TEXT,
    aliases TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_type, entity_name)
);

CREATE TABLE IF NOT EXISTS entity_relationships (
    id SERIAL PRIMARY KEY,
    subject_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,           -- 'member_of', 'contributes_to', 'part_of', etc.
    object_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    source_page_id INTEGER REFERENCES pages(id),
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_name ON entities(entity_name);
CREATE INDEX idx_entity_relationships_subject ON entity_relationships(subject_id);
CREATE INDEX idx_entity_relationships_object ON entity_relationships(object_id);
CREATE INDEX idx_entity_relationships_predicate ON entity_relationships(predicate);

CREATE TABLE pages (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT,
    tsv TSVECTOR
);

CREATE TABLE code_snippets (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id),
    snippet TEXT,
    language TEXT
);

CREATE INDEX idx_pages_tsv ON pages USING GIN(tsv);

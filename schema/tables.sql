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


-- Track conversations (either per user or per chat room)
CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    matrix_room_id TEXT NOT NULL,      -- The Matrix room identifier
    matrix_user_id TEXT,               -- Optional: specific user in multi-user rooms
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_topic TEXT                 -- Current conversation topic
);

-- Store message history
CREATE TABLE conversation_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    is_bot BOOLEAN NOT NULL,           -- TRUE if bot message, FALSE if user message
    message_text TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message_order INTEGER NOT NULL     -- For maintaining sequence
);

-- Track which chunks were used in responses
CREATE TABLE message_contexts (
    id SERIAL PRIMARY KEY,
    message_id INTEGER REFERENCES conversation_messages(id) ON DELETE CASCADE,
    page_id INTEGER REFERENCES pages(id),
    chunk_id INTEGER REFERENCES page_chunks(id),
    relevance_score FLOAT              -- How relevant this chunk was
);

-- Add indexes for performance
CREATE INDEX idx_conversations_room ON conversations(matrix_room_id);
CREATE INDEX idx_conversation_messages_convo ON conversation_messages(conversation_id);
CREATE INDEX idx_message_contexts_message ON message_contexts(message_id);
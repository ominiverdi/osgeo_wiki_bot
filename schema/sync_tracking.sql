-- Sync Tracking Tables
-- Tables for tracking incremental sync status and history

-- Track source page sync status
CREATE TABLE IF NOT EXISTS source_pages (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,           -- 'wiki', 'wordpress_page', 'wordpress_post'
    source_id INTEGER NOT NULL,          -- pageid from MediaWiki, post ID from WordPress
    title TEXT NOT NULL,
    url TEXT,
    last_revid INTEGER,                  -- Last revision ID we processed (MediaWiki)
    content_hash TEXT,                   -- SHA256 of content for change detection
    last_synced TIMESTAMP,               -- When we last synced this page
    status TEXT DEFAULT 'active',        -- 'active', 'outdated', 'deleted'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, source_id)
);

-- Track sync operations
CREATE TABLE IF NOT EXISTS sync_log (
    id SERIAL PRIMARY KEY,
    sync_type TEXT NOT NULL,             -- 'incremental', 'full'
    source_type TEXT NOT NULL,           -- 'wiki', 'wordpress'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    since_timestamp TIMESTAMP,           -- What timestamp we synced from
    pages_checked INTEGER DEFAULT 0,
    pages_updated INTEGER DEFAULT 0,
    pages_created INTEGER DEFAULT 0,
    pages_deleted INTEGER DEFAULT 0,
    pages_skipped INTEGER DEFAULT 0,
    errors TEXT[],                       -- Array of error messages
    status TEXT DEFAULT 'running'        -- 'running', 'completed', 'failed'
);

-- Track individual page updates
CREATE TABLE IF NOT EXISTS page_update_log (
    id SERIAL PRIMARY KEY,
    sync_id INTEGER REFERENCES sync_log(id),
    source_page_id INTEGER REFERENCES source_pages(id),
    update_type TEXT NOT NULL,           -- 'created', 'modified', 'deleted'
    old_revid INTEGER,
    new_revid INTEGER,
    old_content_hash TEXT,
    new_content_hash TEXT,
    chunks_added INTEGER DEFAULT 0,
    chunks_removed INTEGER DEFAULT 0,
    chunks_modified INTEGER DEFAULT 0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_source_pages_type_id ON source_pages(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_source_pages_status ON source_pages(status);
CREATE INDEX IF NOT EXISTS idx_source_pages_last_synced ON source_pages(last_synced);
CREATE INDEX IF NOT EXISTS idx_sync_log_started ON sync_log(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_log_status ON sync_log(status);
CREATE INDEX IF NOT EXISTS idx_page_update_log_sync ON page_update_log(sync_id);
CREATE INDEX IF NOT EXISTS idx_page_update_log_page ON page_update_log(source_page_id);

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_source_pages_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update timestamp
DROP TRIGGER IF EXISTS source_pages_updated_at ON source_pages;
CREATE TRIGGER source_pages_updated_at
    BEFORE UPDATE ON source_pages
    FOR EACH ROW
    EXECUTE FUNCTION update_source_pages_timestamp();

-- Helper view: recent sync operations
CREATE OR REPLACE VIEW recent_syncs AS
SELECT 
    id,
    sync_type,
    source_type,
    started_at,
    completed_at,
    EXTRACT(EPOCH FROM (completed_at - started_at)) AS duration_seconds,
    pages_checked,
    pages_created,
    pages_updated,
    pages_skipped,
    pages_deleted,
    array_length(errors, 1) AS error_count,
    status
FROM sync_log
ORDER BY started_at DESC
LIMIT 20;

-- Helper view: pages needing attention (errors or stale)
CREATE OR REPLACE VIEW pages_needing_attention AS
SELECT 
    sp.*,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - sp.last_synced)) / 86400 AS days_since_sync
FROM source_pages sp
WHERE sp.status = 'error'
   OR sp.last_synced < CURRENT_TIMESTAMP - INTERVAL '30 days'
ORDER BY sp.last_synced ASC NULLS FIRST;

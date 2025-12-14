-- Sync Tracking Tables
-- Tables for tracking incremental sync status and history

-- Track source page sync status and store latest content
-- This is the "source of truth" for all page content
-- Number of records = number of unique pages (one per page)
CREATE TABLE IF NOT EXISTS source_pages (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,           -- 'wiki', 'wordpress_page', 'wordpress_post'
    source_id INTEGER NOT NULL,          -- pageid from MediaWiki, post ID from WordPress
    title TEXT NOT NULL,
    url TEXT,
    last_revid INTEGER,                  -- Last revision ID we processed (MediaWiki)
    content_hash TEXT,                   -- SHA256 of content for change detection
    content_text TEXT,                   -- Plain text content (for processing)
    content_html TEXT,                   -- Original HTML (for reference)
    categories TEXT[],                   -- Array of category names
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

-- Processing Queue
-- Queue tasks for async processing (chunks, extensions, entities)
CREATE TABLE IF NOT EXISTS processing_queue (
    id SERIAL PRIMARY KEY,
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    source_page_id INTEGER REFERENCES source_pages(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,              -- 'chunks', 'extensions', 'entities'
    priority INTEGER DEFAULT 0,           -- Higher = more urgent
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT DEFAULT 'pending',        -- 'pending', 'processing', 'done', 'failed'
    error_message TEXT,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    -- Prevent duplicate pending tasks for same page/type
    CONSTRAINT unique_pending_task UNIQUE (page_id, task_type, status) 
        DEFERRABLE INITIALLY DEFERRED
);

-- Note: The unique constraint above prevents duplicate pending tasks but allows
-- multiple done/failed tasks for history. We handle this in application logic.

CREATE INDEX IF NOT EXISTS idx_queue_pending ON processing_queue(status, priority DESC, created_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_queue_page ON processing_queue(page_id);
CREATE INDEX IF NOT EXISTS idx_queue_type ON processing_queue(task_type);
CREATE INDEX IF NOT EXISTS idx_queue_source_page ON processing_queue(source_page_id);

-- Function to queue a task (avoids duplicates)
CREATE OR REPLACE FUNCTION queue_task(
    p_page_id INTEGER,
    p_source_page_id INTEGER,
    p_task_type TEXT,
    p_priority INTEGER DEFAULT 0
) RETURNS INTEGER AS $$
DECLARE
    v_queue_id INTEGER;
BEGIN
    -- Check if pending task already exists
    SELECT id INTO v_queue_id
    FROM processing_queue
    WHERE page_id = p_page_id 
      AND task_type = p_task_type 
      AND status = 'pending';
    
    IF v_queue_id IS NOT NULL THEN
        -- Already queued, return existing ID
        RETURN v_queue_id;
    END IF;
    
    -- Insert new task
    INSERT INTO processing_queue (page_id, source_page_id, task_type, priority)
    VALUES (p_page_id, p_source_page_id, p_task_type, p_priority)
    RETURNING id INTO v_queue_id;
    
    RETURN v_queue_id;
END;
$$ LANGUAGE plpgsql;

-- Function to claim next task for processing
CREATE OR REPLACE FUNCTION claim_task(p_task_type TEXT) 
RETURNS TABLE (
    queue_id INTEGER,
    page_id INTEGER,
    source_page_id INTEGER,
    attempts INTEGER
) AS $$
DECLARE
    v_queue_id INTEGER;
BEGIN
    -- Select and lock next pending task
    SELECT pq.id INTO v_queue_id
    FROM processing_queue pq
    WHERE pq.task_type = p_task_type
      AND pq.status = 'pending'
      AND pq.attempts < pq.max_attempts
    ORDER BY pq.priority DESC, pq.created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;
    
    IF v_queue_id IS NULL THEN
        RETURN;
    END IF;
    
    -- Mark as processing
    UPDATE processing_queue
    SET status = 'processing',
        started_at = CURRENT_TIMESTAMP,
        attempts = processing_queue.attempts + 1
    WHERE id = v_queue_id;
    
    -- Return task details
    RETURN QUERY
    SELECT pq.id, pq.page_id, pq.source_page_id, pq.attempts
    FROM processing_queue pq
    WHERE pq.id = v_queue_id;
END;
$$ LANGUAGE plpgsql;

-- Function to complete a task
CREATE OR REPLACE FUNCTION complete_task(p_queue_id INTEGER, p_success BOOLEAN, p_error TEXT DEFAULT NULL)
RETURNS VOID AS $$
BEGIN
    UPDATE processing_queue
    SET status = CASE WHEN p_success THEN 'done' ELSE 'failed' END,
        completed_at = CURRENT_TIMESTAMP,
        error_message = p_error
    WHERE id = p_queue_id;
END;
$$ LANGUAGE plpgsql;

-- Helper view: queue statistics
CREATE OR REPLACE VIEW queue_stats AS
SELECT 
    task_type,
    status,
    COUNT(*) as count,
    MIN(created_at) as oldest,
    MAX(created_at) as newest
FROM processing_queue
GROUP BY task_type, status
ORDER BY task_type, status;

-- Helper view: failed tasks for review
CREATE OR REPLACE VIEW failed_tasks AS
SELECT 
    pq.*,
    p.title as page_title,
    sp.url as page_url
FROM processing_queue pq
LEFT JOIN pages p ON pq.page_id = p.id
LEFT JOIN source_pages sp ON pq.source_page_id = sp.id
WHERE pq.status = 'failed'
ORDER BY pq.completed_at DESC;

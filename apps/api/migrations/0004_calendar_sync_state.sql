ALTER TABLE events ADD COLUMN cancelled_at TEXT;

CREATE TABLE calendar_sync_states (
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL CHECK (calendar_id GLOB 'sim_calendar_[a-h]'),
    domain_id TEXT CHECK (domain_id IS NULL OR domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    classified_at TEXT,
    sync_token TEXT,
    page_token TEXT,
    sync_status TEXT NOT NULL DEFAULT 'simulated' CHECK (sync_status IN ('simulated', 'stale', 'error')),
    last_success_at TEXT,
    last_attempt_at TEXT,
    error_code TEXT CHECK (error_code IS NULL OR error_code IN (
        'simulated_network', 'invalid_cursor', 'provider_error'
    )),
    PRIMARY KEY (source_id, calendar_id),
    CHECK ((domain_id IS NULL AND classified_at IS NULL) OR
           (domain_id IS NOT NULL AND classified_at IS NOT NULL))
);

CREATE INDEX idx_calendar_sync_states_domain_status
    ON calendar_sync_states(domain_id, sync_status);

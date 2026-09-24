ALTER TABLE calendar_sync_states ADD COLUMN full_sync_id TEXT;

CREATE TABLE calendar_sync_seen_events (
    source_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    full_sync_id TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    PRIMARY KEY (source_id, calendar_id, full_sync_id, external_ref),
    FOREIGN KEY (source_id, calendar_id)
        REFERENCES calendar_sync_states(source_id, calendar_id) ON DELETE CASCADE
);

CREATE INDEX idx_calendar_sync_seen_events_external_ref
    ON calendar_sync_seen_events(source_id, calendar_id, external_ref);

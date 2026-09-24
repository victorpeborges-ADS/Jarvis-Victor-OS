ALTER TABLE relations ADD COLUMN domain_id TEXT CHECK (domain_id IS NULL OR domain_id IN (
    'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
    'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
));

CREATE TABLE audit_entries (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL CHECK (operation IN ('source_write', 'event_write', 'entity_write', 'relation_write', 'memory_read')),
    outcome TEXT NOT NULL CHECK (outcome = 'success'),
    record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    dataset TEXT NOT NULL DEFAULT 'real' CHECK (dataset = 'real'),
    occurred_at TEXT NOT NULL
);

CREATE INDEX idx_audit_entries_occurred_at ON audit_entries(occurred_at);

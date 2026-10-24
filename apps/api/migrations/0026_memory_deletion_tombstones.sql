CREATE TABLE memory_deletion_tombstones (
    category TEXT NOT NULL CHECK (category IN (
        'explicit_capture', 'confirmed_fact', 'external_evidence', 'inferred_proposal'
    )),
    record_id TEXT NOT NULL CHECK (length(record_id) = 32 AND record_id NOT GLOB '*[^0-9a-f]*'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    deleted_revision INTEGER NOT NULL CHECK (deleted_revision >= 1),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    operation_id TEXT NOT NULL UNIQUE CHECK (length(operation_id) = 64 AND operation_id NOT GLOB '*[^0-9a-f]*'),
    deleted_at TEXT NOT NULL,
    PRIMARY KEY (category, domain_id, record_id)
);

CREATE INDEX idx_memory_deletion_tombstones_revision
    ON memory_deletion_tombstones(category, domain_id, deleted_revision, record_id);

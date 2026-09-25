CREATE TABLE missions (
    id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 9 AND 88),
    owner TEXT NOT NULL CHECK (length(owner) BETWEEN 1 AND 120),
    domain_id TEXT CHECK (domain_id IS NULL OR domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    status TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    document_json TEXT NOT NULL,
    dataset TEXT NOT NULL DEFAULT 'api_synthetic' CHECK (dataset = 'api_synthetic'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE mission_events (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, idempotency_key)
);

CREATE TABLE mission_idempotency (
    owner TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    PRIMARY KEY (owner, idempotency_key)
);

CREATE TABLE mission_knowledge (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    domain_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('staged', 'review')),
    content TEXT NOT NULL,
    skill_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_missions_owner_domain
    ON missions(owner, domain_id, id);

CREATE TABLE local_captures (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id = 'dom_synthetic_a'),
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_local_captures_owner_created
ON local_captures(owner, created_at, id);

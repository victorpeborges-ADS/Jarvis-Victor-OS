CREATE TABLE local_conversations (
    conversation_id TEXT PRIMARY KEY CHECK (
        length(conversation_id) = 32 AND conversation_id NOT GLOB '*[^0-9a-f]*'
    ),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX idx_local_conversations_resume
    ON local_conversations(owner, domain_id, expires_at, last_seen_at DESC);

CREATE TABLE synthetic_artifacts (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    origin_id TEXT NOT NULL CHECK (origin_id = 'generate-synthetic-document'),
    version TEXT NOT NULL CHECK (version = '1.0.0'),
    manifest_sha256 TEXT NOT NULL CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    size INTEGER NOT NULL CHECK (size BETWEEN 1 AND 65536),
    body BLOB NOT NULL,
    retain_until TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_synthetic_artifacts_authorized
    ON synthetic_artifacts(owner, domain_id, origin_id, version, retain_until);

CREATE TRIGGER synthetic_artifacts_are_immutable
BEFORE UPDATE ON synthetic_artifacts
BEGIN
    SELECT RAISE(ABORT, 'synthetic artifact is immutable');
END;

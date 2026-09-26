ALTER TABLE mission_knowledge
ADD COLUMN kind TEXT NOT NULL DEFAULT 'skill_derived'
CHECK (kind IN ('skill_derived', 'selected_original'));

ALTER TABLE mission_knowledge
ADD COLUMN source_review_id TEXT REFERENCES mission_artifact_reviews(id);

CREATE TABLE selected_synthetic_sources (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    domain_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count BETWEEN 1 AND 50000),
    classification TEXT NOT NULL CHECK (classification = 'synthetic_test_only'),
    state TEXT NOT NULL CHECK (state = 'awaiting_review'),
    selected_at TEXT NOT NULL,
    UNIQUE(owner, mission_id, content_sha256),
    UNIQUE(owner, idempotency_key)
);

CREATE INDEX idx_selected_sources_owner_mission
ON selected_synthetic_sources(owner, mission_id, selected_at);

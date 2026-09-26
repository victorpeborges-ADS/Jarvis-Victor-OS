CREATE TABLE mission_artifact_reviews (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL DEFAULT 1 CHECK (artifact_version >= 1),
    artifact_sha256 TEXT NOT NULL,
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'rejected', 'changes_requested')),
    decision_reason TEXT CHECK (decision_reason IS NULL OR length(decision_reason) <= 500),
    decision_actor TEXT,
    decided_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (mission_id, artifact_id, artifact_version)
);

CREATE TABLE mission_review_decisions (
    id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL REFERENCES mission_artifact_reviews(id) ON DELETE CASCADE,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL CHECK (artifact_version >= 1),
    artifact_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'changes_requested')),
    decision_reason TEXT CHECK (decision_reason IS NULL OR length(decision_reason) <= 500),
    actor TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, idempotency_key)
);

CREATE INDEX idx_reviews_owner_state ON mission_artifact_reviews(owner, state, mission_id);
CREATE INDEX idx_reviews_mission ON mission_artifact_reviews(mission_id, artifact_id);

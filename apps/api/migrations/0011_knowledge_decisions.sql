CREATE TABLE mission_knowledge_decisions (
    id TEXT PRIMARY KEY,
    knowledge_id TEXT NOT NULL UNIQUE REFERENCES mission_knowledge(id) ON DELETE CASCADE,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    domain_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    knowledge_sha256 TEXT NOT NULL,
    source_review_id TEXT REFERENCES mission_artifact_reviews(id),
    source_artifact_sha256 TEXT,
    actor TEXT NOT NULL,
    reason TEXT,
    idempotency_key TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    UNIQUE(owner, idempotency_key)
);

CREATE INDEX idx_knowledge_decisions_mission
ON mission_knowledge_decisions(owner, mission_id, decision);

CREATE TRIGGER knowledge_decisions_no_update
BEFORE UPDATE ON mission_knowledge_decisions
BEGIN SELECT RAISE(ABORT, 'knowledge decision ledger is append only'); END;

CREATE TRIGGER knowledge_decisions_no_delete
BEFORE DELETE ON mission_knowledge_decisions
BEGIN SELECT RAISE(ABORT, 'knowledge decision ledger is append only'); END;

CREATE TABLE mission_idempotency_scoped (
    owner TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN (
        'legacy_unresolved',
        'mission.create',
        'mission.transition',
        'mission.import',
        'mission.import.item',
        'mission.review.decide',
        'mission.review.revise'
    )),
    idempotency_key TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    result_json TEXT,
    PRIMARY KEY (owner, operation, idempotency_key)
);

INSERT INTO mission_idempotency_scoped (
    owner, operation, idempotency_key, mission_id, body_sha256, result_json
)
SELECT owner, 'legacy_unresolved', idempotency_key, mission_id, body_sha256, result_json
FROM mission_idempotency;

DROP TABLE mission_idempotency;
ALTER TABLE mission_idempotency_scoped RENAME TO mission_idempotency;

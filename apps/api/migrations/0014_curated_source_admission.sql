CREATE TABLE selected_synthetic_sources_curated (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    domain_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    review_id TEXT NOT NULL REFERENCES mission_artifact_reviews(id),
    knowledge_id TEXT NOT NULL REFERENCES mission_knowledge(id),
    idempotency_key TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count BETWEEN 1 AND 50000),
    classification TEXT NOT NULL CHECK (classification IN ('synthetic_verified', 'unverified')),
    state TEXT NOT NULL CHECK (state IN ('selected', 'quarantined')),
    selected_at TEXT NOT NULL,
    fixture_id TEXT,
    catalog_id TEXT,
    catalog_version TEXT,
    fixture_sha256 TEXT,
    provenance_json TEXT,
    UNIQUE(owner, mission_id, content_sha256),
    UNIQUE(owner, idempotency_key),
    CHECK (
        (classification='synthetic_verified' AND state='selected' AND fixture_id IS NOT NULL
         AND catalog_id IS NOT NULL AND catalog_version IS NOT NULL AND fixture_sha256 IS NOT NULL
         AND provenance_json IS NOT NULL)
        OR
        (classification='unverified' AND state='quarantined')
    )
);

INSERT INTO selected_synthetic_sources_curated (
    id, owner, mission_id, domain_id, display_name, content_sha256, review_id,
    knowledge_id, idempotency_key, byte_count, classification, state, selected_at,
    fixture_id, catalog_id, catalog_version, fixture_sha256, provenance_json
)
SELECT id, owner, mission_id, domain_id, display_name, content_sha256, review_id,
       knowledge_id, idempotency_key, byte_count, 'unverified', 'quarantined', selected_at,
       NULL, NULL, NULL, NULL, NULL
FROM selected_synthetic_sources;

DROP TABLE selected_synthetic_sources;
ALTER TABLE selected_synthetic_sources_curated RENAME TO selected_synthetic_sources;

CREATE INDEX idx_selected_sources_owner_mission
ON selected_synthetic_sources(owner, mission_id, selected_at);

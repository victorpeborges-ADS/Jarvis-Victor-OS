CREATE TABLE selected_source_reconciliation (
    source_id TEXT NOT NULL REFERENCES selected_synthetic_sources(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'reconciled', 'quarantined')),
    reason TEXT,
    evaluated_at TEXT,
    PRIMARY KEY (source_id, owner)
);

-- Only rows quarantined by migration 0014 with all new catalog claims absent
-- are eligible for the one-time legacy proof reconstruction.
INSERT INTO selected_source_reconciliation (source_id, owner, status)
SELECT id, owner, 'pending'
FROM selected_synthetic_sources
WHERE classification='unverified' AND state='quarantined'
  AND fixture_id IS NULL AND catalog_id IS NULL AND catalog_version IS NULL
  AND fixture_sha256 IS NULL AND provenance_json IS NULL;

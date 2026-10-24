CREATE TABLE confirmed_facts (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 80),
    source_kind TEXT NOT NULL CHECK (source_kind = 'owner_confirmation'),
    source_ref TEXT NOT NULL CHECK (
        length(source_ref) BETWEEN 1 AND 64
        AND source_ref NOT GLOB '*[^A-Za-z0-9_-]*'
    ),
    version INTEGER NOT NULL CHECK (version >= 1),
    recorded_at TEXT NOT NULL,
    revised_at TEXT NOT NULL
);

CREATE TABLE external_evidence (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 80),
    source_kind TEXT NOT NULL CHECK (source_kind = 'synthetic_source'),
    source_ref TEXT NOT NULL CHECK (
        length(source_ref) BETWEEN 1 AND 64
        AND source_ref NOT GLOB '*[^A-Za-z0-9_-]*'
    ),
    version INTEGER NOT NULL CHECK (version >= 1),
    recorded_at TEXT NOT NULL,
    revised_at TEXT NOT NULL
);

CREATE TABLE inferred_proposals (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 80),
    source_kind TEXT NOT NULL CHECK (source_kind = 'assistant_inference'),
    source_ref TEXT NOT NULL CHECK (
        length(source_ref) BETWEEN 1 AND 64
        AND source_ref NOT GLOB '*[^A-Za-z0-9_-]*'
    ),
    version INTEGER NOT NULL CHECK (version >= 1),
    recorded_at TEXT NOT NULL,
    revised_at TEXT NOT NULL
);

CREATE INDEX idx_confirmed_facts_domain
    ON confirmed_facts(owner, domain_id, recorded_at, id);
CREATE INDEX idx_external_evidence_domain
    ON external_evidence(owner, domain_id, recorded_at, id);
CREATE INDEX idx_inferred_proposals_domain
    ON inferred_proposals(owner, domain_id, recorded_at, id);

CREATE TRIGGER confirmed_facts_identity_immutable
BEFORE UPDATE OF id, owner, domain_id, source_kind, source_ref, recorded_at
ON confirmed_facts
BEGIN
    SELECT RAISE(ABORT, 'confirmed fact identity is immutable');
END;

CREATE TRIGGER confirmed_facts_revision_steps
BEFORE UPDATE OF body, version, revised_at ON confirmed_facts
WHEN NEW.version <> OLD.version + 1 OR NEW.body = OLD.body
BEGIN
    SELECT RAISE(ABORT, 'confirmed fact revision is invalid');
END;

CREATE TRIGGER external_evidence_identity_immutable
BEFORE UPDATE OF id, owner, domain_id, source_kind, source_ref, recorded_at
ON external_evidence
BEGIN
    SELECT RAISE(ABORT, 'external evidence identity is immutable');
END;

CREATE TRIGGER external_evidence_revision_steps
BEFORE UPDATE OF body, version, revised_at ON external_evidence
WHEN NEW.version <> OLD.version + 1 OR NEW.body = OLD.body
BEGIN
    SELECT RAISE(ABORT, 'external evidence revision is invalid');
END;

CREATE TRIGGER inferred_proposals_identity_immutable
BEFORE UPDATE OF id, owner, domain_id, source_kind, source_ref, recorded_at
ON inferred_proposals
BEGIN
    SELECT RAISE(ABORT, 'inferred proposal identity is immutable');
END;

CREATE TRIGGER inferred_proposals_revision_steps
BEFORE UPDATE OF body, version, revised_at ON inferred_proposals
WHEN NEW.version <> OLD.version + 1 OR NEW.body = OLD.body
BEGIN
    SELECT RAISE(ABORT, 'inferred proposal revision is invalid');
END;

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'calendar_sim'),
    resource_id TEXT NOT NULL CHECK (resource_id = 'calendar:synthetic-primary'),
    account_ref TEXT,
    scopes_json TEXT NOT NULL,
    sync_status TEXT NOT NULL CHECK (sync_status IN ('disconnected', 'idle', 'syncing', 'stale', 'error', 'revoked')),
    dataset TEXT NOT NULL DEFAULT 'real' CHECK (dataset = 'real'),
    created_at TEXT NOT NULL
);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('appointment', 'task', 'message', 'note', 'reference', 'project')),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
    domain_id TEXT CHECK (domain_id IS NULL OR domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    sensitivity TEXT NOT NULL CHECK (sensitivity IN ('normal', 'sensitive', 'restricted')),
    occurred_at TEXT,
    payload_json TEXT NOT NULL,
    dataset TEXT NOT NULL DEFAULT 'real' CHECK (dataset = 'real'),
    created_at TEXT NOT NULL
);

CREATE TABLE event_provenance (
    event_id TEXT PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_ref TEXT,
    observed_at TEXT NOT NULL,
    last_verified_at TEXT,
    valid_until TEXT,
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0.0 AND 1.0),
    classification_method TEXT NOT NULL CHECK (classification_method IN ('human_review', 'explicit_rule', 'unclassified')),
    classified_at TEXT,
    UNIQUE (source_id, external_ref)
);

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person', 'project', 'task', 'appointment', 'document', 'goal')),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 300),
    domain_id TEXT CHECK (domain_id IS NULL OR domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    sensitivity TEXT NOT NULL CHECK (sensitivity IN ('normal', 'sensitive', 'restricted')),
    dataset TEXT NOT NULL DEFAULT 'real' CHECK (dataset = 'real'),
    created_at TEXT NOT NULL
);

CREATE TABLE relations (
    id TEXT PRIMARY KEY,
    from_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL CHECK (relation_type IN ('related_to', 'owns', 'blocks', 'supports', 'scheduled_for', 'mentions')),
    review_status TEXT NOT NULL CHECK (review_status IN ('pending', 'accepted', 'rejected')),
    dataset TEXT NOT NULL DEFAULT 'real' CHECK (dataset = 'real'),
    created_at TEXT NOT NULL,
    CHECK (from_entity_id <> to_entity_id),
    UNIQUE (from_entity_id, to_entity_id, relation_type)
);

CREATE TABLE relation_evidence (
    relation_id TEXT NOT NULL REFERENCES relations(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    PRIMARY KEY (relation_id, event_id)
);

CREATE INDEX idx_events_domain_occurred
    ON events(domain_id, occurred_at);
CREATE INDEX idx_events_source_type
    ON events(source_id, event_type);
CREATE INDEX idx_entities_domain_type
    ON entities(domain_id, entity_type);
CREATE INDEX idx_relations_from_to
    ON relations(from_entity_id, to_entity_id);

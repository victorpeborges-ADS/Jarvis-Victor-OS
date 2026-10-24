CREATE TABLE prepared_effects (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    recipient TEXT NOT NULL CHECK (recipient GLOB '*@example.test'),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 400),
    plan_version TEXT NOT NULL CHECK (length(plan_version) BETWEEN 1 AND 32),
    approval_sha TEXT NOT NULL CHECK (length(approval_sha) = 64),
    effect_key TEXT NOT NULL UNIQUE CHECK (length(effect_key) = 64),
    status TEXT NOT NULL CHECK (status IN (
        'prepared', 'revoked', 'succeeded', 'failed', 'unknown', 'cancelled'
    )),
    confirmed INTEGER NOT NULL CHECK (confirmed IN (0, 1))
);

CREATE TABLE attention_notices (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) = 64),
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'deferred', 'delivered', 'missed', 'suppressed'
    )),
    cost TEXT NOT NULL CHECK (length(cost) BETWEEN 1 AND 16)
);

CREATE UNIQUE INDEX idx_attention_open_fingerprint
    ON attention_notices(owner, fingerprint)
    WHERE status IN ('pending', 'deferred', 'delivered', 'suppressed');

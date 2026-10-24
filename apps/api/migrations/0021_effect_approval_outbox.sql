ALTER TABLE workflow_approvals ADD COLUMN bound_account TEXT;
ALTER TABLE workflow_approvals ADD COLUMN bound_connector TEXT;
ALTER TABLE workflow_approvals ADD COLUMN bound_tool TEXT;
ALTER TABLE workflow_approvals ADD COLUMN bound_destination TEXT;
ALTER TABLE workflow_approvals ADD COLUMN bound_effect TEXT;
ALTER TABLE workflow_approvals ADD COLUMN binding_sha TEXT;

CREATE TABLE synthetic_effect_outbox (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    task_id TEXT NOT NULL UNIQUE REFERENCES workflow_tasks(id),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 8 AND 80),
    binding_sha TEXT NOT NULL CHECK (length(binding_sha) = 64),
    review_sha TEXT NOT NULL CHECK (length(review_sha) = 64),
    account TEXT NOT NULL,
    connector TEXT NOT NULL CHECK (connector = 'synthetic-mail'),
    tool_id TEXT NOT NULL CHECK (tool_id = 'simulate_action'),
    destination TEXT NOT NULL CHECK (destination = 'synthetic-outbox'),
    presented_effect TEXT NOT NULL CHECK (length(presented_effect) BETWEEN 1 AND 400),
    catalog_effect TEXT NOT NULL CHECK (length(catalog_effect) BETWEEN 1 AND 120),
    state TEXT NOT NULL CHECK (state IN ('succeeded', 'failed', 'unknown')),
    effect_ref TEXT CHECK (effect_ref IS NULL OR length(effect_ref) = 32),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE synthetic_effect_ledger (
    idempotency_key TEXT PRIMARY KEY,
    effect_ref TEXT NOT NULL UNIQUE CHECK (length(effect_ref) = 32),
    binding_sha TEXT NOT NULL CHECK (length(binding_sha) = 64),
    recorded_at TEXT NOT NULL
);

CREATE TABLE local_automations (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    kind TEXT NOT NULL CHECK (kind IN ('reminder', 'morning_briefing', 'idea_mission_review')),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 24),
    recurrence TEXT NOT NULL CHECK (recurrence IN ('once', 'daily')),
    local_schedule TEXT NOT NULL,
    timezone TEXT NOT NULL CHECK (length(timezone) BETWEEN 1 AND 64),
    quiet_start TEXT,
    quiet_end TEXT,
    message TEXT NOT NULL DEFAULT '' CHECK (length(message) <= 32),
    sources_json TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'paused', 'completed', 'deleted')),
    next_run_at_utc TEXT,
    max_retries INTEGER NOT NULL DEFAULT 2 CHECK (max_retries BETWEEN 0 AND 2),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE local_automation_runs (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    automation_id TEXT NOT NULL REFERENCES local_automations(id),
    scheduled_for_utc TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    workflow_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'deferred', 'retry_wait', 'succeeded', 'failed', 'missed', 'pending', 'superseded')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    next_attempt_at_utc TEXT,
    result_text TEXT NOT NULL DEFAULT '',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (automation_id, scheduled_for_utc)
);

CREATE INDEX idx_local_automations_owner_next
ON local_automations(owner, state, next_run_at_utc);

CREATE INDEX idx_local_automation_runs_schedule
ON local_automation_runs(automation_id, scheduled_for_utc DESC, created_at DESC);

CREATE TABLE workflow_tasks (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    tool_id TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    arguments_sha TEXT NOT NULL CHECK (length(arguments_sha) = 64),
    state TEXT NOT NULL CHECK (state IN (
        'proposed', 'awaiting_approval', 'paused', 'running', 'interrupted',
        'succeeded', 'failed', 'cancelled'
    )),
    resume_state TEXT,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 80),
    preview_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner, idempotency_key)
);

CREATE TABLE workflow_approvals (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    task_id TEXT NOT NULL UNIQUE REFERENCES workflow_tasks(id),
    arguments_sha TEXT NOT NULL CHECK (length(arguments_sha) = 64),
    session_binding TEXT NOT NULL CHECK (length(session_binding) = 64),
    grant_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE workflow_executions (
    id TEXT PRIMARY KEY CHECK (length(id) = 32),
    task_id TEXT NOT NULL UNIQUE REFERENCES workflow_tasks(id),
    phase TEXT NOT NULL CHECK (phase IN ('open', 'interrupted', 'committed')),
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE workflow_results (
    task_id TEXT PRIMARY KEY REFERENCES workflow_tasks(id),
    effect TEXT NOT NULL,
    output_json TEXT NOT NULL,
    result_sha TEXT NOT NULL CHECK (length(result_sha) = 64),
    attempts INTEGER NOT NULL CHECK (attempts > 0)
);

CREATE TABLE workflow_log (
    id INTEGER PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES workflow_tasks(id),
    at TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN (
        'created', 'paused', 'resumed', 'cancelled', 'approval_issued',
        'execution_opened', 'execution_interrupted', 'execution_succeeded',
        'execution_failed'
    ))
);

CREATE INDEX workflow_tasks_owner_updated ON workflow_tasks(owner, updated_at DESC);

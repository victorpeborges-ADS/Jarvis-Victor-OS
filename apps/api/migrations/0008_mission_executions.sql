CREATE TABLE mission_executions (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    task_id TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('open', 'committed', 'failed', 'interrupted')),
    attempt INTEGER NOT NULL,
    skill_id TEXT,
    skill_version TEXT,
    input_digest TEXT,
    revision_at_start INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    committed_at TEXT
);

CREATE UNIQUE INDEX idx_mission_one_open_execution
    ON mission_executions(mission_id) WHERE phase = 'open';

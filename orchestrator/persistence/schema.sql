CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    pipeline_type TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS step_executions (
    step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    exit_code INTEGER,
    stdout_path TEXT,
    stderr_path TEXT,
    output_files_json TEXT,
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id)
);

CREATE TABLE IF NOT EXISTS pull_request_tracking (
    prompt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    requesting_agent TEXT NOT NULL,
    priority TEXT NOT NULL,
    created_at TEXT NOT NULL,
    nepha_response_status TEXT,
    nepha_responded_at TEXT,
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id)
);

CREATE TABLE IF NOT EXISTS notifications_sent (
    notification_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL
);

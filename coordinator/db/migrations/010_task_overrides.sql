-- Reliability override records for auditable policy exceptions.

CREATE TABLE hive.task_overrides (
    id          SERIAL PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES hive.tasks(id) ON DELETE CASCADE,
    gate_name   TEXT NOT NULL CHECK (
        gate_name IN (
            'G1_scope_lock',
            'G2_tdd_order',
            'G3_verification',
            'G4_review_separation',
            'G5_handoff_completeness',
            'G_start_dependencies'
        )
    ),
    scope       TEXT NOT NULL CHECK (length(trim(scope)) > 0),
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
    reason      TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON hive.task_overrides (task_id, gate_name, expires_at);

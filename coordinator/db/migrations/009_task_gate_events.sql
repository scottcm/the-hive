-- Reliability gate engine audit trail.

CREATE TABLE hive.task_gate_events (
    id          SERIAL PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES hive.tasks(id) ON DELETE CASCADE,
    gate_name   TEXT NOT NULL CHECK (
        gate_name IN (
            'G1_scope_lock',
            'G2_tdd_order',
            'G3_verification',
            'G4_review_separation',
            'G5_handoff_completeness'
        )
    ),
    decision    TEXT NOT NULL CHECK (decision IN ('pass', 'fail', 'override')),
    reason      TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    actor       TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    artifact_ref TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON hive.task_gate_events (task_id, created_at, id);
CREATE INDEX ON hive.task_gate_events (gate_name, decision, created_at, id);

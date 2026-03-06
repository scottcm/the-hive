-- Reliability foundations: durable evidence ledger for TDD/review/handoff.

CREATE TABLE hive.task_evidence_artifacts (
    id                   SERIAL PRIMARY KEY,
    task_id              INTEGER NOT NULL REFERENCES hive.tasks(id) ON DELETE CASCADE,
    artifact_type        TEXT NOT NULL
                         CHECK (
                             artifact_type IN (
                                 'red_run',
                                 'implementation_commit',
                                 'green_run',
                                 'review_output',
                                 'handoff_packet'
                             )
                         ),
    artifact_hash_sha256 TEXT NOT NULL
                         CHECK (artifact_hash_sha256 ~ '^[0-9a-f]{64}$'),
    storage_ref          TEXT NOT NULL CHECK (length(trim(storage_ref)) > 0),
    captured_by          TEXT NOT NULL CHECK (length(trim(captured_by)) > 0),
    captured_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    immutable            BOOLEAN NOT NULL DEFAULT true,
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb
                         CHECK (jsonb_typeof(metadata) = 'object'),
    retention_until      TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '180 days')
                         CHECK (retention_until >= captured_at),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON hive.task_evidence_artifacts (task_id, captured_at, id);
CREATE INDEX ON hive.task_evidence_artifacts (artifact_type, captured_at, id);

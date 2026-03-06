-- Reliability foundations: machine-readable task contracts.
-- Task contracts are required for task start (claim/open -> in_progress).

CREATE TABLE hive.task_contracts (
    task_id              INTEGER PRIMARY KEY REFERENCES hive.tasks(id) ON DELETE CASCADE,
    contract_version     INTEGER NOT NULL DEFAULT 1 CHECK (contract_version > 0),
    allowed_paths        TEXT[] NOT NULL CHECK (cardinality(allowed_paths) > 0),
    forbidden_paths      TEXT[] NOT NULL DEFAULT '{}',
    dependencies         INTEGER[] NOT NULL DEFAULT '{}',
    required_tests       JSONB NOT NULL,
    review_policy        JSONB NOT NULL,
    handoff_template     TEXT NOT NULL CHECK (length(trim(handoff_template)) > 0),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON hive.task_contracts USING GIN (dependencies);

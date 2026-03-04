CREATE SCHEMA IF NOT EXISTS hive;

CREATE TABLE hive.sections (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    priority    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'done', 'archived')),
    assigned_to TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hive.tasks (
    id             SERIAL PRIMARY KEY,
    section_id     INTEGER REFERENCES hive.sections(id),
    title          TEXT NOT NULL,
    description    TEXT,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'in_progress', 'blocked', 'done', 'cancelled')),
    priority       INTEGER NOT NULL DEFAULT 0,
    sequence_order INTEGER NOT NULL DEFAULT 0,
    assigned_to    TEXT,
    github_issue   INTEGER,
    relevant_docs  TEXT[] NOT NULL DEFAULT '{}',
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hive.clarifications (
    id          SERIAL PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES hive.tasks(id),
    asked_by    TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'answered')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    answered_at TIMESTAMPTZ
);

CREATE INDEX ON hive.tasks(status);
CREATE INDEX ON hive.tasks(assigned_to);
CREATE INDEX ON hive.tasks(section_id, sequence_order);
CREATE INDEX ON hive.clarifications(task_id);
CREATE INDEX ON hive.clarifications(status);

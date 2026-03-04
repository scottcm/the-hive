-- v4 schema: add projects as top-level container
-- Projects are repo-agnostic groupings (maps to GitHub repos initially).
-- Milestones belong to a project.

CREATE TABLE hive.projects (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE hive.milestones ADD COLUMN project_id INTEGER REFERENCES hive.projects(id);

CREATE INDEX ON hive.milestones(project_id);

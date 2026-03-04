-- Task dependency gates: tasks can declare dependencies on other tasks.
-- An agent cannot claim a task until all its dependencies are done/cancelled.

ALTER TABLE hive.tasks
    ADD COLUMN depends_on INTEGER[] NOT NULL DEFAULT '{}';

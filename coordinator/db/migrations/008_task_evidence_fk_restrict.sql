-- Prevent silent evidence deletion through task-row cascade.
-- Evidence purge must be explicit and policy-controlled.

ALTER TABLE hive.task_evidence_artifacts
    DROP CONSTRAINT IF EXISTS task_evidence_artifacts_task_id_fkey;

ALTER TABLE hive.task_evidence_artifacts
    ADD CONSTRAINT task_evidence_artifacts_task_id_fkey
    FOREIGN KEY (task_id)
    REFERENCES hive.tasks(id)
    ON DELETE RESTRICT;

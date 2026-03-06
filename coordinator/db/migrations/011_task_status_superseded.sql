-- Add 'superseded' as a valid task status.

ALTER TABLE hive.tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE hive.tasks ADD CONSTRAINT tasks_status_check
    CHECK (status IN ('open', 'in_progress', 'blocked', 'done', 'cancelled', 'superseded'));

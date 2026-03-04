-- v3 schema: section → milestone rename, tags, multiple github issues
-- - Renamed sections table to milestones
-- - Renamed tasks.section_id to milestone_id
-- - Added tasks.tags (freeform text array for subsystem tagging)
-- - Changed tasks.github_issue (single int) to github_issues (int array)

ALTER TABLE hive.sections RENAME TO milestones;

ALTER TABLE hive.tasks RENAME COLUMN section_id TO milestone_id;

ALTER TABLE hive.tasks ADD COLUMN tags TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE hive.tasks ADD COLUMN github_issues INTEGER[] NOT NULL DEFAULT '{}';

-- Migrate existing single github_issue to github_issues array
UPDATE hive.tasks
SET github_issues = ARRAY[github_issue]
WHERE github_issue IS NOT NULL;

ALTER TABLE hive.tasks DROP COLUMN github_issue;

-- Rebuild index with new column name
DROP INDEX IF EXISTS hive.tasks_section_id_sequence_order_idx;
CREATE INDEX ON hive.tasks(milestone_id, sequence_order);

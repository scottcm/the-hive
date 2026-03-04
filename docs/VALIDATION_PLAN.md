# The Hive — Validation Plan

Manual validation of the hive coordination system using the dashboard
project as the test vehicle. Each test exercises a specific hive feature
through the MCP tools.

## Prerequisites

- Docker image rebuilt with latest code (`docker build -t the-hive-mcp .`)
- Hive DB seeded with dashboard tasks (`python scripts/seed_dashboard_tasks.py`)
- MCP server accessible to at least one agent session
- Agent bootstrap prompt (`prompts/agent-bootstrap.md`) loaded

## Test Sequence

Tests are ordered to build on each other. Earlier tests set up state
that later tests depend on.

### T1: Agent startup — empty session

**Feature**: `get_current_task`, `get_next_task`

**Steps**:

1. Start a new agent session with identity `test-1`
2. Agent calls `get_current_task(assigned_to="test-1")`
3. Expect: `None` (no tasks assigned to this identity)
4. Agent calls `get_next_task(assigned_to="test-1")`
5. Expect: returns task 4 ("FastAPI scaffold + project/milestone API")
   — the only task with no unmet dependencies

**Validates**: Bootstrap flow works. Dependency filtering excludes
tasks 5-9 (all have unmet deps).

### T2: Dependency gate — blocked claim

**Feature**: `claim_task` dependency enforcement

**Steps**:

1. Agent calls `claim_task(task_id=5, assigned_to="test-1")`
2. Expect: `ValueError` with message containing "unmet dependencies"
   and "#4 (open)"
3. Agent calls `claim_task(task_id=7, assigned_to="test-1")`
4. Expect: `ValueError` listing both #4 and #5 as blockers

**Validates**: Dependency gates block claiming. Error messages list
specific blockers with their current status.

### T3: Claim and work — happy path

**Feature**: `claim_task`, `add_note`

**Steps**:

1. Agent calls `claim_task(task_id=4, assigned_to="test-1")`
2. Expect: task returned with `status="in_progress"`,
   `assigned_to="test-1"`, full shape (notes, clarifications)
3. Agent calls `add_note(task_id=4, author="test-1", content="Starting FastAPI scaffold")`
4. Expect: note returned with `author="test-1"`, timestamp
5. Agent calls `get_current_task(assigned_to="test-1")`
6. Expect: returns task 4 with the note in `notes[]`

**Validates**: Claim sets status and assignee. Notes persist and
appear in task detail.

### T4: Clarification — blocking question

**Feature**: `create_clarification`, task auto-block

**Steps**:

1. Agent calls `create_clarification(task_id=4,
   asked_by="test-1",
   question="Should we use uvicorn or hypercorn?")`
2. Expect: clarification returned with `status="pending"`
3. Agent calls `get_current_task(assigned_to="test-1")`
4. Expect: task 4 now has `status="blocked"` and the clarification
   in `pending_clarifications[]`

**Validates**: Creating a clarification auto-blocks the task.

### T5: Answer clarification — auto-unblock

**Feature**: `answer_clarification`, task auto-unblock

**Steps**:

1. Call `answer_clarification(clarification_id=<id from T4>,
   answer="Use uvicorn, per design doc")`
2. Expect: clarification returned with `status="answered"`,
   `answered_at` set
3. Call `get_current_task(assigned_to="test-1")`
4. Expect: task 4 back to `status="open"` (auto-unblocked because
   no remaining pending clarifications)

**Validates**: Answering the last pending clarification auto-unblocks
the task.

### T6: List and filter

**Feature**: `list_tasks`, `list_milestones`, `list_projects`,
`list_clarifications`

**Steps**:

1. Call `list_projects()` — expect 1 project ("the-hive")
2. Call `list_milestones(project_id=1)` — expect "API Backend"
   (priority 10) and "Dashboard Frontend" (priority 5), ordered by
   priority desc
3. Call `list_tasks(tag="backend")` — expect tasks 4, 5, 6
4. Call `list_tasks(tag="frontend")` — expect tasks 7, 8
5. Call `list_tasks(status="open")` — expect tasks 4-9
   (task 4 was unblocked in T5)
6. Call `list_clarifications(status="answered")` — expect the
   clarification from T4/T5

**Validates**: Filtering by project, tag, status all work. Milestone
ordering by priority works.

### T7: Complete task — dependency unlock

**Feature**: `update_task`, dependency cascade

**Steps**:

1. Call `claim_task(task_id=4, assigned_to="test-1")` (re-claim after
   unblock)
2. Call `add_note(task_id=4, author="test-1",
   content="Scaffold complete, all tests passing")`
3. Call `update_task(task_id=4, status="done")`
4. Expect: task 4 returned with `status="done"`
5. Call `get_next_task(assigned_to="test-1")`
6. Expect: returns task 5 OR task 6 (both now have deps met — task 4
   is done). Should return whichever has lower sequence_order in the
   higher-priority milestone (both are in API Backend, so task 5
   with sequence_order=2 before task 6 with sequence_order=3)
7. Call `get_next_task(assigned_to="test-2")` (different identity)
8. Expect: also returns an available task — confirming both T5 and
   T6 are available for parallel work

**Validates**: Completing a task unlocks its dependents. Parallel
tasks (T5, T6) both become available simultaneously.

### T8: Parallel agents

**Feature**: Two agents working concurrently

**Steps**:

1. Call `claim_task(task_id=5, assigned_to="test-1")`
2. Expect: success — task 5 now in_progress for test-1
3. Call `claim_task(task_id=6, assigned_to="test-2")`
4. Expect: success — task 6 now in_progress for test-2
5. Call `get_next_task(assigned_to="test-3")`
6. Expect: `None` — no open tasks with deps met (T7 needs T4+T5,
   T8 needs T5+T6, T9 needs T8; T5 and T6 are in_progress)

**Validates**: Multiple agents can claim parallel tasks. Tasks with
partially-met deps (e.g., T7 needs both T4 done AND T5 done) remain
blocked.

### T9: Release task

**Feature**: `release_task`

**Steps**:

1. Call `release_task(task_id=6)`
2. Expect: task 6 returned with `status="open"`,
   `assigned_to=null`
3. Call `get_next_task(assigned_to="test-3")`
4. Expect: returns task 6 (back in the pool)

**Validates**: Release returns a task to the open pool for other
agents.

### T10: Full pipeline — cascade to frontend

**Feature**: Multi-level dependency cascade

**Steps**:

1. Complete task 5: `update_task(task_id=5, status="done")`
2. Complete task 6: claim it, then `update_task(task_id=6, status="done")`
3. Call `get_next_task(assigned_to="test-1")`
4. Expect: returns task 7 (board view) — deps T4 and T5 both done.
   Task 8 (task detail) should also be available — deps T5 and T6
   both done.
5. Call `list_milestones(project_id=1)`
6. Expect: API Backend milestone shows `task_counts.done=3`,
   Dashboard Frontend shows `task_counts.open=3`
7. Complete tasks 7 and 8
8. Call `get_next_task(assigned_to="test-1")`
9. Expect: returns task 9 (GitHub integration) — dep T8 now done
10. Complete task 9
11. Call `get_next_task(assigned_to="test-1")`
12. Expect: `None` — all tasks done

**Validates**: Full dependency cascade works across milestones.
Task counts update correctly. System reaches quiescence when all
work is done.

### T11: Project-level view

**Feature**: `list_projects` with aggregated counts

**Steps**:

1. Call `list_projects()`
2. Expect: "the-hive" project shows `milestone_count=2` (plus any
   pre-existing milestones), `task_counts.done=6`

**Validates**: Project aggregation rolls up across milestones.

## Success Criteria

All 11 tests pass in sequence. Specific things to watch for:

- Dependency gates never let a task be claimed before its deps
  are done
- Auto-block/unblock on clarifications works correctly
- Task counts on milestones and projects are accurate after
  each state change
- `get_next_task` respects milestone priority ordering
- Multiple agents can work in parallel on independent tasks
- The full pipeline from T1 to T11 completes without manual
  DB intervention

## Reset

To re-run the validation from scratch:

```sql
TRUNCATE hive.clarifications, hive.task_notes, hive.tasks,
         hive.milestones, hive.projects
RESTART IDENTITY CASCADE;
```

Then re-seed: `python scripts/seed_dashboard_tasks.py`

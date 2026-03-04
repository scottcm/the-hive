# The Hive — Coordinator Design

## Purpose

A shared work queue for developers and AI agents. Replaces manually
maintained session files (working_memory.md, state.md, task files) with
a queryable Postgres store exposed via an MCP server.

Primary user: one developer + three AI agents (Claude, Codex, Gemini).
Designed to grow to multiple developers.

## Concepts

**Section** — a group of related tasks (e.g., "LLM Service implementation").
Has priority for cross-section ordering and a description that provides
context to agents working on tasks within it.

**Task** — a unit of work within a section. Has status, sequence order
(for ordering within a section), optional GitHub issue link, and a list
of relevant doc paths (relative to project root). Status lifecycle:
`open` → `in_progress` → `done` | `cancelled`. Can become `blocked` via
clarifications.

**Note** — a timestamped, attributed progress update on a task.
Append-only. Agents and developers add notes as work progresses.
Notes are never edited or deleted.

**Clarification** — a blocking question raised by an agent. Creating a
clarification blocks the task. When the last pending clarification on a
task is answered, the task auto-unblocks (returns to `open`).

## Database Schema

Schema name: `hive`

```sql
CREATE SCHEMA IF NOT EXISTS hive;

CREATE TABLE hive.sections (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    priority    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'done', 'archived')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hive.tasks (
    id             SERIAL PRIMARY KEY,
    section_id     INTEGER REFERENCES hive.sections(id),
    title          TEXT NOT NULL,
    description    TEXT,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'in_progress', 'blocked',
                                     'done', 'cancelled')),
    sequence_order INTEGER NOT NULL DEFAULT 0,
    assigned_to    TEXT,
    github_issue   INTEGER,
    relevant_docs  TEXT[] NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE hive.task_notes (
    id          SERIAL PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES hive.tasks(id),
    author      TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
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
CREATE INDEX ON hive.task_notes(task_id);
CREATE INDEX ON hive.clarifications(task_id);
CREATE INDEX ON hive.clarifications(status);
```

### Changes from v1 schema

- **Removed** `sections.assigned_to` — no tool used it, semantics
  undefined. Task-level assignment is sufficient.
- **Removed** `tasks.priority` — dead data. `get_next_task` ordered by
  section priority + task sequence_order, never task priority. Use
  `sequence_order` for intra-section ordering.
- **Removed** `tasks.notes` — replaced by `task_notes` table. Single
  TEXT field had no history, no attribution, each update overwrote the
  previous.
- **Added** `task_notes` table — append-only, timestamped, attributed.

## MCP Tool Contracts

All tools are async. All return plain dicts (JSON-serializable).
14 tools total: 7 task, 1 note, 3 section, 3 clarification.

### Task Tools

```python
async def get_current_task(assigned_to: str) -> dict | None
```

Returns the caller's current `in_progress` task. If none, returns their
first `open` assigned task. If none, returns `None`.

**Full task shape** (used by `get_current_task`, `claim_task`,
`release_task`, `update_task`):

```json
{
  "id": 1,
  "title": "...",
  "description": "...",
  "status": "in_progress",
  "assigned_to": "claude",
  "section_id": 2,
  "section_name": "LLM Service",
  "section_description": "Implement the LLM service provider system",
  "github_issue": 42,
  "relevant_docs": ["docs/design/LLM_SERVICE.md"],
  "sequence_order": 1,
  "notes": [
    {"id": 1, "author": "scott", "content": "Use provider pattern", "created_at": "2026-03-01T10:00:00Z"},
    {"id": 2, "author": "claude", "content": "Started implementation", "created_at": "2026-03-01T11:30:00Z"}
  ],
  "pending_clarifications": [
    {"id": 3, "question": "Which auth method?", "status": "pending"}
  ]
}
```

```python
async def get_next_task(assigned_to: str) -> dict | None
```

Returns the next available task: first checks assigned+open tasks
ordered by section priority desc then sequence_order asc, then falls
back to unassigned open tasks in the same order. Returns `None` if
nothing available.

**Summary task shape** (used by `get_next_task`, `list_tasks`,
`create_task`) — no `notes` or `pending_clarifications`:

```json
{
  "id": 1,
  "title": "...",
  "description": "...",
  "status": "open",
  "assigned_to": null,
  "section_id": 2,
  "section_name": "LLM Service",
  "section_description": "...",
  "github_issue": null,
  "relevant_docs": [],
  "sequence_order": 1
}
```

```python
async def claim_task(task_id: int, assigned_to: str) -> dict
```

Atomically sets `status='in_progress'` and `assigned_to` on a task
that is currently `open`. Returns the full task shape. Raises
`ValueError` if the task is not `open` (already claimed, blocked, done,
etc.) — the agent should call `get_next_task` again and try another.

Implementation: single `UPDATE ... WHERE id = %s AND status = 'open'
RETURNING id`. If no row returned, the claim failed.

```python
async def release_task(task_id: int) -> dict
```

Sets `status='open'` and clears `assigned_to`. Returns the updated task
(full shape). Use when an agent cannot complete a task and wants to
return it to the pool.

```python
async def list_tasks(
    assigned_to: str | None = None,
    status: str | None = None,
    section_id: int | None = None
) -> list[dict]
```

Returns matching tasks (summary shape). Ordered by section priority
desc, sequence_order asc.

```python
async def update_task(
    task_id: int,
    status: str | None = None,
    assigned_to: str | None = None
) -> dict
```

Updates the given fields. `updated_at` is always refreshed. Returns the
full task shape. Raises `ValueError` if `task_id` not found or `status`
is invalid.

Use for status transitions (`done`, `cancelled`) and reassignment.
To claim a task, use `claim_task`. To unassign, use `release_task`.

```python
async def create_task(
    title: str,
    description: str | None = None,
    section_id: int | None = None,
    assigned_to: str | None = None,
    sequence_order: int = 0,
    github_issue: int | None = None,
    relevant_docs: list[str] | None = None
) -> dict
```

Creates and returns the new task (summary shape).

### Note Tools

```python
async def add_note(task_id: int, author: str, content: str) -> dict
```

Appends a timestamped progress note to a task. Returns the note:

```json
{"id": 1, "task_id": 2, "author": "claude", "content": "...", "created_at": "2026-03-01T11:30:00Z"}
```

### Section Tools

```python
async def list_sections(status: str | None = None) -> list[dict]
```

Returns sections with task counts:

```json
{
  "id": 1,
  "name": "...",
  "description": "...",
  "priority": 10,
  "status": "active",
  "task_counts": {"open": 3, "in_progress": 1, "done": 5, "blocked": 0}
}
```

```python
async def create_section(
    name: str,
    description: str | None = None,
    priority: int = 0
) -> dict
```

Creates and returns the new section (with zero task counts).

```python
async def update_section(
    section_id: int,
    name: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    status: str | None = None
) -> dict
```

Updates the given fields. Returns the updated section (with task
counts). Raises `ValueError` if `section_id` not found or `status`
is invalid.

### Clarification Tools

```python
async def create_clarification(
    task_id: int,
    asked_by: str,
    question: str
) -> dict
```

Creates a clarification and sets the task status to `blocked`.
Returns:

```json
{"id": 1, "task_id": 2, "asked_by": "codex", "question": "...", "status": "pending"}
```

```python
async def answer_clarification(
    clarification_id: int,
    answer: str
) -> dict
```

Sets the answer, marks status `answered`, sets `answered_at`.
If no pending clarifications remain on the task, sets the task status
back to `open` so it re-enters the work queue.
Returns the updated clarification (full shape including answer and
answered_at).

```python
async def list_clarifications(
    status: str | None = None,
    task_id: int | None = None,
    asked_by: str | None = None
) -> list[dict]
```

Returns matching clarifications with task context:

```json
{
  "id": 1,
  "task_id": 2,
  "task_title": "Implement provider registration",
  "asked_by": "codex",
  "question": "Which auth method for provider endpoints?",
  "answer": null,
  "status": "pending",
  "created_at": "2026-03-01T14:00:00Z",
  "answered_at": null
}
```

Primary use: developer calls `list_clarifications(status="pending")`
to see all questions needing answers.

## Session Startup Pattern

At the start of every agent session:

```
1. get_current_task(assigned_to="<agent-name>")
2. If task returned with status "in_progress" → resume work
3. If task returned with status "open" → claim_task(id, "<agent-name>")
4. If None → get_next_task("<agent-name>")
5. If task found → claim_task(id, "<agent-name>")
6. If None → no work available
```

The task description + section description + relevant_docs provide the
context an agent needs to start work. Agents should read the files
listed in `relevant_docs` before beginning.

## Environment

- `HIVE_DB_URL` — Postgres connection string (required)
- `HIVE_TEST_DB_URL` — separate test database (required for tests)

## MCP Transport

- **Local dev**: stdio. Claude Code runs the server as a subprocess.
- **Server/Docker**: SSE at `http://host:8000/sse`.

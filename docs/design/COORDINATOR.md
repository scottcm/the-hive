# The Hive — Coordinator Design

## Purpose

A shared work queue for developers and AI agents. Replaces manually
maintained session files (working_memory.md, state.md, task files) with
a queryable Postgres store exposed via an MCP server.

Primary user: one developer + three AI agents (Claude, Codex, Gemini).
Designed to grow to multiple developers.

## Concepts

**Section** — a group of related tasks (e.g., "LLM Service implementation").
Has priority and optional assignment to a developer or agent.

**Task** — a unit of work within a section. Has a status, sequence order
(for ordering within a section), optional GitHub issue link, and a list
of relevant design doc URLs. Agents write working notes into `notes`.

**Clarification** — a question raised by an agent when blocked. The agent
creates a clarification and moves on to another task. The developer answers
it asynchronously.

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
```

## MCP Tool Contracts

All tools are async. All return plain dicts (JSON-serializable).

### Task Tools

```python
async def get_current_task(assigned_to: str) -> dict | None
```
Returns the caller's current `in_progress` task. If none, returns their
first `open` assigned task. If none, returns `None`.

Return shape:
```json
{
  "id": 1,
  "title": "...",
  "description": "...",
  "status": "in_progress",
  "assigned_to": "claude",
  "section_id": 2,
  "section_name": "LLM Service",
  "github_issue": 42,
  "relevant_docs": ["https://github.com/..."],
  "notes": "...",
  "sequence_order": 1,
  "pending_clarifications": [
    {"id": 3, "question": "...", "status": "pending"}
  ]
}
```

```python
async def get_next_task(assigned_to: str) -> dict | None
```
Returns the next available task for the caller: first checks assigned+open
tasks ordered by section priority then sequence_order, then falls back to
unassigned open tasks in the same order. Returns `None` if nothing available.
Same return shape as `get_current_task` (without `pending_clarifications`).

```python
async def list_tasks(
    assigned_to: str | None = None,
    status: str | None = None,
    section_id: int | None = None
) -> list[dict]
```
Returns matching tasks. Each item includes `section_name`. Ordered by
section priority desc, sequence_order asc.

```python
async def update_task(
    task_id: int,
    status: str | None = None,
    notes: str | None = None,
    assigned_to: str | None = None
) -> dict
```
Updates the given fields. `updated_at` is always refreshed. Returns the
updated task (same shape as `get_current_task`). Raises `ValueError` if
`task_id` not found or `status` value is invalid.

```python
async def create_task(
    title: str,
    description: str | None = None,
    section_id: int | None = None,
    assigned_to: str | None = None,
    priority: int = 0,
    sequence_order: int = 0,
    github_issue: int | None = None,
    relevant_docs: list[str] | None = None
) -> dict
```
Creates and returns the new task.

### Section Tools

```python
async def list_sections(status: str | None = None) -> list[dict]
```
Returns sections with task counts. Shape:
```json
{
  "id": 1,
  "name": "...",
  "description": "...",
  "priority": 10,
  "status": "active",
  "assigned_to": "mike",
  "task_counts": {"open": 3, "in_progress": 1, "done": 5, "blocked": 0}
}
```

```python
async def create_section(
    name: str,
    description: str | None = None,
    priority: int = 0,
    assigned_to: str | None = None
) -> dict
```
Creates and returns the new section.

### Clarification Tools

```python
async def create_clarification(
    task_id: int,
    asked_by: str,
    question: str
) -> dict
```
Creates a clarification and sets the task status to `blocked`.
Returns: `{"id": 1, "task_id": 2, "asked_by": "codex", "question": "...", "status": "pending"}`

```python
async def answer_clarification(
    clarification_id: int,
    answer: str
) -> dict
```
Sets the answer, marks status `answered`, sets `answered_at`.
Does NOT automatically unblock the task — the agent decides whether to
resume after reading the answer.
Returns the updated clarification.

## Session Startup Pattern

At the start of every agent session, call:

```
get_current_task(assigned_to="<agent-name>")
```

This replaces reading working_memory.md + state.md + task file.
If it returns a task, that is the active context. If `None`, call
`get_next_task` to find available work.

## Environment

- `HIVE_DB_URL` — Postgres connection string (required)
- `HIVE_TEST_DB_URL` — separate test database (required for tests)

## MCP Transport

- **Local dev**: stdio. Claude Code runs the server as a subprocess.
- **Server/Docker**: SSE at `http://host:8000/sse`.

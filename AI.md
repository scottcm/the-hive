# AI.md — The Hive

Quick-reference for AI agents. Read this once per session before starting work.
For hard rules and gates, see AGENTS.md. For session startup, see prompts/agent-bootstrap.md.

## What This System Is

The Hive is a shared work coordination system for a developer + multiple AI agents.
It is a Postgres-backed task queue exposed via an MCP server and a FastAPI REST API.
Agents claim tasks, do work, record evidence, and complete tasks through enforced gates.

## Tech Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.12+ |
| DB | Postgres (schema: `hive`), psycopg3 async |
| MCP server | FastMCP (`mcp>=1.0`) |
| REST API | FastAPI + uvicorn |
| Frontend | Svelte SPA (dashboard/) |
| Tests | pytest + pytest-asyncio |

## Codebase Map

```
coordinator/
  mcp/tools/
    tasks.py          # task CRUD, gate engine (G1-G5), contracts, evidence, overrides
    evidence.py       # evidence artifact storage
    clarifications.py # clarification CRUD + auto-block/unblock
    notes.py          # task notes
    projects.py       # project CRUD
    milestones.py     # milestone CRUD
  mcp/server.py       # FastMCP server entry point
  web/app.py          # FastAPI app + lifespan (DB pool)
  web/routes/         # REST route handlers (call mcp/tools/* directly)
  db/
    migrate.py        # migration runner
    migrations/       # numbered SQL migrations (001–010)
    connection.py     # async pool setup
  models.py           # shared model types
tests/
  test_mcp_tasks.py   # primary gate/contract/evidence test suite (56 tests)
  test_mcp_evidence.py
  test_web_tasks.py
  test_web_*.py
dashboard/            # Svelte SPA
docs/
  design/COORDINATOR.md           # system concepts and DB schema
  design/DASHBOARD.md             # UI design
  architecture/RELIABILITY_EXECUTION_DESIGN.md  # gate policy design (source of truth)
  VALIDATION_PLAN.md              # manual validation steps (human reference, not agent rules)
prompts/agent-bootstrap.md        # session startup instructions
```

## Key Concepts

**Task states:** `open` → `in_progress` → `done` | `superseded`; can become `blocked`

**Done gate (G1-G5):** all five must pass (or have an active override) before `update_task(status="done")` succeeds:
- G1 Scope lock — changed files match contract allow-list
- G2 TDD order — RED evidence before first implementation commit
- G3 Verification — required green test commands have passing evidence
- G4 Review separation — at least one reviewer != author
- G5 Handoff completeness — handoff_packet with valid schema (str + list field types enforced)

**Task contract:** required before a task can be claimed or moved to `in_progress`.
Fields: `allowed_paths`, `forbidden_paths`, `dependencies`, `red_tests`, `green_tests`, `review_policy`, `handoff_template`.

**Evidence artifacts:** immutable records attached to tasks.
Types: `red_run`, `implementation_commit`, `green_run`, `review_output`, `handoff_packet`.
Required fields: `artifact_hash_sha256`, `storage_ref`, `captured_by`, `metadata`.

**Handoff packet metadata schema:**
- strings: `what_changed`, `why_changed`
- lists: `residual_risks`, `unresolved_questions`, `verification_links`, `next_actions`

**Overrides:** gate failures can be overridden with actor + reason + expiry. Recorded in `hive.task_overrides`.

## DB Migrations (current)

| # | Description |
|---|-------------|
| 001–005 | Core schema: projects, milestones, tasks, notes, clarifications, deps |
| 006 | task_contracts |
| 007–008 | task_evidence_artifacts + FK restrict |
| 009 | task_gate_events |
| 010 | task_overrides |

## Current Milestones

| ID | Name | Status |
|----|------|--------|
| 1 | API Backend | active |
| 2 | Dashboard Frontend | active |
| 3 | Reliability Foundations | active |

## Anti-Patterns (don't do these)

- Do not mark a task `done` before its review companion task is complete.
- Do not edit files outside your task contract's `allowed_paths`.
- Do not record GREEN evidence before RED evidence.
- Do not self-review (reviewer identity must differ from author).
- Do not add `Co-Authored-By` to commits.
- Do not skip the task contract — claim will fail without one.

## Where to Find More

| Question | Read |
|----------|------|
| Hard agent rules and gates | AGENTS.md |
| Full gate policy design | docs/architecture/RELIABILITY_EXECUTION_DESIGN.md |
| DB schema and concepts | docs/design/COORDINATOR.md |
| Dashboard UI spec | docs/design/DASHBOARD.md |
| Manual system validation steps | docs/VALIDATION_PLAN.md |

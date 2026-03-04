# The Hive — Dashboard Design

## Purpose

Web UI for the-hive coordination system. Provides human visibility into
agent work, answers pending clarifications, and manages
projects/milestones/tasks. Agents interact via MCP tools; humans interact
via the dashboard.

## Use Cases

**UC-1: Status check** — Open the board, see all active milestones
within a project, task statuses, who's working on what, and what's
blocked. No clicks required beyond loading the page.

**UC-2: Answer clarifications** — See a banner showing pending
clarification count. Navigate to the blocked task, read the question,
type an answer. Task auto-unblocks.

**UC-3: Create and organize work** — Create projects, milestones within
them, and tasks within milestones. Assign to agents, set sequence order,
link GitHub issues, add tags.

**UC-4: Monitor progress** — Read agent notes on tasks to understand
what they've done, what they're stuck on, and what they plan next.

**UC-5: Manage task lifecycle** — Change task status, reassign tasks,
release tasks back to the pool. Close issues from the task detail page.

**UC-6: GitHub context** — See linked issues and PRs with live status
(open/closed, CI pass/fail) without leaving the dashboard. Close issues
directly from the task detail page.

**UC-7: Project management** — Create projects, edit name/description,
archive completed projects. Switch between projects on the board view.

## Tech Stack

**Backend**: FastAPI — serves the API and static files. Connects to the
same Postgres database as the MCP server. Runs as a separate process
(not inside the MCP server).

**Frontend**: Svelte SPA — component-based, reactive, minimal
boilerplate. Chosen over HTMX for future agent coordination UI
(real-time updates, complex state management).

**Why SPA**: The dashboard will eventually support real-time agent
coordination (WebSocket updates, live task claiming, agent status).
HTMX is simpler for static CRUD but doesn't scale to that interaction
model.

## Views

### Board View

The primary view. Shows milestones and tasks within the selected project.

**Layout**:

- Header: app title, project selector dropdown, "+ Project",
  "+ Milestone", and "+ Task" buttons
- Clarification banner (only when pending count > 0): count + "Review"
  button
- Filter bar: status, assignee, tag dropdowns + task count summary
- Milestone groups (collapsible):
  - Header: name, description, task count summary. Click to
    collapse/expand.
  - Active milestones default expanded, completed milestones default
    collapsed (faded).
  - Task cards: ID, title, tags (color-coded), GitHub issue links,
    status badge, assignee (color-coded dot + name), blocked indicator
  - Each task card links to its task detail page

**Mockup**: `mockups/board.html`

### Task Detail View

Opened by clicking a task card on the board.

**Layout**:

- Header: back link to board, task title + ID, Edit and Release buttons
- Two-column: main content (left) + sidebar (right)
- Main content has two tabs:
  - **Context tab**: description, relevant docs (clickable paths),
    GitHub section (issues with close buttons, PRs, CI status)
  - **Activity tab**: pending clarifications (with answer textarea),
    answered clarifications, notes timeline (with add-note input).
    Badge on tab shows pending clarification count.
- Sidebar: status dropdown, assignee dropdown, project name, milestone
  name, tags, sequence order, linked GitHub issues, created/updated
  timestamps

**Mockup**: `mockups/task-detail.html`

## API Design

The dashboard backend exposes a REST API. All endpoints return JSON.
The API reads from and writes to the same `hive` schema as the MCP
tools.

### Project Endpoints

```
GET    /api/projects                — list (optional ?status= filter)
POST   /api/projects                — create
PATCH  /api/projects/:id            — update (name, description, status)
```

### Milestone Endpoints

```
GET    /api/milestones              — list (optional ?status=, ?project_id=)
POST   /api/milestones              — create (with optional project_id)
PATCH  /api/milestones/:id          — update
```

### Task Endpoints

```
GET    /api/tasks                   — list (optional ?status=, ?assignee=, ?milestone_id=, ?tag=)
POST   /api/tasks                   — create
GET    /api/tasks/:id               — get full task (with notes + clarifications)
PATCH  /api/tasks/:id               — update status, assignee, etc.
POST   /api/tasks/:id/claim         — claim (set in_progress + assignee)
POST   /api/tasks/:id/release       — release (set open + clear assignee)
POST   /api/tasks/:id/notes         — add note
```

### Clarification Endpoints

```
GET    /api/clarifications          — list (optional ?status=, ?task_id=)
POST   /api/clarifications          — create
PATCH  /api/clarifications/:id      — answer
```

### GitHub Proxy (future)

```
POST   /api/github/issues/:number/close  — close issue via GitHub API
```

GitHub operations go through the backend to keep tokens server-side.

## Implementation Slicing

Following the Agent Playbook: slice vertically, each slice delivers a
working tested unit. Design decisions (project layout, packages,
interfaces) are resolved here before agents touch code.

### Slice 1: FastAPI scaffold + project/milestone API

- FastAPI app with lifespan (DB pool)
- Project CRUD endpoints (reuse `coordinator.mcp.tools.projects`)
- Milestone CRUD endpoints (reuse `coordinator.mcp.tools.milestones`)
- Tests against test database
- Static file serving setup (empty placeholder)

### Slice 2: Task API

- Task CRUD endpoints including claim/release
- Note creation endpoint
- Full task detail endpoint (notes + clarifications)
- Tag filtering

### Slice 3: Clarification API

- Clarification CRUD endpoints
- Answer endpoint (with auto-unblock logic)
- Pending clarification count endpoint (for banner)

### Slice 4: Svelte scaffold + board view

- Svelte project setup (Vite + SvelteKit or plain Svelte)
- Project selector dropdown (fetches projects, filters board)
- Board view component: fetch milestones + tasks for selected project,
  render grouped cards
- Collapsible milestone groups
- Filter bar (status, assignee, tag)
- Clarification banner

### Slice 5: Task detail view

- Task detail component with Context/Activity tabs
- Context tab: description, docs, GitHub section
- Activity tab: clarifications (read + answer), notes (read + add)
- Sidebar with editable fields (status, assignee)
- Dependency display: "Blocked by" list (links to blocker tasks),
  "Blocks" list (reverse lookup — tasks that depend on this one)

### Slice 6: GitHub integration

- Close issue button (calls backend proxy)
- Live issue/PR status display
- CI status display

## Project Layout

```
the-hive/
├── coordinator/
│   ├── db/           # existing — shared with MCP server
│   ├── mcp/          # existing — MCP tool layer
│   └── web/          # NEW — FastAPI app
│       ├── app.py    # FastAPI app + lifespan
│       └── routes/   # route modules (projects, milestones, tasks, clarifications)
├── dashboard/        # NEW — Svelte frontend
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── docs/
├── mockups/
└── tests/
    └── test_web_*.py # NEW — API tests
```

The web layer imports from `coordinator.db` directly — same connection
pool, same database. No duplication of query logic; the MCP tools and
web routes share the same data access functions.

## Decisions

**Shared data access**: The web routes call the same async functions in
`coordinator.mcp.tools.*` that the MCP tools use. This avoids
duplicating SQL queries and ensures consistency. The MCP tool functions
are pure async functions that return dicts — they don't depend on the
MCP framework.

**Separate process**: The dashboard runs as its own process
(`uvicorn coordinator.web.app:app`), not inside the MCP server. This
keeps the MCP server lightweight (stdio) and lets the dashboard serve
HTTP independently.

**No auth (v1)**: Single-user, local-network tool. No authentication
in the first version. Add when multi-user support is needed.

**No WebSocket (v1)**: Polling or manual refresh for now. WebSocket
for real-time updates is a future slice when agent coordination UI
is built.

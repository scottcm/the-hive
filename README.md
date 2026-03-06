# The Hive — Coordinator

Work coordination for AI-assisted development teams.

Provides an MCP server that lets developers and AI agents query and update
a shared work queue: what to work on next, task status, clarification
requests, and section-level planning.

## Setup

```bash
cp .env.example .env
# edit .env: set HIVE_DB_URL
uv sync --extra dev
uv run python -m coordinator.db.migrate
```

## Run (local, stdio transport)

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "hive": {
      "command": "uv",
      "args": ["run", "python", "-m", "coordinator.mcp.server"],
      "cwd": "/path/to/the-hive"
    }
  }
}
```

## Run (Docker, SSE transport)

```bash
docker compose up
```

## Test

```bash
./scripts/run-tests.ps1 tests/ -v
```

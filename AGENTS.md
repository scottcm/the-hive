# AGENTS.md

Rules for all AI agents working on the-hive.

Read AI.md for system context, codebase map, and key concepts.

## Hard Requirements (Non-Negotiable)

1. **Scope lock.** Edit only files listed in your prompt.
   If you notice unrelated issues, record them as findings — do not fix them.
2. **TDD required.** Tests must fail (RED) before implementation.
   Paste RED output as proof before writing implementation code.
3. **Ask clarifying questions first.** If any requirement is ambiguous,
   stop and ask before writing code. Only ask questions not answered by the prompt.
4. **If any hard requirement is violated, stop, report the violation, and wait.**

## Gates

### Gate 1: Scope

Before committing, verify no out-of-scope files were modified:

```bash
git diff --name-only HEAD
```

### Gate 2: Tests Pass

Paste full pytest output. All tests must pass with zero failures.
Preferred test runner in this repo: `./scripts/run-tests.ps1`.
If a task marked `done` later shows test failures, immediately move it back to
`in_progress` (or `changes_requested`) and attach failure evidence before any
new implementation work.

### Gate 3: Self-Audit

Complete this table in your final response:

| Check | Command | Output |
|-------|---------|--------|
| All tests pass | `pytest tests/ -v` | |
| No scope creep | `git diff --name-only HEAD` | |
| Commit hash | `git log --oneline -1` | |

## Conventions

- Python 3.12+
- `psycopg[binary]>=3.2` for Postgres (psycopg3 async API)
- `mcp>=1.0` (FastMCP) for the MCP server
- `pytest` + `pytest-asyncio` for tests
- Type annotations on all public functions and methods
- UTF-8 without BOM, LF line endings
- Commit messages: `type(scope): message` (feat, fix, test, chore, doc)
- No docstrings unless the logic is non-obvious
- No unused imports

# AGENTS.md

Rules for all AI agents working on the-hive.

## Hard Requirements (Non-Negotiable)

1. **Never commit to `main`.** All work goes on a feature branch.
2. **Scope lock.** Edit only files listed in your prompt.
   If you notice unrelated issues, record them as findings — do not fix them.
3. **TDD required.** Tests must fail (RED) before implementation.
   Paste RED output as proof before writing implementation code.
4. **Ask clarifying questions first.** If any requirement is ambiguous,
   stop and ask before writing code. Only ask questions not answered by the prompt.
5. **If any hard requirement is violated, stop, report the violation, and wait.**

## Gates

### Gate 1: Branch

Run and paste output before any edits:

```bash
git rev-parse --abbrev-ref HEAD
```

Output must show your feature branch, not `main`.

### Gate 2: Scope

Before committing, verify no out-of-scope files were modified:

```bash
git diff --name-only HEAD
```

### Gate 3: Tests Pass

Paste full pytest output. All tests must pass with zero failures.

### Gate 4: Self-Audit

Complete this table in your final response:

| Check | Command | Output |
|-------|---------|--------|
| Branch is not main | `git rev-parse --abbrev-ref HEAD` | |
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

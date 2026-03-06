# V1_DESIGN.md — Final Readiness Review

| Field | Value |
| --- | --- |
| Document | `docs/architecture/V1_DESIGN.md` |
| Reviewed by | claude-scott |
| Date | 2026-03-06 |
| Verdict | **READY** |

## Scope

Strict final-gate review. Only migration-breaking or logic-impossible issues
qualify as blockers. Style, naming, and non-blocking inconsistencies are omitted.

## Blockers found and resolved

### B1 — `blocked` status requires claim fields (resolved)

**Finding:** `tasks_claim_state_check` placed `blocked` only in the claim-present
branch, but v0.9 clarification auto-block can block unclaimed tasks.

**Fix:** Added `'blocked'` to the claim-absent branch so it appears in both.

### B2 — `created_by NOT NULL` ALTER on populated table (resolved)

**Finding:** `ADD COLUMN created_by text NOT NULL` fails on populated tables.

**Fix:** Column added as nullable; migration section 13 now documents explicit
three-step sequence: add nullable, backfill, `ALTER COLUMN created_by SET NOT NULL`.

### B3 — Status constraint discovery is ambiguous (resolved)

**Finding:** `LIKE '%status IN%'` matched both the old status CHECK and the new
`tasks_claim_state_check`.

**Fix:** Changed to `LIKE '%cancelled%'` which uniquely identifies the v0.9
status constraint.

## Additional fixes applied

- Section 7.2 cross-reference corrected: `section 8.11` -> `section 8.12` for
  the identity audit table.
- `heartbeat_expired` confirmed as audit event only (in `task_gate_events`,
  not in `task_overrides`).
- v1 ownership write restrictions explicitly labeled as cooperative policy
  (v2 auth/RBAC will enforce).

## Verdict

All blockers resolved. Design is internally consistent and migration-safe.
**READY** for implementation task creation.

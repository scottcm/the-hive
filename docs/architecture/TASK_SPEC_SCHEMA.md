# Task Spec Schema — v1.0

Status: Draft
Date: 2026-03-07
Referenced from: V1_DESIGN.md Section 7.4

---

## Purpose

V1_DESIGN.md defines `task_spec` as a schema-validated JSONB column (Section
8.6, max 64 KB). This document specifies the required and optional keys within
`task_spec` for each `task_type`, plus the evidence and output contracts that
agents must satisfy.

`create_task` validates `task_spec` against these schemas at creation time.
`validate_spec` (Section 9) also accepts `task_spec` payloads for pre-flight
validation.

---

## 1. Common Keys (All Task Types)

These keys are available in every `task_spec` regardless of `task_type`.

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `description` | string | Yes | Human/agent-readable summary of what the task accomplishes |
| `mutation_policy` | object | No | Permissions for what the agent may modify (see Section 2) |
| `failure_policy` | object | No | What to do on blockers (see Section 3) |
| `output_contract` | object | No | Required response/evidence format (see Section 4) |

Keys from V1_DESIGN.md that live on the task record itself (not inside
`task_spec`):

- `context` — background information (task column, §8.6)
- `acceptance_criteria` — concrete done checks (task column, §8.6)
- `allowed_paths` / `forbidden_paths` — scope lock (task contract, G1)
- `handoff_template` — handoff format (task contract, G5)
- `execution_policy` — workspace/branch policy and completion actions (task
  column, §7.8). Includes `on_complete` (push_and_pr / push_only / none),
  `target_branch`, `auto_merge`, `pr_title_template`, `delete_branch_on_merge`.

These are not duplicated in `task_spec`. The spec complements these fields
with type-specific execution details.

**Field precedence.** `task_spec.description` is the machine-consumable
execution summary agents use for task execution. `task.context` provides
background information. If the v0.9 `task.description` column still exists
after migration, it is superseded by `task_spec.description` for agent
execution.

---

## 2. Mutation Policy

Controls what the agent is permitted to modify during task execution.
Declared in `task_spec.mutation_policy`. Defaults apply when omitted.

```json
{
  "mutation_policy": {
    "mode": "write_allowed",
    "allow_git": true,
    "allow_status_update": true,
    "allow_notes": true,
    "allow_file_creation": true
  }
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `mode` | `"write_allowed"` or `"read_only"` | `"write_allowed"` | Base permission level. `read_only` means the agent may not modify repo files (appropriate for review tasks). |
| `allow_git` | boolean | `true` | Whether the agent may create commits, branches, or push. Typically `false` for review tasks. |
| `allow_status_update` | boolean | `true` | Whether the agent may call `update_task` to change status fields. |
| `allow_notes` | boolean | `true` | Whether the agent may add notes/comments to the task. |
| `allow_file_creation` | boolean | `true` | Whether the agent may create new files (vs only editing existing). Restricted by `allowed_paths` regardless. |

**Review tasks default to `read_only`.** When `task_type = review` and
`mutation_policy` is omitted, the effective defaults are:
`mode: read_only`, `allow_git: false`, `allow_file_creation: false`,
`allow_status_update: true`, `allow_notes: true`.

`allow_status_update` remains `true` for review tasks because the reviewer
must be able to move the review task to `done` (on approval) or release it
to `open` (on changes requested). The reviewer cannot modify the **parent**
implementation task's status — that is enforced by claim ownership
(`update_task(status=done)` requires a valid `claim_token` for the target
task, which the reviewer does not hold for the parent).

**v1.0 threat model.** Mutation policy is enforced cooperatively in v1.0 —
agents are expected to respect it, and the API does not block violations.
This is acceptable because v1.0 operates within a trusted deployment
boundary: all agents are deployed by the same operator, and the MCP API
is not exposed to untrusted callers. A malicious or misconfigured agent
could ignore `read_only` mode and modify files. Mitigations: (1) G1 scope
lock rejects out-of-scope changes at completion regardless of mutation
policy, (2) git history provides an audit trail, (3) review tasks catch
unauthorized modifications. v2 auth/RBAC will enforce mutation policy at
the API level.

---

## 3. Failure Policy

Declares what the agent should do when it encounters blockers before or
during execution. Declared in `task_spec.failure_policy`.

```json
{
  "failure_policy": {
    "on_dirty_worktree": "abort_and_clarify",
    "on_failing_baseline_tests": "abort_and_clarify",
    "on_missing_dependency": "clarify",
    "on_scope_violation": "abort_and_clarify",
    "default": "clarify"
  }
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `on_dirty_worktree` | action | `"abort_and_clarify"` | Worktree has uncommitted changes at task start |
| `on_failing_baseline_tests` | action | `"abort_and_clarify"` | Tests fail before the agent makes any changes |
| `on_missing_dependency` | action | `"clarify"` | A required file, module, or migration is missing |
| `on_scope_violation` | action | `"abort_and_clarify"` | Agent discovers it needs files outside `allowed_paths` |
| `default` | action | `"clarify"` | Fallback for unlisted blocker types |

**Actions:**

| Action | Behavior |
|--------|----------|
| `"clarify"` | Raise a clarification (task blocks, claim preserved) |
| `"abort"` | Release the task claim (`release_task`), return to `open` |
| `"abort_and_clarify"` | Release claim and raise a clarification explaining the blocker |
| `"skip"` | Log the issue as a note but continue execution |

**Non-skippable blockers.** `on_scope_violation` does not accept `"skip"` —
scope violations are non-skippable because G1 will reject the task at
completion regardless. Valid actions for `on_scope_violation` are `"abort"`,
`"clarify"`, or `"abort_and_clarify"`. `create_task` rejects a failure policy
that sets `on_scope_violation` to `"skip"`. All other blocker types accept
all four actions.

**`abort_and_clarify` operation order.** `abort_and_clarify` executes as:
(1) create clarification (task transitions to `blocked`, claim preserved),
(2) `release_task` (claim cleared, task stays `blocked`-unclaimed). This
ensures the clarification is associated with the task context before the
claim is released.

---

## 4. Output Contract

Declares the required format for the agent's output — both evidence
artifacts and any structured response. Declared in `task_spec.output_contract`.

```json
{
  "output_contract": {
    "required_evidence": ["implementation_diff", "test_results"],
    "optional_evidence": ["performance_benchmarks"],
    "response_format": "structured",
    "findings_order": "severity_desc",
    "require_file_line_refs": true,
    "require_verdict": true
  }
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `required_evidence` | string[] | (per task type) | Evidence artifact types that must be recorded before `done` |
| `optional_evidence` | string[] | `[]` | Evidence types that may be recorded but are not gate-blocking |
| `response_format` | `"structured"` or `"freeform"` | `"structured"` | Whether findings must follow the structured format |
| `findings_order` | `"severity_desc"` or `"file_order"` | `"severity_desc"` | How findings should be ordered in review output |
| `require_file_line_refs` | boolean | `false` | Whether findings must include `file:line` references |
| `require_verdict` | boolean | `false` | Whether a final verdict (`approved` / `changes_requested`) is required |

**Enforcement points.** Output contract validation occurs at two stages:

1. **At `record_task_evidence` write time** — schema validation for structured
   evidence types. For example, `review_output` must contain a valid `verdict`
   field, and `file:line` references when `require_file_line_refs = true`.
   Malformed evidence is rejected at write time with a validation error.
2. **At `update_task(status=done)` gate evaluation** — the gate engine checks
   that all `required_evidence` types have been recorded before allowing the
   transition. Missing required evidence blocks the `done` transition.

This two-stage approach catches format errors early (at write) while deferring
completeness checks to the done gate (allowing agents to record evidence in
any order).

---

## 5. Task Type: `implementation`

Implementation tasks produce code changes.

### Required `task_spec` keys

| Key | Type | Description |
|-----|------|-------------|
| `description` | string | What to implement |

### Optional `task_spec` keys

| Key | Type | Description |
|-----|------|-------------|
| `branch` | string | Target branch name (overrides `execution_policy.branch_name_template`) |
| `base_sha` | string | Base commit SHA to branch from |
| `mutation_policy` | object | Defaults: `mode: write_allowed`, all permissions `true` |
| `failure_policy` | object | Defaults: see Section 3 |
| `output_contract` | object | Defaults: `required_evidence: ["implementation_diff", "test_results"]` |

### Default evidence contract

| Evidence type | Required | Description |
|---------------|----------|-------------|
| `implementation_diff` | Yes | Git diff or commit SHA of changes |
| `test_results` | Yes | Test output showing RED then GREEN (G2) |
| `self_audit` | Yes | G3 verification checklist |
| `handoff` | Yes | G5 handoff note (format from `handoff_template`) |
| `pr_url` | When `on_complete = push_and_pr` | URL of the created pull request |

### Default output contract

```json
{
  "required_evidence": ["implementation_diff", "test_results", "self_audit", "handoff"],
  "response_format": "freeform"
}
```

When `execution_policy.on_complete = push_and_pr`, `pr_url` is added to
`required_evidence` automatically.

---

## 6. Task Type: `review`

Review tasks evaluate an implementation task's changes. The agent operates
in read-only mode by default and produces structured findings.

### Required `task_spec` keys

| Key | Type | Description |
|-----|------|-------------|
| `description` | string | Review scope and focus areas |
| `review_ref` | string | Branch name or commit SHA of the implementation to review. Enforced by `create_task` (V1_DESIGN.md §7.6). |

### Optional `task_spec` keys

| Key | Type | Description |
|-----|------|-------------|
| `base_sha` | string | Base commit for diffing. If omitted, the reviewer diffs `review_ref` against the parent task's branch point or `main`. |
| `review_scope` | string[] | File globs to focus the review on. If omitted, review covers the full diff. |
| `mutation_policy` | object | Defaults: `mode: read_only`, `allow_git: false` |
| `failure_policy` | object | Defaults: see Section 3 |
| `output_contract` | object | Defaults: structured, severity-ordered, verdict required |

### Default evidence contract

| Evidence type | Required | Description |
|---------------|----------|-------------|
| `review_output` | Yes | Structured findings with verdict (`approved` or `changes_requested`) |

### Default output contract

```json
{
  "required_evidence": ["review_output"],
  "response_format": "structured",
  "findings_order": "severity_desc",
  "require_file_line_refs": true,
  "require_verdict": true
}
```

### Review output structure

`review_output` evidence artifacts must contain:

```json
{
  "verdict": "approved | changes_requested",
  "findings": [
    {
      "severity": "critical | major | minor | nit",
      "file": "path/to/file.py",
      "line": 42,
      "description": "What is wrong or risky",
      "suggestion": "How to fix it (optional)"
    }
  ],
  "summary": "Overall assessment"
}
```

**Canonical severity vocabulary.** Review findings use the four-level scale
`critical | major | minor | nit`. This is the only accepted vocabulary for
`review_output.findings[].severity`. Design and project documents that use
`medium` or `low` outside of review output should map to this scale:
`medium` → `minor`, `low` → `nit`.

---

## 7. Task Type: `misc`

Miscellaneous tasks with no predefined contract. Used for documentation,
research, planning, or other non-code work.

### Required `task_spec` keys

| Key | Type | Description |
|-----|------|-------------|
| `description` | string | What the task accomplishes |

### Optional `task_spec` keys

All common keys (Section 1) are available. No type-specific keys.

### Default evidence contract

No evidence types are required by default. The task creator should specify
`output_contract.required_evidence` explicitly if evidence is expected.

---

## 8. Decision Authority

Decision authority is derived from existing V1_DESIGN.md mechanisms, not
from `task_spec` fields. This section documents the rules for clarity.

| Action | Who can do it | Mechanism |
|--------|--------------|-----------|
| Move to `done` | Claiming agent (with valid `claim_token` + `claim_session_id`) | §7.4a, §9 `update_task` |
| Move to `open` (release) | Claiming agent, recovery job, session end | §9 `release_task`, §7.9 |
| Move to `superseded` | Any agent with task context | §9 `supersede_task` |
| Move to `open` (reopen) | Any agent with reason | §9 `reopen_task` |
| Update routing fields | Task creator or project/milestone owner | §7.4 write restrictions |
| Record evidence | Claiming agent only (active session + claim token) | §9 `record_task_evidence` |
| Create clarification | Any agent (task must be non-terminal) | §7.7a |
| Answer clarification | Routed-to principal | §7.7 |

Reviewers cannot directly change the parent implementation task's status.
A review verdict of `changes_requested` releases the *review* task's claim
(review returns to `open`). The implementer addresses findings on the parent
task independently. The parent remains blocked by G0 until the review child
is `done`.

---

## 9. Validation Rules

`create_task` enforces:

1. `task_spec.description` is present and non-empty (all types).
2. `task_spec.review_ref` is present and non-empty when `task_type = review`
   (V1_DESIGN.md §7.6).
3. `task_spec` total size does not exceed 64 KB (§8.6 CHECK constraint).
4. If `mutation_policy`, `failure_policy`, or `output_contract` are present,
   their keys must match the schemas defined above. Unknown keys are rejected.

`validate_spec` performs the same checks without creating a task, for
pre-flight validation.

---

## 10. Extensibility

This schema is designed for v1.0's three task types. When v1.1 introduces
`review_judgment`, `review_coverage`, and `review_reconciliation` (see
V1.1_DEFERRED.md #D2), each will inherit from the `review` schema with
type-specific additions:

- `review_judgment`: adds `severity_calibration_focus` (optional)
- `review_coverage`: adds `coverage_checklist` (optional)
- `review_reconciliation`: adds `source_reviews` (required, list of review
  task IDs to reconcile)

The common keys, mutation policy, failure policy, and output contract
structures remain unchanged.

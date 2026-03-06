# The Hive Reliability Execution Design

Status: Reviewed - approved for Phase 1 implementation  
Last updated: 2026-03-06  
Owner: the-hive maintainers

## 1. Purpose

Define how The Hive moves from process-driven coordination to policy-enforced
parallel AI development with scoped work, test-driven validation, and explicit
handoffs.

This document is the source of truth for reliability architecture and rollout.
Implementation tasks should not proceed without aligning to this design.

## 2. Problem Statement

Current workflows rely on operator discipline instead of hard controls.
This causes inconsistent enforcement of:

- scope boundaries
- dependency order
- RED-before-implementation TDD
- independent review
- handoff completeness

When agent throughput increases, manual enforcement does not scale and defect
risk rises.

## 3. Goals

1. Enforce scoped work through machine-validated task contracts.
2. Enforce TDD with durable RED and GREEN evidence artifacts.
3. Enforce explicit handoffs with required metadata and links.
4. Enforce dependency order and review separation before completion.
5. Preserve full auditability of all gate decisions and overrides.

## 4. Non-Goals (Phase 1)

1. Real-time collaborative editing.
2. Full enterprise RBAC model.
3. Autonomous multi-repo orchestration.
4. CI provider-specific deep integration beyond required checks.

## 5. Reliability Principles

1. Verification over assertion.
2. Contracts over conventions.
3. Deterministic gates over discretionary judgment.
4. Independent review over self-attestation.
5. Traceability over speed shortcuts.

## 6. Core Architecture

### 6.1 Task Contract (Required)

Each task must include a machine-readable contract with:

- allowed file paths/globs
- forbidden file paths/globs
- dependency task IDs
- required test commands
- required evidence artifacts
- required reviewer policy
- handoff template ID

Without a valid contract, a task cannot move to `in_progress`.

### 6.2 Policy Gate Engine

A single gate engine evaluates state transitions.
Every transition emits pass/fail records and reasons.

Gate checks are run on:

- claim/start
- status transitions (`in_progress`, `blocked`, `done`)
- merge readiness

### 6.3 Evidence Ledger

Store immutable references for:

- RED run (command + timestamp + failing summary)
- implementation commit(s)
- GREEN run (targeted + required full suite)
- review decision and findings
- handoff packet

### 6.4 Handoff Packet

Every completed task produces a structured handoff containing:

- what changed
- why it changed
- residual risks
- unresolved questions
- verification proof links
- next actions

### 6.5 Independent Review Gate

Policy: self-review is prohibited.
The implementation author cannot review or approve their own code.
`done` requires at least one independent review result.

### 6.6 Artifact Integrity and Retention

Evidence artifacts must include:

- artifact type
- storage URI/reference
- content hash (SHA-256)
- capture timestamp
- capture actor
- immutability flag

Retention policy:

- minimum retention is 180 days after task reaches `done` or `superseded`
- artifact deletion before retention expiry requires owner override with reason

## 7. Workflow State Machine

Allowed states:

- `open`
- `in_progress`
- `blocked`
- `done`
- `superseded`

Allowed transitions:

1. `open -> in_progress`
2. `in_progress -> blocked`
3. `blocked -> in_progress`
4. `in_progress -> done`
5. `open|in_progress|blocked -> superseded`

Transition guards:

1. `open -> in_progress`: valid contract, dependencies satisfied or explicitly
   marked as waived with override record.
2. `in_progress -> done`: gate checks pass for scope, RED->implementation
   ordering, GREEN evidence, independent review, and handoff.
3. Any override requires actor, reason, and expiry.

## 8. Gate Definitions

### Gate G1: Scope Lock

- Compare changed files to contract allow-list.
- Fail on any out-of-scope change unless approved override exists.
- For rename/move operations, validate both source and destination paths.

### Gate G2: TDD Order

- RED artifact must exist before first implementation commit.
- RED must include failing test identifiers relevant to task contract.
- `first implementation commit` is the earliest commit recorded in evidence with
  type `implementation_commit`.
- Gate evaluation uses ledger capture order (`captured_at`) rather than VCS
  author/commit timestamp.

### Gate G3: Verification

- Required targeted tests must pass.
- Required full suite command must pass (or documented pre-approved exception).
- Phase 1 default is full-suite required for every task. Exceptions require an
  override record with owner approval and expiry.
- If post-completion verification fails, the task must be returned from `done`
  to `in_progress` (or `changes_requested`) until GREEN evidence is restored.

### Gate G4: Review Separation

- Reviewer identity must differ from author identity (`reviewer != author`).
- A self-review is invalid and does not satisfy completion gates.
- Critical findings must be resolved or explicitly accepted by owner override.

### Gate G5: Handoff Completeness

- Handoff fields validated against schema.
- Missing evidence links fail completion.

## 9. Data Model Additions

Proposed logical entities:

1. `task_contracts`
2. `task_gate_events`
3. `task_evidence_artifacts`
4. `task_handoffs`
5. `task_overrides`

Minimum fields:

- actor
- timestamp
- task_id
- gate_name
- decision (`pass|fail|override`)
- reason
- artifact_ref (optional)

Entity-specific required fields:

1. `task_contracts`
   - contract_version
   - allowed_paths
   - forbidden_paths
   - dependencies
   - required_tests
   - review_policy
   - handoff_template
2. `task_evidence_artifacts`
   - artifact_type
   - artifact_hash_sha256
   - captured_at
   - captured_by
   - storage_ref
   - immutable
3. `task_handoffs`
   - template_id
   - payload_json
   - submitted_by
   - submitted_at
4. `task_overrides`
   - gate_name
   - scope
   - approved_by
   - reason
   - expires_at

## 10. Suggested Task Contract Schema (v1)

```yaml
task_id: 123
owner: codex-scott
allowed_paths:
  - dashboard/**
forbidden_paths:
  - coordinator/**
dependencies:
  - 7
  - 8
required_tests:
  red:
    - npx vitest run dashboard/src/lib/TaskDetail.test.ts
  green:
    - npx vitest run dashboard/src/lib/TaskDetail.test.ts
    - npx vitest run
review_policy:
  min_reviews: 1
  independent_required: true
handoff_template: v1_task_handoff
verification_policy:
  require_full_suite: true
block_policy:
  blocker_task_ids_required: true
superseded_policy:
  replacement_task_id_required: true
evidence_policy:
  retention_days: 180
  require_sha256: true
```

## 11. Rollout Plan

### Phase 1: Enforce Core Gates

1. Add contract + evidence + gate event storage.
2. Enforce G1-G5 on task completion.
3. Require handoff packet for `done`.

Success criteria:

- 100% done tasks have RED and GREEN evidence.
- 0 unapproved out-of-scope file changes.
- 100% done tasks have independent review records.

### Phase 2: Dependency and Scheduling Reliability

1. Dependency-aware claiming and auto-blocking.
2. Lease/heartbeat ownership.
3. Stale owner auto-release with audit events.

Success criteria:

- lower blocked time from stale ownership
- fewer dependency-order violations

### Phase 3: Governance and Optimization

1. RBAC and approval policies.
2. Reliability dashboard and trend metrics.
3. Automated policy tuning from incident/defect outcomes.

## 12. Migration Guidance for Existing Work

1. Do not delete historical tasks/issues.
2. If dependency metadata cannot be edited on existing tasks:
   - mark task `blocked`
   - add explicit blocker note
   - create replacement task with correct dependencies if needed
3. Treat missing prerequisite capabilities as explicit tasks, not hidden
   assumptions inside implementation tasks.

## 13. Review Checklist

1. Are all gates objectively machine-checkable?
2. Are override rules explicit and auditable?
3. Is RED-before-implementation enforceable with available data?
4. Are dependency semantics clear and non-ambiguous?
5. Can one operator run this workflow reliably before multi-operator scale?

## 14. Resolved Decisions

1. `blocked` requires enumerated blocker IDs in contract/handoff data.
2. Full-suite GREEN is mandatory by default in Phase 1.
3. Evidence retention minimum is 180 days.
4. `superseded` tasks must link a replacement task ID when applicable.

## 15. Acceptance Criteria for This Design

This design is accepted when:

1. It has one independent review with resolved major findings.
2. Phase 1 implementation tasks are created directly from sections 6-11.
3. Existing active tasks are mapped to this gate model with explicit notes.

# The Hive v1.0 - Agentic Coordination Design

Status: Draft - pending review
Last updated: 2026-03-06
Owner: the-hive maintainers
Baseline: v0.9 implements `docs/architecture/RELIABILITY_EXECUTION_DESIGN.md` (G1-G5 gates)

---

## 1. Purpose

Define the additions required to evolve the Hive from a gate-enforced task queue
into a coordination system capable of supporting multi-person, multi-vendor,
multi-session agentic development workflows without manual scheduling or routing.

v1.0 is intentionally a breaking upgrade from the v0.9 beta schema/process.
Clean migration is preferred over compatibility shims.

---

## 2. Baseline (What v0.9 Provides)

- G1-G5 gate engine enforced on task completion
- Task contracts (`allowed_paths`, `forbidden_paths`, `dependencies`, `red_tests`, `green_tests`, `review_policy`, `handoff_template`)
- Evidence artifacts (immutable, SHA-256 referenced)
- Override system with actor, reason, expiry
- State machine: `open -> in_progress -> done | cancelled | blocked` (replaced by section 7.4a)
- Dependency-aware claiming and `get_next_task`
- Clarification system (create, answer, auto-block/unblock)
- Projects -> Milestones -> Tasks hierarchy
- MCP server + FastAPI REST + Svelte dashboard

---

## 3. Problem Statement

v0.9 enforces process correctness. It does not address coordination at scale.
Specific gaps:

1. **Tasks are not reliably agent-executable.** Free-text descriptions still require
   human prompt translation and interpretation.

2. **No profile/session split for agents.** Concurrent sessions of the same agent role
   are not modeled cleanly.

3. **Capability/trust routing is too coarse.** No support for per-capability ratings
   (for example, review judgment vs review coverage).

4. **No enforceable dual-review workflow.** Teams requiring two distinct review modes
   (judgment + coverage) cannot gate completion via task structure.

5. **No branch/worktree execution policy.** Multiple agents can interfere in a shared
   clone by switching branches and mutating each other's workspace.

6. **Spec payloads are not schema-validated.** Project/milestone/task intent is not
   consistently machine-parseable.

7. **Clarification routing lacks explicit target queue semantics.** Routing intent exists,
   but target retrieval/inbox behavior is underspecified.

8. **v2 auth/RBAC seam is undefined.** Current identity fields risk forcing rewrites
   when authenticated principals and policy checks are added.

---

## 4. Goals

1. Make tasks self-sufficient for agent execution without custom human prompts.
2. Model agent profiles, concurrent sessions, capabilities, and trust so routing is automatic and enforced.
3. Support dual-review workflows as first-class policy (`review-judgment` + `review-coverage`) with reconciliation.
4. Add domain ownership to milestones so clarifications route correctly.
5. Enrich projects/milestones/tasks with schema-validated specs.
6. Enforce safe concurrent execution through branch/worktree policy at claim/start time.
7. Keep v1.0 default-open for access while adding identity/policy seams needed for v2 auth/RBAC.

---

## 5. Non-Goals (v1.0)

1. Push notifications or webhooks (polling remains sufficient).
2. Full authentication and RBAC enforcement (planned for v2).
3. Centralized manager scheduling loop (queue self-selection remains primary).
4. Automatic task generation from design docs.
5. CI/CD provider-specific integrations.
6. Cross-repo orchestration.

---

## 6. Design Principles

In addition to the reliability principles from RELIABILITY_EXECUTION_DESIGN.md:

1. **Queue over assignment.** Agents self-select via capability-filtered `get_next_task`.
2. **Policy as data.** Capability matrix, review roles, and execution rules are structured and versioned.
3. **Profile vs session separation.** Long-lived agent profile policy is distinct from short-lived runtime sessions.
4. **Spec-first execution.** Agents consume schema-validated `*_spec` payloads, not ad-hoc prompts.
5. **Safe parallelism by default.** Branch/worktree policy must prevent concurrent workspace interference.
6. **Forward seams for auth.** Identity and policy boundaries are explicit now, even with v1 default-open access.

---

## 7. Core Architecture Additions

### 7.1 Agent Identity: Profiles and Sessions

v1 introduces two identity layers:

- **Agent profile**: stable capability/trust definition (for example `scott.codex.worker`).
- **Agent session**: concurrent runtime instance (for example `scott.codex.worker.01`).

Recommended `agent_id` format for sessions:

- `<owner>.<vendor>.<role>.<nn>`

Examples:

- `scott.codex.worker.01`
- `scott.gemini.scout.01`
- `scott.claude.manager.02`

Session records include lease/heartbeat metadata for stale-claim recovery.

### 7.2 Capability Matrix and Review Roles

Capabilities and role suitability are managed in a versioned config file:

- `config/agent_matrix.toml`

The matrix defines:

- capability taxonomy
- per-profile capability ratings (`strong | marginal | blocked`)
- default trust level (`low | standard | high`)
- gate compliance defaults
- review role policy

The matrix is loaded into the database at startup via the seed step (section 13).
Once seeded, the database copy is authoritative. Runtime capability checks read from
`hive.agent_profile_capabilities`, not from the TOML file. Changes to the TOML
require a re-seed operation, which is an auditable action logged in the identity
audit table (section 8.12).

Initial review roles:

- `review-judgment` (severity calibration, final verdict quality)
- `review-coverage` (exhaustive secondary sweep)

### 7.3 Enriched Project and Milestone Records

Projects and milestones gain schema-validated specs and execution policy fields.

Project additions:

- `repo`, `design_doc_ref`, `goal`, `owner`
- `project_spec` (JSON schema validated)
- `execution_policy` (JSON schema validated)

Milestone additions:

- `domain`, `owner`
- `milestone_spec` (JSON schema validated)
- `execution_policy` (JSON schema validated, overrides project policy)

### 7.4 Enriched Task Record and Task Types

Tasks gain structured execution data and workflow typing.

Agent execution fields:

- `task_spec` (JSON schema validated)
- `context`
- `acceptance_criteria`
- `github_issue_ids`

Routing and policy fields:

- `required_capabilities`
- `min_trust_level`
- `excluded_agents` (write-restricted; see below)
- `preferred_agent` (write-restricted; see below)
- `task_type` (`implementation | review_judgment | review_coverage | review_reconciliation | misc`)
  - `review_judgment` and `review_coverage` are **code reviews**, not self-audits.
    The reviewer examines the parent task's implementation diff and artifacts as
    an independent critic. The `task_spec` for review tasks must reference the
    parent's branch/commit and frame the work as a code review, not a checklist
    the implementing agent runs against its own output.
- `parent_task_id` (nullable; links review/reconciliation tasks to parent implementation)
- `execution_policy` (JSON schema validated, task-level override)

Routing field write policy: `excluded_agents` and `preferred_agent` can only be set
at task creation time or by the task's project/milestone owner. `update_task` rejects
changes to these fields unless the caller's `actor_id` matches the task creator or
the owning project/milestone `owner`. This prevents agents from monopolizing work or
excluding competitors.

v1 security note: because v1 is default-open and unauthenticated, this is a
cooperative policy control, not a hard security boundary. v2 auth/RBAC will
enforce these ownership checks against authenticated principals.

### 7.4a Task State Machine

v0.9 state machine: `open -> in_progress -> done | cancelled | blocked`.
v1.0 replaces this with a fully defined transition table. Statuses are
`open | in_progress | blocked | done | superseded`. Claim fields
(`claim_token`, `claim_session_id`, `heartbeat_deadline`) are set or cleared
atomically as a group; the `tasks_claim_state_check` constraint (section 8.6)
enforces this.

Valid transitions:

| From | To | Trigger | Claim fields |
| --- | --- | --- | --- |
| `open` | `in_progress` | `claim_task` | Set (all three) |
| `open` | `blocked` | auto-block (dependency fail, clarification on unclaimed task) | Stay NULL |
| `open` | `superseded` | `supersede_task` | Stay NULL |
| `in_progress` | `done` | `update_task(status=done)` — G0-G5 must pass | Clear (all three) |
| `in_progress` | `blocked` | clarification raised or dependency blocked while claimed | Keep (all three) |
| `in_progress` | `open` | `release_task`, heartbeat expiry, or review `changes_requested` | Clear (all three) |
| `in_progress` | `superseded` | `supersede_task` | Clear (all three) |
| `blocked` (claimed) | `in_progress` | auto-unblock (clarification answered, dependency resolved) | Keep (all three) |
| `blocked` (claimed) | `open` | `release_task` or heartbeat expiry while blocked | Clear (all three) |
| `blocked` (claimed) | `superseded` | `supersede_task` | Clear (all three) |
| `blocked` (unclaimed) | `open` | auto-unblock | Stay NULL |
| `blocked` (unclaimed) | `superseded` | `supersede_task` | Stay NULL |
| `done` | `open` | `reopen_task` | Stay NULL |
| `superseded` | `open` | `reopen_task` | Stay NULL |

Invalid transitions (rejected by application logic):

- `open` -> `done` (must claim first; gates require evidence from a claimed session)
- `done` -> `in_progress` / `blocked` (must reopen to `open` first)
- `superseded` -> `in_progress` / `blocked` / `done` (must reopen to `open` first)

**Claim-aware blocking.** v0.9 auto-block always sets status to `blocked` and
auto-unblock always sets status to `open`, discarding any active claim. v1 fixes
this: when an `in_progress` task is blocked (e.g., clarification raised by the
claiming agent), the claim fields are preserved and the agent resumes
(`blocked` -> `in_progress`) when unblocked. When an unclaimed `open` task is
blocked (e.g., dependency failure), it returns to `open` on unblock. The
`tasks_claim_state_check` constraint allows `blocked` in both claimed and
unclaimed states to support this.

**Review-specific note.** The `in_progress` -> `open` transition via
`changes_requested` verdict uses the same mechanism as `release_task`. The
review `task_type` does not introduce additional states; the verdict is recorded
as evidence metadata, not as a status value.

### 7.5 Capability-Filtered Task Selection

`get_next_task` gains `agent_session_id` (preferred) and supports existing `agent_id` aliases.

Eligibility filters when session identity is provided:

1. Session is active and lease-valid.
2. Profile has all required capabilities at allowed level.
3. Profile trust level meets/exceeds `min_trust_level`.
4. Session/profile is not in `excluded_agents`.
5. `gate_compliant` is true when `min_trust_level > low`.
6. Execution-policy preconditions pass (worktree/branch lease checks).
7. Existing queue filters still apply (status/dependencies/not already claimed).
8. No owner/domain authorization filter is applied in v1.0 (default-open access).

v1 access policy: default-open visibility (no owner access filtering). Ownership fields
remain for routing and future v2 authorization.

`claim_task` re-validates eligibility to prevent race conditions.

### 7.6 Review as Child Tasks + Reconciliation Gate

For implementation work requiring dual review:

1. Create one parent `implementation` task.
2. Create child `review_judgment` task (`parent_task_id = implementation_id`).
3. Create child `review_coverage` task (`parent_task_id = implementation_id`).
4. Create child `review_reconciliation` task that resolves combined findings.

Parent implementation task cannot move to `done` until required child review tasks
and reconciliation task are `done`.

**Code review, not self-audit.** v0.9 allowed agents to satisfy G4 by recording
`review_output` evidence against their own work — effectively a self-audit
checklist. v1 eliminates this pattern. Review child tasks are code reviews:
the reviewer reads the parent's implementation diff, evaluates correctness and
risk, and records findings as an independent critic. The `task_spec` for each
review child task must include the parent's branch or commit ref so the reviewer
can inspect the actual changes. `create_task` rejects review child tasks whose
`task_spec` does not contain a `review_ref` field (branch name or commit SHA).
Self-audit evidence recorded by the implementing agent is not a substitute for
a code review by a separate reviewer.

**Review verdict lifecycle.** A review task has two possible outcomes:

- **Approved**: reviewer records `review_output` evidence with
  `verdict: "approved"`. The review task moves to `done`.
- **Changes requested**: reviewer records `review_output` evidence with
  `verdict: "changes_requested"` and findings. The review task releases its
  claim and returns to `open`. The implementer addresses the findings on the
  parent task, then the review task is re-claimed for another pass. This cycle
  repeats until the reviewer approves. The same or a different reviewer may
  claim subsequent passes; G4 profile-level separation is re-evaluated on each
  claim.

G4 review separation is enforced at the **profile** level, not the session level.
When evaluating G4, the engine resolves the `profile_id` for both the implementation
author's `claim_session_id` and each reviewer's `actor_id`. The invariant is:
`reviewer_profile_id != author_profile_id`. This prevents self-review via session
aliasing (e.g., `scott.codex.worker.01` implementing and `.02` reviewing).

Human reviewer handling: if a reviewer `actor_id` does not resolve to an
`agent_session_id`, the reviewer identity is treated as `human:<actor_id>`.
Self-review prevention then compares:

- agent-authored work: `reviewer_profile_id != author_profile_id`
- human-authored work: `reviewer_actor_id != author_actor_id`

This is enforced by gate **G0_child_closure**: before any `status = 'done'`
transition is accepted, the engine queries
`SELECT id FROM hive.tasks WHERE parent_task_id = $1 AND status NOT IN ('done', 'superseded')`
and rejects the transition if any rows are returned. G0 runs before existing G1-G5
finalization. The stale-claim recovery job emits events with gate name
`heartbeat_expired` into `hive.task_gate_events`.

### 7.7 Clarification Routing

Clarifications gain a routing chain and explicit target identity:

1. Route first to milestone owner.
2. Escalate to project owner if unresolved.
3. Escalate to human-required queue if still unresolved.

`routed_to` stores the target principal/session identity. Target inbox retrieval is
explicitly supported by clarification listing/query tools.

### 7.8 Execution Policy Hierarchy (Workspace Safety)

Execution policy can be set at:

1. project default
2. milestone/domain override
3. task override

Minimum v1 policy keys:

- `workspace_mode = dedicated_worktree`
- `branch_mode = per_task_branch`
- `branch_name_template` (for example `task/{task_id}-{agent_session_id}`)
- `allow_shared_clone = false` for write operations
- `require_clean_worktree_on_claim = true`

Branch name safety: before constructing a branch name, all interpolated values
(`task_id`, `agent_session_id`) are validated against `^[a-zA-Z0-9._-]+$`. If any
value contains characters outside this set, the claim is rejected. This is also
mitigated by the ID format CHECK on `agent_sessions.id` (section 8.2).

These checks are enforced at claim/start and completion evidence validation.

### 7.9 Stale-Claim Recovery

A background job recovers claims from dead or unresponsive agents.

Timing parameters:

- **Heartbeat interval**: agents call `heartbeat_task` every 5 minutes.
- **Heartbeat deadline**: `claim_task` sets `heartbeat_deadline = now() + 15 min`.
  Each `heartbeat_task` call extends the deadline by another 15 minutes.
- **Grace period**: the recovery job runs every 5 minutes and only reclaims tasks
  where `heartbeat_deadline < now()`. The 15-minute deadline provides a 10-minute
  grace window beyond the expected 5-minute heartbeat interval.

Recovery behavior:

1. `UPDATE hive.tasks SET status = 'open', assigned_to = NULL, claim_token = NULL, claim_session_id = NULL, heartbeat_deadline = NULL WHERE status = 'in_progress' AND heartbeat_deadline < now()`.
2. Emit a `gate_event` with `gate_name = 'heartbeat_expired'` for each reclaimed task.
3. Session expiry also triggers claim release: if `agent_sessions.status` becomes
   `expired`, the recovery job releases any tasks where `claim_session_id` matches
   the expired session, regardless of `heartbeat_deadline`.

Branch cleanup on expired claims: the released task retains its `execution_policy`
branch name template. A new claimant gets a fresh branch name. Stale branches from
expired claims are not automatically deleted; operators clean them up out-of-band.
Automated branch cleanup is deferred to v1.1.

---

## 8. Data Model Additions

Enum columns use `text CHECK (col IN (...))` throughout. Adding a new enum value
requires `DROP CONSTRAINT` + `ADD CONSTRAINT`, which takes a brief `ACCESS EXCLUSIVE`
lock. At current scale this is acceptable. If table sizes grow significantly, migrate
to Postgres `ENUM` types or reference tables with FKs in a future release.

### 8.1 New Table: `hive.agent_profiles`

```sql
CREATE TABLE hive.agent_profiles (
    id              text PRIMARY KEY
                    CHECK (id ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
    display_name    text NOT NULL,
    owner           text NOT NULL,
    vendor          text NOT NULL,
    model_family    text NOT NULL,
    trust_level     text NOT NULL CHECK (trust_level IN ('low', 'standard', 'high')),
    gate_compliant  boolean NOT NULL DEFAULT true,
    active          boolean NOT NULL DEFAULT true,
    created_by      text NOT NULL,  -- identity that registered this profile
    created_at      timestamptz NOT NULL DEFAULT now()
);
```

`register_agent_profile` is insert-only. Updating an existing profile requires
`update_agent_profile`, which validates that the caller's `actor_id` matches the
original `created_by`. This prevents namespace squatting and silent trust
escalation.

### 8.2 New Table: `hive.agent_sessions`

```sql
CREATE TABLE hive.agent_sessions (
    id               text PRIMARY KEY
                     CHECK (id ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
    profile_id       text NOT NULL REFERENCES hive.agent_profiles(id) ON DELETE RESTRICT,
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'expired')),
    lease_expires_at timestamptz,
    last_heartbeat_at timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);
```

`ON DELETE RESTRICT` prevents deleting a profile that has sessions. Deactivate
profiles by setting `active = false` instead.

### 8.3 Capability Taxonomy and Membership

```sql
CREATE TABLE hive.agent_capabilities (
    id          text PRIMARY KEY,
    description text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE hive.agent_profile_capabilities (
    profile_id     text NOT NULL REFERENCES hive.agent_profiles(id) ON DELETE CASCADE,
    capability_id  text NOT NULL REFERENCES hive.agent_capabilities(id),
    level          text NOT NULL CHECK (level IN ('strong', 'marginal', 'blocked')),
    PRIMARY KEY (profile_id, capability_id)
);
```

### 8.4 Additions to `hive.projects`

```sql
ALTER TABLE hive.projects
    ADD COLUMN repo              text,
    ADD COLUMN design_doc_ref    text,
    ADD COLUMN goal              text,
    ADD COLUMN owner             text,
    ADD COLUMN project_spec      jsonb NOT NULL DEFAULT '{}'::jsonb
                                 CHECK (pg_column_size(project_spec) <= 65536),
    ADD COLUMN execution_policy  jsonb NOT NULL DEFAULT '{}'::jsonb
                                 CHECK (pg_column_size(execution_policy) <= 16384);
```

### 8.5 Additions to `hive.milestones`

```sql
ALTER TABLE hive.milestones
    ADD COLUMN domain            text,
    ADD COLUMN owner             text,
    ADD COLUMN milestone_spec    jsonb NOT NULL DEFAULT '{}'::jsonb
                                 CHECK (pg_column_size(milestone_spec) <= 65536),
    ADD COLUMN execution_policy  jsonb NOT NULL DEFAULT '{}'::jsonb
                                 CHECK (pg_column_size(execution_policy) <= 16384);
```

### 8.6 Additions to `hive.tasks`

```sql
ALTER TABLE hive.tasks
    ADD COLUMN created_by             text,
    ADD COLUMN context                text,
    ADD COLUMN acceptance_criteria    text[] NOT NULL DEFAULT '{}',
    ADD COLUMN github_issue_ids       int[] NOT NULL DEFAULT '{}'
                                       CHECK (0 < ALL(github_issue_ids)),
    ADD COLUMN required_capabilities  text[] NOT NULL DEFAULT '{}',
    ADD COLUMN min_trust_level        text NOT NULL DEFAULT 'low'
                                       CHECK (min_trust_level IN ('low', 'standard', 'high')),
    ADD COLUMN excluded_agents        text[] NOT NULL DEFAULT '{}',
    ADD COLUMN preferred_agent        text,
    ADD COLUMN task_type              text NOT NULL DEFAULT 'misc'
                                       CHECK (task_type IN ('implementation', 'review_judgment', 'review_coverage', 'review_reconciliation', 'misc')),
    ADD COLUMN parent_task_id         int REFERENCES hive.tasks(id)
                                       CHECK (parent_task_id != id),
    ADD COLUMN claim_token            uuid,
    ADD COLUMN claim_session_id       text REFERENCES hive.agent_sessions(id),
    ADD COLUMN heartbeat_deadline     timestamptz,
    ADD COLUMN task_spec              jsonb NOT NULL DEFAULT '{}'::jsonb
                                       CHECK (pg_column_size(task_spec) <= 65536),
    ADD COLUMN execution_policy       jsonb NOT NULL DEFAULT '{}'::jsonb
                                       CHECK (pg_column_size(execution_policy) <= 16384);

-- Claim-state invariant: token, session, and deadline are all-or-nothing
ALTER TABLE hive.tasks
    ADD CONSTRAINT tasks_claim_state_check CHECK (
        (
            status IN ('open', 'blocked', 'done', 'superseded')
            AND claim_token IS NULL
            AND claim_session_id IS NULL
            AND heartbeat_deadline IS NULL
        )
        OR (
            status IN ('in_progress', 'blocked')
            AND claim_token IS NOT NULL
            AND claim_session_id IS NOT NULL
            AND heartbeat_deadline IS NOT NULL
        )
    );

-- Indexes for capability-filtered get_next_task
CREATE INDEX ON hive.tasks (task_type, status) WHERE status = 'open';
CREATE INDEX ON hive.tasks (parent_task_id) WHERE parent_task_id IS NOT NULL;
CREATE INDEX ON hive.tasks (min_trust_level, status) WHERE status = 'open';
```

`created_by` is set from the caller's `actor_id` on `create_task` and is immutable
after creation. It is used to authorize routing field updates (section 7.4).
Migration order for populated tables is:

1. Add `created_by` as nullable (DDL above).
2. Backfill existing rows (section 13 step 3).
3. Enforce non-null:
   `ALTER TABLE hive.tasks ALTER COLUMN created_by SET NOT NULL;`

`claim_session_id` is an FK to `hive.agent_sessions(id)`. The `tasks_claim_state_check`
constraint ensures the three claim fields (`claim_token`, `claim_session_id`,
`heartbeat_deadline`) are always set or cleared together — there is no partially-claimed
state. `claim_task` sets all three atomically; the recovery job (section 7.9) and
`release_task` clear all three atomically.

### 8.7 Additions to `hive.clarifications`

```sql
ALTER TABLE hive.clarifications
    ADD COLUMN routed_to text;
```

`routed_to` is not FK-constrained because it may reference human principals not in
the agent registry. Application logic validates that `routed_to` resolves to a known
profile, project owner, or milestone owner before accepting the clarification.

### 8.8 Required Table: `hive.task_idempotency_keys`

```sql
CREATE TABLE hive.task_idempotency_keys (
    key          text PRIMARY KEY,
    operation    text NOT NULL,
    result_json  jsonb NOT NULL
                 CHECK (pg_column_size(result_json) <= 16384),
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL DEFAULT now() + interval '24 hours'
);

CREATE INDEX ON hive.task_idempotency_keys (expires_at);
```

Cleanup: the stale-claim recovery background job (section 7.9) also runs
`DELETE FROM hive.task_idempotency_keys WHERE expires_at < now()` on each sweep.
This prevents unbounded table growth from buggy or high-volume agents.

### 8.9 Actor Identity Column Unification

v0.9 uses three different column names for the same concept (the identity of the
actor who performed the operation):

| Table | v0.9 column | Constraint |
| --- | --- | --- |
| `task_gate_events` | `actor` | `NOT NULL` |
| `task_overrides` | `approved_by` | `NOT NULL` |
| `task_evidence_artifacts` | `captured_by` | `NOT NULL` |

v1.0 renames all three to `actor_id` for a uniform v2 auth seam. This is a
breaking migration (v1 is a breaking upgrade; no compatibility shim required).

```sql
ALTER TABLE hive.task_gate_events
    RENAME COLUMN actor TO actor_id;

ALTER TABLE hive.task_overrides
    RENAME COLUMN approved_by TO actor_id;

ALTER TABLE hive.task_evidence_artifacts
    RENAME COLUMN captured_by TO actor_id;
```

Policy note:

- All three columns are already `NOT NULL`; the rename preserves that constraint.
- All new writes in v1.0 MUST set `actor_id` to the agent session ID or human
  principal that performed the operation. This is the identity token v2 auth will
  validate.
- Application code must use `actor_id` exclusively after migration. References to
  the old column names (`actor`, `approved_by`, `captured_by`) must be updated in
  the same release.

### 8.10 Gate Name Constraint Extension

v0.9 CHECK constraints on `hive.task_gate_events.gate_name` and
`hive.task_overrides.gate_name` enumerate only G1-G5. v1.0 adds
`G0_child_closure` (section 7.6) and the `heartbeat_expired` audit event
(stale-claim recovery job). The constraints must be widened before any G0 or
heartbeat event can be written.

```sql
-- task_gate_events: drop old gate-name check by discovery, then add v1 list
DO $$
DECLARE
    c text;
BEGIN
    SELECT conname INTO c
    FROM pg_constraint
    WHERE conrelid = 'hive.task_gate_events'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%gate_name%';
    IF c IS NOT NULL THEN
        EXECUTE format('ALTER TABLE hive.task_gate_events DROP CONSTRAINT %I', c);
    END IF;
END $$;

ALTER TABLE hive.task_gate_events
    ADD CONSTRAINT task_gate_events_gate_name_check CHECK (
        gate_name IN (
            'G0_child_closure',
            'G1_scope_lock',
            'G2_tdd_order',
            'G3_verification',
            'G4_review_separation',
            'G5_handoff_completeness',
            'heartbeat_expired'
        )
    );

-- task_overrides: heartbeat_expired is an event, not an overridable gate
DO $$
DECLARE
    c text;
BEGIN
    SELECT conname INTO c
    FROM pg_constraint
    WHERE conrelid = 'hive.task_overrides'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%gate_name%';
    IF c IS NOT NULL THEN
        EXECUTE format('ALTER TABLE hive.task_overrides DROP CONSTRAINT %I', c);
    END IF;
END $$;

ALTER TABLE hive.task_overrides
    ADD CONSTRAINT task_overrides_gate_name_check CHECK (
        gate_name IN (
            'G0_child_closure',
            'G1_scope_lock',
            'G2_tdd_order',
            'G3_verification',
            'G4_review_separation',
            'G5_handoff_completeness',
            'G_start_dependencies'
        )
    );
```

### 8.11 Task Status Canonicalization

v0.9 uses `cancelled` as a terminal status. v1.0 replaces it with `superseded` to
better reflect the intent: a task is not arbitrarily cancelled but replaced by a
successor or made irrelevant by a design change. The canonical v1.0 task statuses
are:

`open | in_progress | blocked | done | superseded`

```sql
-- Rename existing cancelled rows
UPDATE hive.tasks SET status = 'superseded' WHERE status = 'cancelled';

-- Replace the status CHECK constraint by discovery (name may vary by environment)
DO $$
DECLARE
    c text;
BEGIN
    SELECT conname INTO c
    FROM pg_constraint
    WHERE conrelid = 'hive.tasks'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%cancelled%';
    IF c IS NOT NULL THEN
        EXECUTE format('ALTER TABLE hive.tasks DROP CONSTRAINT %I', c);
    END IF;
END $$;

ALTER TABLE hive.tasks
    ADD CONSTRAINT tasks_status_check CHECK (
        status IN ('open', 'in_progress', 'blocked', 'done', 'superseded')
    );
```

All application code, dependency queries, and gate predicates must use `superseded`
where they previously used `cancelled`. The G0 blocking predicate (section 7.6)
and dependency resolution queries both treat `superseded` as terminal:
`status NOT IN ('done', 'superseded')` blocks the parent.

### 8.12 Identity Audit Table

Profile registration, trust level changes, capability assignments, and session
lifecycle events are auditable. Gate events cover task operations, but identity
management has no equivalent trail in v0.9. v1.0 adds:

```sql
CREATE TABLE hive.agent_audit_log (
    id          SERIAL PRIMARY KEY,
    actor_id    text NOT NULL,
    operation   text NOT NULL CHECK (
        operation IN (
            'profile_created',
            'profile_updated',
            'session_started',
            'session_ended',
            'session_expired',
            'capability_changed',
            'matrix_reseeded'
        )
    ),
    target_id   text NOT NULL,       -- profile or session ID affected
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (pg_column_size(detail) <= 16384),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON hive.agent_audit_log (target_id, created_at);
CREATE INDEX ON hive.agent_audit_log (operation, created_at);
```

---

## 9. New and Modified MCP Tools

### New tools

| Tool | Description |
| --- | --- |
| `register_agent_profile` | Insert a new agent profile (fails if ID already exists) |
| `update_agent_profile` | Update an existing profile; caller `actor_id` must match `created_by` |
| `start_agent_session` | Create/renew an active agent session |
| `heartbeat_agent_session` | Refresh session lease |
| `heartbeat_task` | Refresh an active task claim heartbeat using `claim_token` |
| `end_agent_session` | Mark session inactive |
| `list_agent_profiles` | List registered profiles |
| `list_capabilities` | Return capability taxonomy and levels |
| `validate_spec` | Validate project/milestone/task spec payload against current schema version |

### Modified tools

| Tool | Change |
| --- | --- |
| `get_next_task` | Add `agent_session_id`; capability/trust/execution-policy filtering |
| `claim_task` | Re-validate eligibility and execution-policy lease checks; issues `claim_token` bound to `claim_session_id`; sets heartbeat deadline. `claim_token` is returned only in the `claim_task` response and MUST NOT appear in list/query endpoints. |
| `create_task` | Accept `task_type`, `parent_task_id`, `task_spec`, execution fields/policy. Sets `created_by` from caller's `actor_id` (immutable after creation). Reject if `parent_task_id` itself has a non-null `parent_task_id` (enforces single-level nesting). |
| `update_task` | Accept routing/execution/spec fields and workflow type updates; validate `(claim_token, claim_session_id)` pair on terminal transitions |
| `record_task_evidence` | Require active `agent_session_id` + matching `(claim_token, claim_session_id)` pair; set `actor_id` on write |
| `create_project` / `update_project` | Accept `project_spec`, execution policy, intent fields |
| `create_milestone` / `update_milestone` | Accept `milestone_spec`, execution policy, `domain`, `owner` |
| `create_clarification` | Auto-populate `routed_to` via routing chain |
| `list_clarifications` | Add filtering by `routed_to` |
| All mutating tools | Support optional `idempotency_key`; resolve through `hive.task_idempotency_keys` |

---

## 10. Workflow Changes

### Agent startup (automated)

1. Session starts via `start_agent_session(profile_id=...)`.
2. Agent calls `get_next_task(agent_session_id=...)`.
3. Agent claims with `claim_task(task_id, assigned_to=agent_session_id)`.
4. Agent loads `task_spec` (+ project/milestone specs + resolved execution policy).
5. If blocked: `create_clarification` routes by domain ownership.
6. During execution, evidence writes require matching active session/claim token.
7. On completion: evidence + handoff + review child tasks + reconciliation + G1-G5 -> `done`.

### Review workflow (dual-review)

1. Parent implementation task created.
2. Required child review tasks created (`review_judgment`, `review_coverage`).
   Each child `task_spec` includes a `review_ref` pointing to the parent's
   branch or commit, so the reviewer examines the actual implementation diff.
3. Reviewer agent claims a review child task and performs a code review —
   reading the diff, evaluating correctness, identifying risks, and recording
   findings. This is not a self-audit; the reviewer has no prior context from
   the implementation and approaches the code as an independent critic.
4. If the reviewer approves, the review task moves to `done`. If the reviewer
   requests changes, the review task returns to `open` and the implementer
   addresses the findings. Steps 3-4 repeat until approved.
5. Child reconciliation task merges findings and records final disposition.
6. Parent closes only after child review/reconciliation tasks are complete.

### Clarification resolution

1. Worker raises clarification -> hive sets `routed_to`.
2. Routed owner retrieves via pending clarification query.
3. Owner answers -> worker task auto-unblocks (existing behavior).
4. Unresolved clarifications escalate milestone owner -> project owner -> human queue.

### Task creation from implementation plan

1. Create project with intent fields + `project_spec` + default execution policy.
2. Create milestones with `domain`, `owner`, `milestone_spec`, policy overrides.
3. Create tasks with `task_spec`, capabilities/trust, review/workflow type, GitHub links.
4. Encode implementation/review/reconciliation dependencies explicitly.

---

## 11. Rollout Plan

### Phase 1: Identity + Spec + Policy Foundations

1. Add profile/session/capability schema tables.
2. Add `*_spec` and `execution_policy` columns.
3. Add task workflow columns (`task_type`, `parent_task_id`).
4. Implement profile/session management tools.
5. Add spec validation logic and tool.

Success criteria:

- Agent profile/session lifecycle works with lease heartbeat.
- Project/milestone/task specs are accepted and validated.
- Execution policy can be stored and resolved per task.

### Phase 2: Routing + Execution Enforcement

1. Implement capability/trust filtering with session identity.
2. Enforce execution policy checks at claim/start.
3. Add stale-lease handling and stale claim recovery.
4. Add idempotency handling for all mutating operations via `hive.task_idempotency_keys`.
5. Enforce `actor_id` for all new gate/override/evidence writes.

Success criteria:

- Ineligible sessions cannot see/claim tasks outside capability/trust policy.
- Shared-clone branch interference is prevented by policy enforcement.

### Phase 3: Review Workflow and Clarification Routing

1. Enforce parent-child review/reconciliation closure gating.
2. Add reconciliation artifact requirements.
3. Implement full clarification routing query surface (`routed_to`).

Success criteria:

- Parent implementation tasks cannot close before required review child tasks.
- Dual-review workflow is machine-enforced, not convention-based.

---

## 12. Validation Plan Extension

v1.0 validation extends `docs/VALIDATION_PLAN.md` with scenarios:

- **T12: Agent profile/session lifecycle**
  - Create profile, start session, heartbeat, expire session.
- **T13: Capability-filtered selection**
  - Verify ineligible session cannot receive/claim restricted tasks.
- **T14: Trust and gate-compliant enforcement**
  - Verify trust thresholds and `gate_compliant` restrictions.
- **T15: Execution policy enforcement**
  - Verify dedicated worktree/per-task branch checks block invalid claims.
- **T16: Spec validation**
  - Reject invalid `project_spec`, `milestone_spec`, `task_spec` payloads.
- **T17: Dual-review child-task gating**
  - Parent implementation task cannot move to `done` until review/reconciliation children are done.
- **T18: Clarification routing**
  - Verify `routed_to` chain and escalation behavior.
- **T19: Session concurrency**
  - Multiple sessions of same profile do not conflict due to leases/workspace policy.
- **T20: Idempotency**
  - Replayed create/claim calls do not duplicate work.
- **T21: Evidence claim/session validation**
  - Evidence write with wrong `claim_token` is rejected.
  - Evidence write with expired/inactive session is rejected.
- **T22: Actor tracking**
  - New gate/override/evidence writes always include non-null `actor_id`.
- **T23: Claim token session binding**
  - `claim_task` stores `claim_session_id` alongside `claim_token`.
  - `update_task(status=done)` with correct token but wrong session ID is rejected.
  - `claim_token` does not appear in `get_next_task` or `list_tasks` responses.
- **T24: Profile ID format enforcement**
  - Profile IDs not matching `^[a-z0-9][a-z0-9._-]{2,63}$` are rejected at INSERT.
  - `register_agent_profile` fails on duplicate ID (insert-only).
  - `update_agent_profile` rejects caller whose `actor_id` does not match `created_by`.
- **T25: JSONB payload size limits**
  - `task_spec` exceeding 64 KB is rejected at INSERT/UPDATE.
  - `execution_policy` exceeding 16 KB is rejected at INSERT/UPDATE.
  - Same limits enforced on project and milestone specs.
- **T26: Self-review prevention at profile level**
  - G4 rejects review evidence where reviewer's `profile_id` matches the
    implementation author's `profile_id`, even when session IDs differ.
- **T27: Routing field write restriction**
  - `update_task` rejects changes to `excluded_agents` or `preferred_agent` when
    caller is not the task creator or project/milestone owner.
- **T28: Parent-child depth enforcement**
  - `create_task` with `parent_task_id` pointing to a task that itself has a
    non-null `parent_task_id` is rejected (no grandchildren).
  - `parent_task_id = id` is rejected by CHECK constraint.
- **T29: Identity audit logging**
  - Profile creation, update, session start/end/expire, and capability changes
    each produce a row in `hive.agent_audit_log`.
- **T30: Task created_by immutability**
  - `create_task` sets `created_by` from caller's `actor_id`.
  - `update_task` rejects any attempt to change `created_by`.
- **T31: Claim-state atomicity**
  - `claim_task` sets `claim_token`, `claim_session_id`, and `heartbeat_deadline` together.
  - Attempting to INSERT/UPDATE a task with `claim_token` set but `claim_session_id`
    NULL (or any other partial combination) is rejected by CHECK constraint.
  - `claim_session_id` must reference a valid `agent_sessions.id` (FK enforced).
- **T32: Status canonicalization**
  - Task status `cancelled` is rejected by CHECK constraint after migration.
  - `superseded` is accepted as a terminal status.
  - G0 and dependency queries treat `superseded` as terminal.
- **T33: Review task requires review_ref**
  - `create_task` with `task_type` of `review_judgment` or `review_coverage` and
    a `task_spec` missing `review_ref` is rejected.
  - `review_ref` must be a non-empty string (branch name or commit SHA).
- **T34: Review changes-requested cycle**
  - Review task with `verdict: "changes_requested"` returns to `open` with claim
    fields cleared.
  - Review task with `verdict: "approved"` moves to `done`.
  - Parent implementation task remains blocked by G0 while review task is `open`.
- **T35: Claim-aware blocking**
  - Clarification raised on `in_progress` task: status becomes `blocked`, claim
    fields are preserved (agent keeps claim).
  - Clarification answered: `blocked` (claimed) returns to `in_progress`, not
    `open`. Agent resumes without re-claiming.
  - Clarification raised on `open` (unclaimed) task: status becomes `blocked`,
    claim fields stay NULL. Unblock returns to `open`.
- **T36: Invalid transition rejection**
  - `open` -> `done` is rejected (must claim first).
  - `done` -> `in_progress` is rejected (must reopen first).
  - `superseded` -> `done` is rejected (must reopen first).

---

## 13. Migration Guidance

v1.0 is a breaking upgrade from v0.9 beta usage.

Migration approach:

1. Apply v1 schema migrations (includes status rename `cancelled` -> `superseded`).
2. Seed capability taxonomy + profile matrix from `config/agent_matrix.toml`.
3. Backfill `created_by` on existing tasks from `assigned_to` or a default actor.
4. Enforce `created_by` non-null (`ALTER TABLE hive.tasks ALTER COLUMN created_by SET NOT NULL`).
5. Migrate/seed tasks into `task_spec` and workflow types.
6. Rebuild implementation/review relationships as parent-child links.
7. Enable dual-review closure gates after migration verification.
8. Backfill `actor_id` where possible for seeded/migrated records; enforce non-null for all new writes at application layer.

No runtime backward-compatibility layer is required.

---

## 14. Acceptance Criteria for This Design

This design is accepted when:

1. It has one independent review with resolved major findings.
2. Implementation tasks are created directly from sections 8-11.
3. All schema additions have corresponding migration files.
4. `VALIDATION_PLAN.md` is extended with T12-T36 before Phase 2 begins.
5. v1 migration + validation suite passes in a clean environment.
6. Dual-review parent/child closure policy is enforced in automated tests.
7. Execution policy prevents shared-workspace branch interference in automated tests.

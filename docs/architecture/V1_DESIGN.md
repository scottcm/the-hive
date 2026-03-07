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

4. **No enforceable review workflow.** Review cannot be gated via task structure.
   <!-- v1.1: extends to dual-review with judgment + coverage modes -->

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
3. Support review workflows as first-class policy with child task gating. <!-- v1.1: dual-review with reconciliation -->
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

#### 7.1a Agent Session State Machine

Session statuses: `active | inactive | expired`.

| From | To | Trigger | Side effects |
| --- | --- | --- | --- |
| `active` | `inactive` | `end_agent_session` | Auto-release all tasks claimed by this session (in_progress -> open, blocked-claimed -> blocked-unclaimed) |
| `active` | `expired` | Recovery job: `lease_expires_at < now()` | Auto-release all tasks claimed by this session; log `session_expired` audit event |

Both `inactive` and `expired` are terminal. A terminated session cannot be
reactivated — start a new session with a new ID instead. Old session rows
remain for audit history.

In-state operations on `active` sessions:

- `heartbeat_agent_session` extends `lease_expires_at` and updates
  `last_heartbeat_at`.
- `claim_task` requires session status = `active` and `lease_expires_at > now()`.
- Any mutating operation with an `inactive` or `expired` session is rejected.

**Profile deactivation cascade.** Setting `agent_profiles.active = false` via
`update_agent_profile` auto-expires all `active` sessions for that profile.
This prevents zombie sessions that are mechanically active but ineligible for
any work.

**Session uniqueness.** Session IDs are primary keys. A new session requires a
new ID. If a session crashes and is expired by the recovery job, the agent
starts a fresh session with a different ID (e.g., incrementing the suffix).

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

<!-- v1.1: splits review into review-judgment and review-coverage roles — see V1.1_DEFERRED.md #D2 -->
Initial review role:

- `review` (code review: correctness, risk, coverage)

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

#### 7.3a Project State Machine

Project statuses: `active | archived`.

| From | To | Trigger | Condition |
| --- | --- | --- | --- |
| `active` | `archived` | `update_project(status=archived)` | All milestones are `done` or `archived` |
| `archived` | `active` | `update_project(status=active)` | — |

Archiving a project with `active` milestones is rejected. This forces
explicit resolution of in-flight work before shelving a project.

#### 7.3b Milestone State Machine

Milestone statuses: `active | done | archived`.

| From | To | Trigger | Condition |
| --- | --- | --- | --- |
| `active` | `done` | `update_milestone(status=done)` | All tasks under milestone are `done` or `superseded` |
| `active` | `archived` | `update_milestone(status=archived)` | All tasks under milestone are `done` or `superseded` |
| `done` | `active` | `update_milestone(status=active)` | — |
| `done` | `archived` | `update_milestone(status=archived)` | — |
| `archived` | `active` | `update_milestone(status=active)` | — |

Invalid: `archived` -> `done` (must reactivate first).

`done` means the milestone goal was achieved. `archived` means it was shelved
or superseded. Both require all child tasks to be terminal (`done` or
`superseded`) before the transition is accepted. Reopening (`done` -> `active`
or `archived` -> `active`) has no preconditions — new tasks can then be created
under the reactivated milestone.

### 7.4 Enriched Task Record and Task Types

Tasks gain structured execution data and workflow typing.

Agent execution fields:

- `task_spec` (JSON schema validated; see `TASK_SPEC_SCHEMA.md` for per-type
  required/optional keys, mutation policy, failure policy, and output contracts)
- `context`
- `acceptance_criteria`
- `github_issue_ids`

Routing and policy fields:

- `required_capabilities`
- `min_trust_level`
- `excluded_agents` (write-restricted; see below)
- `preferred_agent` (write-restricted; see below)
<!-- v1.1: splits review into review_judgment, review_coverage, review_reconciliation — see V1.1_DEFERRED.md #D2 -->
- `task_type` (`implementation | review | misc`)
  - `review` tasks are **code reviews**, not self-audits. The reviewer examines
    the parent task's implementation diff and artifacts as an independent critic.
    The `task_spec` for review tasks must reference the parent's branch/commit
    and frame the work as a code review, not a checklist the implementing agent
    runs against its own output.
- `parent_task_id` (nullable; links review tasks to parent implementation)
- `execution_policy` (JSON schema validated, task-level override)

Routing and policy field write policy: `excluded_agents`, `preferred_agent`,
and `execution_policy` can only be set at task creation time or updated by
the task's project/milestone owner. `update_task` rejects changes to these
fields unless the caller's `actor_id` matches the task creator or the owning
project/milestone `owner`. This prevents agents from monopolizing work,
excluding competitors, or escalating completion privileges (e.g., setting
`auto_merge = true` on a task they don't own).

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
2. Profile has all required capabilities at eligible level (`strong` or
   `marginal`). Level `blocked` disqualifies the profile for that capability.
   <!-- v1.1: adds routing preference for strong over marginal — see V1.1_DEFERRED.md #D4 -->
3. Profile trust level meets/exceeds `min_trust_level`.
4. Session/profile is not in `excluded_agents`.
5. `gate_compliant` is true when `min_trust_level > low`.
6. Execution-policy preconditions pass (worktree/branch lease checks).
7. Existing queue filters still apply (status/dependencies/not already claimed).
8. No owner/domain authorization filter is applied in v1.0 (default-open access).
9. For `review` task types, the claiming session's `profile_id` must differ
   from the parent implementation task's author `profile_id`. This is a
   fail-fast enforcement of G4 review separation at claim time — an agent
   cannot claim a review of its own work.

v1 access policy: default-open visibility (no owner access filtering). Ownership fields
remain for routing and future v2 authorization.

`claim_task` re-validates eligibility to prevent race conditions.

### 7.6 Review as Child Tasks

<!-- v1.1: expands to dual review (judgment + coverage) + reconciliation — see V1.1_DEFERRED.md #D2 -->

For implementation work requiring review:

1. Create one parent `implementation` task.
2. Create one child `review` task (`parent_task_id = implementation_id`).

Parent implementation task cannot move to `done` until the child review task
is `done` (enforced by G0 child closure).

**Code review, not self-audit.** v0.9 allowed agents to satisfy G4 by recording
`review_output` evidence against their own work — effectively a self-audit
checklist. v1 eliminates this pattern. Review child tasks are code reviews:
the reviewer reads the parent's implementation diff, evaluates correctness and
risk, and records findings as an independent critic. The `task_spec` for the
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
author's `claim_session_id` and the reviewer's `actor_id`. The invariant is:
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

<!-- v1.1: adds timeout-based auto-escalation — see V1.1_DEFERRED.md #D3 -->
**Escalation trigger (v1.0).** Escalation is manual: the current routee calls
`update_clarification(id, routed_to=<next_in_chain>)` to pass the
clarification up the chain. Automatic timeout-based escalation is deferred to
v1.1. The chain order is: milestone owner -> project owner -> `human-required`
(a sentinel value indicating the clarification needs human attention outside
the system).

#### 7.7a Clarification State Machine

Clarification statuses: `pending | answered`.

| From | To | Trigger | Side effects |
| --- | --- | --- | --- |
| `pending` | `answered` | `answer_clarification` | Auto-unblock task if no other `pending` clarifications remain for that task |

`answered` is terminal. If the answer is insufficient, create a new
clarification — this preserves the audit trail and avoids ambiguity about
which answer resolves which question.

**Creation constraints.** `create_clarification` is only valid when the target
task is `open`, `in_progress`, or `blocked`. It is rejected when the task is
`done` or `superseded` — terminal tasks cannot be blocked.

**Claim-aware auto-block/unblock integration.** Clarification creation and
resolution interact with the task state machine (section 7.4a):

- Creating a clarification on an `in_progress` task transitions it to
  `blocked` with claim fields preserved (agent keeps claim).
- Creating a clarification on an `open` task transitions it to `blocked`
  with claim fields staying NULL.
- Creating a clarification on an already `blocked` task is a no-op on task
  status (task is already blocked; the new clarification adds to the pending
  queue).
- Answering the last pending clarification unblocks: claimed tasks return to
  `in_progress`, unclaimed tasks return to `open`.
- If other pending clarifications remain after an answer, the task stays
  `blocked`.

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

**Completion actions.** The execution policy defines what the agent does
after gates pass and the task moves to `done`:

- `on_complete = push_and_pr` — agent pushes the task branch and creates a
  pull request against `target_branch` (default: `main`).
- `on_complete = push_only` — agent pushes but does not create a PR (useful
  when a manager or CI creates PRs).
- `on_complete = none` — agent does not push (branch stays local; a manager
  or pipeline handles delivery).

**Task type defaults:** `implementation` tasks default to
`on_complete = push_and_pr`. `review` tasks default to `on_complete = none`
(read-only, no branch to push). `misc` tasks default to `on_complete = none`.
Task creators can override these defaults in `execution_policy`.

Additional completion policy keys:

- `target_branch` (default: `main`) — PR target / merge base. Validated
  against `^[a-zA-Z0-9._/-]+$` and must not equal the task's own branch.
  Branch existence is validated at PR creation time.
- `auto_merge = false` (default) — if `true`, the PR is merged by the
  implementing agent after confirming the review child task is `done`. If
  the implementing agent's session expires before review completes, the
  merge is deferred to a manager or the next agent that claims a follow-up
  task. `auto_merge = true` is appropriate only when CI checks provide
  sufficient merge-time validation; it does not wait for external CI
  pipelines.
- `pr_title_template` (default: `task/{task_id}: {task_title}`) — PR title
  format. Interpolated values have newlines and control characters stripped;
  total title is truncated to 200 characters.
- `delete_branch_on_merge = true` (default) — clean up the task branch after
  merge.

**Input validation.** All rendered branch names (from `branch_name_template`,
`task_spec.branch`, or `target_branch`) are validated against
`^[a-zA-Z0-9._/-]+$` before any git operation. `task_spec.branch` overrides
follow the same validation rules as `branch_name_template` interpolated
values.

**Completion ordering.** Completion actions execute **after** the task
transitions to `done`, not before:

1. Agent records all evidence (diff, tests, audit, handoff).
2. Agent calls `update_task(status=done)` — gates validate evidence. If
   gates fail, the task stays `in_progress` and no completion actions run.
3. Gates pass, task transitions to `done`, claim fields cleared.
4. Agent executes completion actions (push, PR creation).
5. Agent records `pr_url` as a post-completion evidence artifact.

If a completion action fails (e.g., PR creation fails because target branch
doesn't exist), the task stays `done` (gates already passed). The agent
raises a clarification or adds a note flagging the delivery failure.
Completion actions are idempotent: `git push` is safe for identical content,
PR creation checks for an existing PR on the same branch, and merge checks
PR state before acting.

### 7.9 Stale-Claim Recovery

A background job recovers claims from dead or unresponsive agents.

Timing parameters:

- **Session heartbeat interval**: agents call `heartbeat_agent_session` every
  5 minutes to extend `lease_expires_at`.
- **Session lease**: `start_agent_session` sets `lease_expires_at = now() + 15 min`.
  Each heartbeat extends the lease by another 15 minutes.
- **Task claim deadline**: `claim_task` sets `heartbeat_deadline` equal to the
  session's `lease_expires_at`. Each `heartbeat_agent_session` propagates the
  new lease to all tasks claimed by that session.
- **Grace period**: the recovery job runs every 5 minutes. The 15-minute lease
  provides a 10-minute grace window beyond the expected 5-minute heartbeat
  interval.
<!-- v1.1: task-level heartbeat becomes independent — see V1.1_DEFERRED.md #D1 -->

Recovery behavior:

1. **Session-level heartbeat expiry.** Expire sessions with lapsed leases:
   `UPDATE hive.agent_sessions SET status = 'expired' WHERE status = 'active' AND lease_expires_at < now()`.
   <!-- v1.1: adds independent task-level heartbeat expiry sweep, see V1.1_DEFERRED.md #D1 -->
2. **Session-level expiry cascade.** When `agent_sessions.status` becomes `expired`
   (lease expiry or profile deactivation), the recovery job releases all tasks
   claimed by that session, regardless of task status or `heartbeat_deadline`:
   - `in_progress` tasks transition to `open`, claim fields cleared.
   - `blocked` (claimed) tasks stay `blocked`, claim fields cleared
     (blocked-claimed -> blocked-unclaimed).
   - SQL: `UPDATE hive.tasks SET assigned_to = NULL, claim_token = NULL, claim_session_id = NULL, heartbeat_deadline = NULL, status = CASE WHEN status = 'in_progress' THEN 'open' ELSE status END WHERE claim_session_id = $expired_session_id`.
3. **Gate event emission.** A `gate_event` with `gate_name = 'heartbeat_expired'`
   is emitted for every task whose claim is released by steps 1 or 2, regardless
   of whether the task was `in_progress` or `blocked` at the time of release.

**Transactionality.** Each session-expiry cascade (step 1 session expiry +
step 2 task releases + step 3 gate event inserts for that session) runs in a
single database transaction to ensure gate events are emitted atomically with
task releases. Idempotency key cleanup runs as an independent operation —
it is idempotent and safe to retry on failure.

<!-- v1.1: independent task-level heartbeat deferred, see docs/architecture/V1.1_DEFERRED.md #D1 -->
**Heartbeat contract.** Agents must heartbeat their session
(`heartbeat_agent_session`, extends `lease_expires_at`). Task claim liveness
is derived from session liveness — `claim_task` sets `heartbeat_deadline`
equal to `lease_expires_at`, and each `heartbeat_agent_session` call
propagates the new deadline to all tasks claimed by that session. Independent
per-task heartbeat deadlines are deferred to v1.1.

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
                                       CHECK (task_type IN ('implementation', 'review', 'misc')),
                                       -- v1.1: adds review_judgment, review_coverage, review_reconciliation
    ADD COLUMN parent_task_id         int REFERENCES hive.tasks(id)
                                       CHECK (parent_task_id != id),
    ADD COLUMN replacement_task_id   int REFERENCES hive.tasks(id)
                                       CHECK (replacement_task_id != id),
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

**Replay semantics.** Idempotency keys are globally unique — callers are
responsible for namespacing (e.g., prefixing with agent session ID). Behavior:

- **Key miss:** execute the operation normally, store the result in
  `result_json` with a 24-hour TTL.
- **Key hit:** return the stored `result_json` without re-executing. Payload
  consistency is not checked — the key alone is the discriminator. This means
  a replayed `claim_task` returns the original claim result (no double-claim
  error), and a replayed `create_task` returns the original task (no
  duplicate).
- **Expired key:** treated as a miss (operation re-executes).

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
| `heartbeat_agent_session` | Refresh session lease (`lease_expires_at`). Propagates new deadline to `heartbeat_deadline` on all tasks where `claim_session_id` matches this session (§7.9). |
| `heartbeat_task` | v1.0: no-op alias (task deadline derived from session lease). v1.1: independently extends `heartbeat_deadline`. <!-- v1.1: see V1.1_DEFERRED.md #D1 --> |
| `end_agent_session` | Mark session inactive |
| `list_agent_profiles` | List registered profiles |
| `list_capabilities` | Return capability taxonomy and levels |
| `validate_spec` | Validate project/milestone/task spec payload against current schema version |
| `release_task` | Release an active claim; transitions `in_progress` -> `open`, clears claim fields. Requires `task_id` + `claim_token`. Also used internally by `end_agent_session` and the recovery job. |
| `supersede_task` | Transitions a task to `superseded` from `open`, `in_progress`, `blocked` (claimed or unclaimed). Clears claim fields if present. Parameters: `task_id`, `replacement_task_id` (optional, recorded for traceability), `reason`. v1.0: cooperative-only — any agent may call, restricted by deployment boundary. <!-- v1.1: consider owner/manager check --> |
| `reopen_task` | Transitions a `done` or `superseded` task back to `open`. Claim fields stay NULL. Parameters: `task_id`, `reason`. v1.0: cooperative-only — any agent may call, restricted by deployment boundary. <!-- v1.1: consider owner/manager check --> |

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
| `update_clarification` | Update `routed_to` for manual escalation (v1.0 escalation trigger) |
| `list_clarifications` | Add filtering by `routed_to` |
| All mutating tools | Support optional `idempotency_key`; resolve through `hive.task_idempotency_keys` |

All tools are designed for both agent and human callers. Human operators
interact through the same API surface via dashboard, CLI, or direct MCP calls.

---

## 10. Workflow Changes

### Agent startup (automated)

1. Session starts via `start_agent_session(profile_id=...)`.
2. Agent calls `get_next_task(agent_session_id=...)`.
3. Agent claims with `claim_task(task_id, assigned_to=agent_session_id)`.
4. Agent loads `task_spec` (+ project/milestone specs + resolved execution policy).
5. If blocked: `create_clarification` routes by domain ownership.
6. During execution, evidence writes require matching active session/claim token.
7. On completion: evidence + handoff + review child task + G0-G5 -> `done`.

### Review workflow

<!-- v1.1: expands to dual-review with reconciliation — see V1.1_DEFERRED.md #D2 -->

1. Parent implementation task created.
2. Child `review` task created. The `task_spec` includes a `review_ref`
   pointing to the parent's branch or commit, so the reviewer examines the
   actual implementation diff.
3. Reviewer agent claims the review task and performs a code review — reading
   the diff, evaluating correctness, identifying risks, and recording findings.
   This is not a self-audit; the reviewer has no prior context from the
   implementation and approaches the code as an independent critic.
4. If the reviewer approves, the review task moves to `done`. If the reviewer
   requests changes, the review task returns to `open` and the implementer
   addresses the findings. Steps 3-4 repeat until approved.
5. Parent closes only after the child review task is complete (G0 enforced).

### Clarification resolution

1. Worker raises clarification -> hive sets `routed_to`.
2. Routed owner retrieves via pending clarification query.
3. Owner answers -> worker task auto-unblocks (existing behavior).
4. Unresolved clarifications escalate milestone owner -> project owner -> human queue.

### Task creation from implementation plan

1. Create project with intent fields + `project_spec` + default execution policy.
2. Create milestones with `domain`, `owner`, `milestone_spec`, policy overrides.
3. Create tasks with `task_spec`, capabilities/trust, review/workflow type, GitHub links.
4. Encode implementation/review dependencies explicitly.

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

1. Enforce parent-child review closure gating (G0).
2. Implement full clarification routing query surface (`routed_to`).

Success criteria:

- Parent implementation tasks cannot close before the review child task is done.
- Review workflow is machine-enforced, not convention-based.
<!-- v1.1: Phase 3 expands to dual-review + reconciliation -->

---

## 12. Validation Plan Extension

v1.0 validation extends `docs/VALIDATION_PLAN.md` with scenarios:

- **T12: Agent profile/session lifecycle**
  - Create profile, start session, heartbeat, end session (section 7.1a).
- **T13: Capability-filtered selection**
  - Verify ineligible session cannot receive/claim restricted tasks.
- **T14: Trust and gate-compliant enforcement**
  - Verify trust thresholds and `gate_compliant` restrictions.
- **T15: Execution policy enforcement**
  - Verify dedicated worktree/per-task branch checks block invalid claims.
- **T16: Spec validation**
  - Reject invalid `project_spec`, `milestone_spec`, `task_spec` payloads.
- **T17: Review child-task gating**
  - Parent implementation task cannot move to `done` until review child is done.
  <!-- v1.1: extends to dual-review + reconciliation children -->
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
  - `create_task` with `task_type` of `review` and a `task_spec` missing
    `review_ref` is rejected.
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
- **T37: Session lifecycle**
  - `end_agent_session` on active session with claimed tasks: tasks are
    auto-released (in_progress -> open, blocked-claimed -> blocked-unclaimed),
    session becomes `inactive`.
  - `heartbeat_agent_session` on `inactive` or `expired` session is rejected.
  - `claim_task` with `inactive` or `expired` session is rejected.
  - Recovery job expires session when `lease_expires_at < now()`, releases
    all claimed tasks, logs `session_expired` audit event.
  - Terminal session IDs cannot be reused (`start_agent_session` with existing
    ID fails).
- **T38: Profile deactivation cascade**
  - Setting `agent_profiles.active = false` auto-expires all `active` sessions
    for that profile.
  - Tasks claimed by those sessions are auto-released.
- **T39: Clarification creation on terminal task**
  - `create_clarification` on a `done` task is rejected.
  - `create_clarification` on a `superseded` task is rejected.
  - `create_clarification` on `open`, `in_progress`, or `blocked` task
    succeeds.
- **T40: Clarification multi-pending unblock**
  - Two clarifications on same task: answering first keeps task blocked;
    answering second unblocks task.
  - Claimed task unblocks to `in_progress` (not `open`).
- **T41: Milestone done with active tasks**
  - `update_milestone(status=done)` is rejected when any task under the
    milestone is `open`, `in_progress`, or `blocked`.
  - Accepted when all tasks are `done` or `superseded`.
- **T42: Project archive with active milestones**
  - `update_project(status=archived)` is rejected when any milestone is
    `active`.
  - Accepted when all milestones are `done` or `archived`.
- **T43: Milestone archived -> done rejected**
  - `update_milestone(status=done)` from `archived` is rejected (must
    reactivate first).

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
7. Enable review closure gates (G0 child closure) after migration verification.
8. Backfill `actor_id` where possible for seeded/migrated records; enforce non-null for all new writes at application layer.

No runtime backward-compatibility layer is required.

---

## 14. Acceptance Criteria for This Design

This design is accepted when:

1. It has one independent review with resolved major findings.
2. Implementation tasks are created directly from sections 8-11.
3. All schema additions have corresponding migration files.
4. `VALIDATION_PLAN.md` is extended with T12-T43 before Phase 2 begins.
5. v1 migration + validation suite passes in a clean environment.
6. Review parent/child closure policy is enforced in automated tests.
7. Execution policy prevents shared-workspace branch interference in automated tests.

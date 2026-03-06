# Prior Art Research: Agentic Workflow Coordination for The Hive v1.0

*Report date: 2026-03-06. Baseline: The Hive v0.9 (G1–G5 gates, MCP + FastAPI + Postgres).*

---

## 1. Executive Summary (12 lines)

**Adopt for v1:**
Temporal's **lease + heartbeat** pattern (schedule-to-start + heartbeat-timeout fields) maps directly to stale-claim recovery with no custom code. Apply it to `claim_task`: a `claimed_at` + `heartbeat_deadline` column plus a background task that resets stale claims gives full recovery. The Jira **sub-task blocking condition** — "parent cannot close until all child tasks reach a terminal state" — is the correct primitive for the parent/child enforcement gap; add a DB-level check in the `done` gate. For dual-review reconciliation, GitHub Actions' **required status checks + wrapper-job pattern** translates cleanly: a `review_policy` field that declares `{judgment: required, coverage: required, reconciliation: required}` plus a gate that counts distinct-role reviewers before allowing `done`. For agent routing, CrewAI's `allowed_agents` + Swarm's **typed handoff** pattern maps to the `required_capabilities` + `excluded_agents` model already in v1 design — validate at claim time, not just at queue time. For idempotency, use **client-supplied idempotency keys** (Stripe/Morling pattern) on all mutating MCP tools; the DB enforces uniqueness via `ON CONFLICT DO NOTHING`. For v2 seams: add an `actor_id` field to every mutable operation now — this is the only identity primitive that must exist before auth can be added without rewriting gate logic.

---

## 2. Comparison Table

| System | Relevant Pattern | Evidence Link | Maturity (2026-03) | Key Tradeoffs |
|---|---|---|---|---|
| **Temporal.io** | Lease heartbeats; parent/child workflows; activity task tokens; idempotent retry via WorkflowID | [docs.temporal.io/activities](https://docs.temporal.io/activities) / [child-workflows](https://docs.temporal.io/child-workflows) | Production GA (Temporal Cloud + OSS) | Full Temporal server is overkill for a Postgres-native queue; patterns are extractable |
| **AWS Step Functions** | `SendTaskHeartbeat` + `HeartbeatSeconds` for stale worker detection; task token as external claim | [docs.aws.amazon.com/step-functions/.../concepts-activities](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-activities.html) | Production GA | SFn is managed AWS infra; the heartbeat/token pattern is portable |
| **Jira Workflow Engine** | Sub-task blocking condition blocks parent `Done` transition until all children terminal | [support.atlassian.com: prevent closing issues with open sub-tasks](https://support.atlassian.com/jira/kb/how-to-prevent-issues-from-being-closed-while-the-sub-tasks-are-still-open-in-jira/) | Mature (20+ yrs) | Jira does it via GUI-configured workflow conditions; v1 needs DB-level constraint |
| **Linear** | Auto-close parent when all sub-issues done (Sept 2024 GA); blocking status rollup | [linear.app/changelog/2024-09-06-auto-close-parent-and-sub-issues](https://linear.app/changelog/2024-09-06-auto-close-parent-and-sub-issues) | Production GA (Sept 2024) | Linear is a SaaS product manager; patterns are extractable but the auto-close direction is parent->child not child->parent gate |
| **GitHub Actions** | `needs:` DAG; required status checks on branch protection; wrapper-job pattern for "all must pass" | [docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions) | Production GA | Gate is enforced at merge time, not task completion time; pattern maps to v1 `review_policy` check |
| **OpenAI Agents SDK** | Typed agent handoffs; agent-as-tool; guardrails (input/output validation) | [openai.github.io/openai-agents-python](https://openai.github.io/openai-agents-python/) | Production GA (2025) | Runtime framework; v1 needs static registry-based routing, not dynamic handoff chains |
| **CrewAI** | Role-based agents; `allow_delegation` + `allowed_agents`; hierarchical manager with validation | [docs.crewai.com/en/concepts/agents](https://docs.crewai.com/en/concepts/agents) / [PR #2068](https://github.com/crewAIInc/crewAI/pull/2068) | Active OSS (2025) | Delegation is runtime LLM-driven; v1 needs deterministic capability matching, not LLM-to-LLM delegation |
| **LangGraph** | Conditional edges on state; capability-scoped tool sets per node; HITL nodes as review gates | [langchain.com/langgraph](https://www.langchain.com/langgraph) / [docs.langchain.com/.../workflows-agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) | Production GA (May 2025) | Graph is the workflow; v1 is a queue with agents — mismatch. Conditional edge logic for routing is directly adoptable |
| **Celery** | `visibility_timeout` for lease; `acks_late` for at-least-once; idempotency via task state DB check | [docs.celeryq.dev/en/main/userguide/tasks.html](https://docs.celeryq.dev/en/main/userguide/tasks.html) | Stable OSS | Celery's timeout is broker-side (Redis/RabbitMQ); v1 uses Postgres so heartbeat must be DB-side |
| **Argo Workflows** | YAML DAG with `depends:` field; `suspend` template for approval gates; enhanced depends for conditional task trees | [argo-workflows.readthedocs.io/en/latest/enhanced-depends-logic](https://argo-workflows.readthedocs.io/en/latest/enhanced-depends-logic/) | Production GA (CNCF) | Kubernetes-native; DAG structure + suspend-for-approval pattern is directly relevant |
| **Event Sourcing / CQRS** | Append-only event log as audit trail; gate events as domain events; replay to rebuild state | [microservices.io/patterns/data/event-sourcing](https://microservices.io/patterns/data/event-sourcing.html) / [learn.microsoft.com/.../event-sourcing](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing) | Foundational pattern | v0.9 already has `hive.task_gate_events`; full CQRS is over-engineered; extend existing table |
| **Stripe Idempotency Keys** | Client-supplied `Idempotency-Key` header; server stores key+response; `ON CONFLICT` returns cached response | [morling.dev/blog/on-idempotency-keys](https://www.morling.dev/blog/on-idempotency-keys/) | Industry standard | Clear primary source; maps directly to MCP tool idempotency |

---

## 3. Deep Dives: Top 5 Systems

### 3.1 Temporal.io — Lease Heartbeats + Parent/Child Blocking

**Exact mechanism:**
Every Temporal *Activity* has four timeout fields:
- `schedule_to_start_timeout`: max wait between task being queued and a Worker picking it up. If exceeded -> `ScheduleToStartTimeout` error. Default: infinity.
- `start_to_close_timeout`: max execution duration per attempt. Strongly recommended explicit value.
- `schedule_to_close_timeout`: total budget across all retries. Default: infinity.
- `heartbeat_timeout`: if the Activity does not call `RecordHeartbeat` within this window, the Task is considered failed and may retry per the `RetryPolicy`. SDK throttles heartbeat calls to `0.8 * heartbeat_timeout`. If the server's in-memory state resets (shard reload), heartbeat timers can be lost — this is a documented bug ([PR #771](https://github.com/temporalio/temporal/pull/771)).

**Parent/child blocking:**
`ExecuteChildWorkflow` returns a `Future`. The Parent calls `.Get()` on that Future — execution blocks synchronously in the Workflow event loop until the child completes. The `ParentClosePolicy` controls what happens if the parent is cancelled: `TERMINATE`, `REQUEST_CANCEL`, or `ABANDON`. A parent workflow that calls `.Get()` on all child Futures is the canonical pattern for "parent cannot close until all children done."

**Idempotency:**
Temporal uses the `WorkflowID` as the natural idempotency key. `StartWorkflowExecution` with `WorkflowIDReusePolicy = REJECT_DUPLICATE` ensures at-most-one running workflow per ID. Activity retries re-run the function but the Workflow's event history deduplicates their side effects.

**Failure modes:**
- Shard-reload heartbeat timer loss (documented, fixed in modern server but watch for it).
- Misconfigured `schedule_to_start_timeout` = infinity means zombie tasks are never recovered if workers die without updating.
- Parent/child event histories grow unbounded for deeply nested trees; use `ContinueAsNew` for fan-out-heavy patterns.

**Migration fit for The Hive:**
Full Temporal adoption is disproportionate. The patterns are extractable:
- `claimed_at` + `heartbeat_deadline` columns on `hive.tasks` + background job = Temporal heartbeat at 10% complexity.
- `done` gate that checks all child task IDs are terminal = Temporal `.Get()` on child Futures.
- Do not adopt Temporal's event history model — v0.9's `hive.task_gate_events` already serves this role.

---

### 3.2 AWS Step Functions — Activity Task Token + Heartbeat

**Exact mechanism:**
Step Functions Activities use a **task token** model distinct from Temporal's worker-pull model:
1. State machine reaches an `Activity Task` state -> SF publishes a task to an activity queue with a unique `taskToken`.
2. Worker polls `GetActivityTask` -> receives `taskToken` + input.
3. Worker calls `SendTaskHeartbeat(taskToken)` periodically; each call resets the `HeartbeatSeconds` clock.
4. Worker calls `SendTaskSuccess(taskToken, output)` or `SendTaskFailure(taskToken, error)` on completion.
5. If `HeartbeatSeconds` elapses without a heartbeat -> SF transitions the state to error; `Catch` + `Retry` fields control recovery.

**Key field from API reference** ([SendTaskHeartbeat](https://docs.aws.amazon.com/step-functions/latest/apireference/API_SendTaskHeartbeat.html)): `taskToken` is a 1024-character opaque string. Task tokens can expire (documented community report: 6.5h expiry in some configurations).

**Idempotency:**
Standard Workflows log every state transition; `StartExecution` with the same `name` returns the existing execution. Express Workflows do NOT deduplicate. For task-level idempotency, use the `taskToken` as a natural key.

**Failure modes:**
- `taskToken` expiry at 6.5h for some execution types (community-documented, AWS re:Post).
- Workers that die without calling `SendTaskFailure` leave the task in limbo until `HeartbeatSeconds` elapses.
- Retry count on `Retry` policy is separate from the heartbeat — a task can exhaust retries while still within its total `TimeoutSeconds`.

**Migration fit:**
The task token model is the clearest direct precedent for The Hive's `claim_task` design. Current `assigned_to` + `claimed_at` maps 1:1. Missing: an opaque `claim_token` field on `hive.tasks` that the agent presents on `complete_task`/`update_task` (prevents stale-agent completing a task that was already reclaimed by another agent after timeout).

---

### 3.3 Jira + Linear — Parent/Child Blocking State Machines

**Jira exact mechanism** ([support.atlassian.com](https://support.atlassian.com/jira/kb/how-to-prevent-issues-from-being-closed-while-the-sub-tasks-are-still-open-in-jira/)):
Jira's Workflow engine attaches a **"Sub-Task Blocking Condition"** to the `Done` transition. Configuration: select which sub-task statuses count as "blocking" (e.g., any non-terminal status). The condition is evaluated at transition time — if any sub-task matches a blocking status, the transition is rejected with a user-visible error. This is enforced server-side in the workflow engine, not by client convention.

For dual-review enforcement: Jira supports **"Approval" sub-task types** that must be transitioned to `Approved` before the parent can close. Two separate approval sub-tasks with different assignees enforces the two-person integrity pattern. The third-party plugin JMWE extends this for more complex conditions.

**Linear exact mechanism** ([linear.app/changelog/2024-09-06](https://linear.app/changelog/2024-09-06-auto-close-parent-and-sub-issues)):
Linear's September 2024 GA feature adds **configurable auto-close policies** at the team level:
- "When all sub-issues are done -> close parent automatically"
- "When parent is closed -> close all remaining sub-issues"

This is a **bi-directional cascade** policy, not a blocking gate. The distinction matters: Jira's approach is a hard gate enforced on the server transition; Linear's is an automation that fires after the fact. For The Hive's use case (gate enforcement), the Jira model is the correct one.

**Failure modes:**
- Jira: the blocking condition can be bypassed by admins with direct workflow transition rights — not enforceable-by-code without restricting admin access.
- Linear: auto-close cascade fires asynchronously; a brief window exists where parent is "done" before sub-issues close.

**Migration fit:**
The Hive G1–G5 gate already runs server-side in `update_task`. Add a **G0 check**: before any `status=done` is accepted, query `SELECT count(*) FROM hive.tasks WHERE parent_task_id = $1 AND status NOT IN ('done', 'superseded')`. If > 0, reject with a structured error listing the blocking child task IDs. This is the direct code-enforceable equivalent of Jira's sub-task blocking condition.

Dual-review: The Hive's G4 already enforces `reviewer != author`. Extend `review_policy` to accept `{roles: ["judgment", "coverage"], require_reconciliation: true}`. G4 then checks: at least one `review_output` artifact with `metadata.role = "judgment"` AND one with `metadata.role = "coverage"` AND if both exist and disagree (`metadata.verdict` differs), a third `review_output` with `metadata.role = "reconciliation"` is required.

---

### 3.4 OpenAI Agents SDK + CrewAI — Capability Routing

**OpenAI Agents SDK exact mechanism** ([openai.github.io/openai-agents-python](https://openai.github.io/openai-agents-python/)):
- An `Agent` has a `name`, `instructions`, `tools`, and optional `handoffs` list.
- `handoffs` is a list of other Agent objects the agent is permitted to transfer control to.
- At runtime, if the model decides to hand off, it calls a tool named `transfer_to_<agent_name>` which is auto-generated from the handoffs list.
- **Guardrails** run on every input and output: they are functions that receive the `RunContext` and the model's response and may raise `InputGuardrailTripwireTriggered` or `OutputGuardrailTripwireTriggered` to block execution.
- The SDK does NOT enforce capability routing at registration time — routing is runtime model decision.

**CrewAI exact mechanism** ([docs.crewai.com/en/concepts/agents](https://docs.crewai.com/en/concepts/agents)):
- Agent fields: `role` (string), `goal` (string), `backstory` (string), `tools` (list), `allow_delegation` (bool), `allowed_agents` (list of agent names, added in [PR #2068](https://github.com/crewAIInc/crewAI/pull/2068)).
- When `allow_delegation=True`, CrewAI injects other agents as tools with names like `Delegate work to coworker` and `Ask question to coworker`.
- `allowed_agents` restricts which agents can be delegated to — this is the closest prior art for The Hive's `excluded_agents` pattern.
- A hierarchical crew assigns a **Manager LLM** that routes tasks to agents based on their `role` and `goal` descriptions.

**Key gap for The Hive:**
Both systems use runtime LLM decisions for routing. The Hive requires **deterministic, registry-enforced** routing. The correct model is closer to Jira's "assignee must have role X to claim transition Y" — a static capability check, not a dynamic LLM handoff. The v1 design's `required_capabilities[]` + `min_trust_level` fields are the right architecture; the AI-framework prior art validates the concept of capability-scoped routing but should not be copied at the mechanism level.

**Failure modes:**
- OpenAI Agents SDK: handoffs can loop if agents don't converge; add `max_turns` to prevent infinite delegation.
- CrewAI: LLM-driven delegation produces non-deterministic routing; `allowed_agents` helps but still model-dependent.

**Migration fit:**
Adopt the `allowed_agents`/`excluded_agents` concept directly. The registry lookup at `get_next_task` time is the correct enforcement point. Add a secondary check at `claim_task` (as the v1 design already specifies) to close the TOCTOU race.

---

### 3.5 Celery / Event Sourcing — Idempotency + Audit

**Celery idempotency exact mechanism** ([docs.celeryq.dev/en/main/userguide/tasks.html](https://docs.celeryq.dev/en/main/userguide/tasks.html)):
- `acks_late=True`: the broker does not acknowledge the message until the task function returns. If the worker crashes mid-execution, the message is redelivered. The task function MUST be idempotent.
- `visibility_timeout`: broker-side lease. If a worker picks up a task and does not ACK within this window, the broker re-delivers it (Redis default: 1 hour). Set this to at least the expected max task duration.
- **Application-level idempotency pattern**: before executing, check a `task_results` table for the task ID. If found, return the cached result. Use `ON CONFLICT DO NOTHING` in Postgres to handle concurrent inserts atomically.

**Idempotency key pattern (Stripe/Morling)** ([morling.dev/blog/on-idempotency-keys](https://www.morling.dev/blog/on-idempotency-keys/)):
- Client generates a UUID per logical operation and sends it as a header/field.
- Server stores `(idempotency_key, response_body, created_at)` in a table with `idempotency_key` as PRIMARY KEY.
- On duplicate: `SELECT response_body FROM idempotency_keys WHERE key = $1` -> return cached response.
- Key expires after a configurable window (Stripe: 24h); `created_at` column enables cleanup.

**Event sourcing for audit** ([learn.microsoft.com/.../event-sourcing](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)):
The Hive already has `hive.task_gate_events` (migration 009). This is the event store. To extend it properly:
- Every gate evaluation emits an event: `{task_id, gate, result, actor_id, timestamp, payload_hash}`.
- Events are append-only — no UPDATE or DELETE on this table.
- Current state is the projection of the event log, but the Hive stores current state separately in `hive.tasks` (CQRS read model). This is correct.
- The audit surface for v2 auth is already present if `actor_id` is on every gate event.

**Failure modes:**
- Celery `acks_late`: if the worker crashes after completing but before ACKing, the task runs twice — only safe if task is idempotent.
- Idempotency key collision: if keys are not globally unique (e.g., client reuses a key for a different operation), incorrect cached responses are returned. Use `task_id + operation_type` as composite key.
- Event store growth: `hive.task_gate_events` will grow unboundedly; add a `retention_days` policy and archive rather than delete.

**Migration fit:**
Add `idempotency_key` column to the tools that mutate task state (`claim_task`, `update_task`, `create_clarification`). Use Postgres `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING *` — if the row already exists, return the previous result. This is two lines of SQL per tool and covers all retry scenarios with zero application-layer complexity.

---

## 4. Adopt / Adapt / Avoid

### Adopt Now (v1 must-have)

| Pattern | Source | Concrete Implementation |
|---|---|---|
| **Heartbeat-based stale claim recovery** | Temporal / AWS Step Functions | Add `heartbeat_deadline timestamptz` to `hive.tasks`. `claim_task` sets it to `now() + interval '15 minutes'`. Background job resets `in_progress -> open` where `heartbeat_deadline < now()`. Agent calls `heartbeat_task(task_id)` every 5 min during work. |
| **Task token for claim validation** | AWS Step Functions | Generate opaque `claim_token uuid` on `claim_task`. Agent must present `claim_token` on `update_task(status=done)`. If token mismatch -> reject. Prevents stale agents completing tasks reclaimed by others. |
| **Parent/child blocking gate (G0)** | Jira sub-task blocking condition | New pre-gate G0: `SELECT count(*) WHERE parent_task_id=$1 AND status NOT IN ('done','superseded')`. Add `parent_task_id` FK to `hive.tasks`. Fail `done` if > 0. |
| **Dual-role review with reconciliation** | GitHub Actions required checks | Extend `review_policy` schema: `{required_roles: ["judgment","coverage"], reconciliation_if_disagree: true}`. G4 counts distinct `metadata.role` values across `review_output` artifacts; if verdicts disagree, require `role=reconciliation`. |
| **Idempotency keys on MCP tools** | Stripe / Morling pattern | Add `idempotency_key text UNIQUE` to `hive.tasks` mutations. `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING *` in every tool that creates or transitions a task. |
| **`actor_id` on every mutation** | RBAC seam (v2 readiness) | Add `actor_id text NOT NULL` to `hive.task_gate_events`, `hive.task_overrides`, `hive.task_evidence_artifacts`. This is the only v2 identity primitive needed now. |
| **Capability check at both `get_next_task` and `claim_task`** | CrewAI `allowed_agents`, OpenAI Swarm | Already in v1 design. Confirm: `claim_task` re-validates all six capability/trust filters, not just the ones checked at selection time. |

### Adapt Later (v1.1+)

| Pattern | Source | Why Not Now |
|---|---|---|
| **Full task token expiry + refresh** | AWS Step Functions (6.5h expiry) | Heartbeat + deadline covers the recovery case. Opaque token rotation adds complexity for minimal gain at current scale. |
| **Auto-close parent when all children done** | Linear Sept 2024 | Useful UX but not a correctness requirement. The blocking gate (G0) is the critical piece. |
| **Structured schema versioning for task specs** | Argo Workflows YAML `apiVersion` | Add `spec_version` field to tasks in v1.1 when task specs are stable enough to version. |
| **LangGraph-style conditional capability edges** | LangGraph | Currently over-engineered. Single-level capability list + trust level is sufficient for v1. |
| **Hierarchical manager agent** | CrewAI hierarchical process | Non-goal in v1.0 (section 5.3 of V1_DESIGN.md). |
| **OpenTelemetry trace spans on gate events** | OTel + OTEL Collector | Valuable for observability but not gate correctness. Add alongside dashboard v2. |

### Avoid (with reason)

| Pattern | Reason |
|---|---|
| **Full Temporal/Step Functions adoption** | Disproportionate infrastructure for a Postgres-native queue. The patterns are extractable without the frameworks. |
| **LLM-driven dynamic agent routing** (CrewAI manager LLM, OpenAI Swarm handoffs) | Non-deterministic. The Hive requires auditable, enforceable routing. A model deciding which agent gets a task is not enforceable by code. |
| **At-most-once delivery** (acknowledge-before-execute, Celery default) | Task state is in Postgres, not a broker. Use at-least-once with idempotency keys instead. |
| **Linear's auto-close cascade** (parent closes -> children close) | The Hive's direction must be child-blocks-parent, not parent-cascades-to-children. The Linear direction would allow circumventing gates by closing the parent. |
| **JIRA's admin-bypassable blocking conditions** | Jira conditions can be bypassed by workflow admins. The Hive's gate must be enforced in application code (Python function), not in a GUI configuration that can be changed by an admin. |
| **Full event-sourcing / CQRS rewrite** | `hive.task_gate_events` (migration 009) is already the event store. Full CQRS would require replacing the mutable `hive.tasks` table with a projection — over-engineered for the current team size. |
| **Idempotency key rotation with cached response** (full Stripe model) | The Hive is not a payment API. At-task-scope idempotency (claim once, complete once) is sufficient. Full response caching adds a cache-invalidation problem. |

---

## 5. Proposed v1 Deltas

### Schema Changes

```sql
-- G0: parent/child blocking
ALTER TABLE hive.tasks
    ADD COLUMN parent_task_id  uuid REFERENCES hive.tasks(id) ON DELETE SET NULL;
-- Note: compute children via SELECT WHERE parent_task_id = $1; do NOT add child_task_ids array
-- (denormalized array and FK can diverge; query is cheap enough at current scale)

-- Heartbeat lease
ALTER TABLE hive.tasks
    ADD COLUMN claim_token        uuid,          -- set on claim, cleared on done/release
    ADD COLUMN heartbeat_deadline timestamptz;   -- NULL when not claimed

-- Dual-role review tracking
-- No schema change required if task_evidence_artifacts.metadata is already JSONB.
-- Add index if not present:
CREATE INDEX IF NOT EXISTS idx_evidence_task_type
    ON hive.task_evidence_artifacts (task_id, artifact_type);

-- Idempotency on MCP tool calls
CREATE TABLE hive.idempotency_keys (
    key          text PRIMARY KEY,
    operation    text NOT NULL,       -- e.g., 'claim_task', 'update_task'
    result_json  jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL DEFAULT now() + interval '24 hours'
);
CREATE INDEX ON hive.idempotency_keys (expires_at);  -- for TTL cleanup job

-- actor_id on audit tables (v2 seam)
ALTER TABLE hive.task_gate_events
    ADD COLUMN actor_id text;         -- NULL for existing rows; NOT NULL after v2 auth lands
ALTER TABLE hive.task_overrides
    ADD COLUMN actor_id text;
ALTER TABLE hive.task_evidence_artifacts
    ADD COLUMN actor_id text;
```

### API/Tool Changes

| Tool | Change |
|---|---|
| `claim_task(task_id, assigned_to, idempotency_key?)` | Returns `claim_token` (UUID). Sets `heartbeat_deadline = now() + 15min`. Validates all 6 capability filters. Stores idempotency result. |
| `heartbeat_task(task_id, claim_token)` | New tool. Validates `claim_token` matches. Extends `heartbeat_deadline` by 15 min. Returns new deadline. |
| `update_task(task_id, ..., claim_token?)` | When transitioning to `done`: validate `claim_token`. Run G0 (no open children). Run extended G4 (dual-role). |
| `release_task(task_id, claim_token)` | New tool (or extend `update_task`). Clears `assigned_to`, `claim_token`, `heartbeat_deadline`. Task returns to `open`. |
| `create_task(..., parent_task_id?)` | Accept `parent_task_id`. FK enforced by DB. |
| All mutating tools | Accept optional `idempotency_key` field. Check `hive.idempotency_keys` before executing. |
| Background job (not MCP tool) | Every 5 min: `UPDATE hive.tasks SET status='open', assigned_to=NULL, claim_token=NULL, heartbeat_deadline=NULL WHERE status='in_progress' AND heartbeat_deadline < now()`. Emit a `gate_event` with `gate='heartbeat_expired'`. |

### Gate Changes

| Gate | Change |
|---|---|
| **G0 (new)** | Before `done`: `SELECT count(*) FROM hive.tasks WHERE parent_task_id = $task_id AND status NOT IN ('done','superseded')`. Fail if > 0. Error includes list of blocking child task IDs. |
| **G4 (extended)** | If `review_policy.required_roles` is set: count distinct `metadata.role` values across `review_output` artifacts. Require all declared roles present. If `reconciliation_if_disagree=true`: if any two reviewer verdicts disagree, require an artifact with `role='reconciliation'` before passing G4. Verdict vocabulary: `approved`, `changes_requested`, `rejected` (validated at evidence submission time). |
| **Claim validation (pre-gate)** | `claim_task` checks: (1) all `required_capabilities` present in agent registry, (2) `min_trust_level` <= agent trust, (3) agent not in `excluded_agents`, (4) `gate_compliant=true` if `min_trust_level > low`, (5) agent owner has domain access, (6) `claim_token` not already set (task not already claimed). |

### Validation Tests

```
T18: Heartbeat stale recovery
- Claim a task as agent-A; simulate deadline expiry.
- Run stale-claim recovery job.
- Verify task returns to open, claim_token cleared.
- Verify gate_event emitted with gate='heartbeat_expired'.
- Claim same task as agent-B; verify succeeds.

T19: Claim token enforcement
- Claim task as agent-A; capture claim_token.
- Attempt update_task(status=done) with wrong token -> expect 400.
- Attempt update_task with correct token -> expect success (gates permitting).

T20: Parent/child G0 blocking
- Create parent task P; create child task C with parent_task_id=P.
- Complete all gates on P; attempt update_task(P, status=done) -> expect fail (C still open).
- Complete C (status=done); reattempt P done -> expect success.

T21: Dual-role G4 review
- review_policy = {required_roles: ["judgment","coverage"], reconciliation_if_disagree: true}
- Submit only judgment review -> G4 fails (missing coverage).
- Submit coverage review with same verdict -> G4 passes.
- Submit coverage review with different verdict from judgment -> G4 fails (missing reconciliation).
- Submit reconciliation review -> G4 passes.

T22: Idempotency key deduplication
- Call claim_task with idempotency_key="abc123".
- Call claim_task again with same key -> verify returns same result, no second claim recorded.
- Verify task is claimed only once (assigned_to set once).
```

---

## 6. v2 Seam Check: Auth/RBAC Readiness

### Minimum Identity Primitives to Add in v1

Only one primitive must exist now to avoid a v2 rewrite:

**`actor_id text` on every mutable operation** (gate events, overrides, evidence artifacts, and the future agents table's `owner` field). This is the identity token that v2 will validate against an auth provider. If v1 stores `actor_id` as a free-text string (e.g., `"claude-scott"`, `"scott"`), v2 simply adds a `hive.actors` table mapping `actor_id -> verified_identity` and a lookup at request time. No existing audit records need to change — they already have the right column.

Do NOT add: JWT validation, session tokens, OAuth flows, role tables, or permission checks. These are all v2 work.

### Where Policy Checks Should Be Abstracted

| Current code location | v1 abstraction | v2 upgrade path |
|---|---|---|
| `get_next_task` capability filter | Move to a pure function `def agent_is_eligible(agent: AgentRecord, task: TaskRecord) -> bool` | v2 adds `def actor_is_authorized(actor_id, task, action) -> bool` — same interface, adds auth lookup |
| `claim_task` eligibility re-check | Same function called again | No change — just add the auth check inside `actor_is_authorized` |
| Gate engine (G1–G5) | `def evaluate_gate(gate: str, task_id, actor_id) -> GateResult` | v2 adds: verify `actor_id` has `can_complete_task` permission before calling gate engine |
| Override creation | `actor` field is free text today | v2 validates `actor` against auth token; same DB column |
| Clarification routing | `routed_to` is free text today | v2 resolves `routed_to` through actor directory for notification delivery |

### Which v1 Shortcuts Would Create v2 Rewrites

| Shortcut | Why it blocks v2 |
|---|---|
| Storing no `actor_id` on gate events (current v0.9 state) | v2 audit log requires identity on every event; backfill is lossy |
| Using `assigned_to text` as both identity and display name | v2 needs `assigned_to` to be a stable opaque ID, not a display string that changes |
| Hardcoding trust levels as strings without a validation table | `CHECK (trust_level IN ('low','standard','high'))` is fine; but if trust level semantics are ad-hoc per task, v2 RBAC cannot map roles to trust levels cleanly. Define trust level semantics now in `hive.agent_capabilities` taxonomy. |
| Milestone/project `owner` as free text | Same as `assigned_to` — make it a stable agent/actor ID from the registry, not a display name |
| No separation between "who claimed" and "who is allowed to claim" | `claim_task` sets `assigned_to` to the claimant. v2 needs to distinguish "current assignee" (actor) from "authorized actor pool" (policy). Keep `assigned_to` for current holder; put eligibility constraints in `required_capabilities`/`excluded_agents` (already in v1 design). |

---

## 7. Open Risks and Unknowns

1. **Heartbeat background job reliability.** A cron/asyncio task that runs every 5 min is a single point of failure. If it crashes, stale claims accumulate. Mitigation: emit a health check event; alert if no stale-claim sweep has run in 10 min.

2. **`child_task_ids` denormalization.** Do NOT add a `child_task_ids` array column. Compute children via `SELECT ... WHERE parent_task_id = $1` at gate time. Denormalized arrays and FKs can diverge; the query is cheap enough at current scale.

3. **Dual-review reconciliation semantics.** "Disagree" must be defined precisely. Define a verdict vocabulary (`approved`, `changes_requested`, `rejected`) and validate it at evidence submission time — not at gate evaluation time. Free-text verdicts will produce false reconciliation triggers.

4. **Idempotency key scope on re-claim.** If an agent crashes after claiming (idempotency key stored) and re-runs, it gets the original `claim_token` back from the cache — correct behavior. Ensure the heartbeat deadline is refreshed on idempotent re-claim (refresh `heartbeat_deadline` even on cache hit).

5. **`superseded` as terminal for G0.** A superseded review task should count as terminal for the G0 check. Confirm this is intentional: `status NOT IN ('done', 'superseded')` is the blocking predicate.

6. **`owner` field type ambiguity.** Both `hive.projects.owner` and `hive.milestones.owner` can be a person or agent identity. If v2 needs different RBAC policies for human vs. agent owners, a single text field is insufficient. Consider adding `owner_type text CHECK (owner_type IN ('human','agent'))` now.

7. **Evidence claim token gap.** Currently, evidence artifacts do not include `claim_token`. A stale agent could attach evidence to a task it no longer holds. Consider adding `claim_token` to evidence artifact submission and validating it matches the current holder.

8. **Source currency note.** All Temporal, Step Functions, GitHub Actions, and LangGraph documentation accessed 2026-03-06. Linear's auto-close changelog published 2024-09-06.

---

## 8. Appendix: Citations

| # | Title | URL | Date |
|---|---|---|---|
| 1 | Temporal Activities | https://docs.temporal.io/activities | 2026-03-06 (current) |
| 2 | Temporal Child Workflows | https://docs.temporal.io/child-workflows | 2026-03-06 (current) |
| 3 | Temporal Detecting Activity Failures | https://docs.temporal.io/encyclopedia/detecting-activity-failures | 2026-03-06 (current) |
| 4 | Temporal Heartbeat Bug Fix PR #771 | https://github.com/temporalio/temporal/pull/771 | Merged (historical) |
| 5 | AWS Step Functions — SendTaskHeartbeat API | https://docs.aws.amazon.com/step-functions/latest/apireference/API_SendTaskHeartbeat.html | 2026-03-06 (current) |
| 6 | AWS Step Functions — Activities | https://docs.aws.amazon.com/step-functions/latest/dg/concepts-activities.html | 2026-03-06 (current) |
| 7 | AWS Step Functions — Best Practices | https://docs.aws.amazon.com/step-functions/latest/dg/sfn-best-practices.html | 2026-03-06 (current) |
| 8 | Step Functions task token expires after 6.5h | https://repost.aws/questions/QU0z51xfDOToK2S3fNnIdHLw/step-functions-task-token-expires-after-6-5h | Community, 2026-03-06 |
| 9 | Jira: Prevent closing issues with open sub-tasks | https://support.atlassian.com/jira/kb/how-to-prevent-issues-from-being-closed-while-the-sub-tasks-are-still-open-in-jira/ | 2026-03-06 (current) |
| 10 | Jira: Automation condition — transition parent based on subtask approval | https://community.atlassian.com/forums/Jira-questions/Automation-condition-to-transition-parent-status-based-on/qaq-p/2495179 | Community, 2026-03-06 |
| 11 | Linear: Auto-close parent and sub-issues (GA) | https://linear.app/changelog/2024-09-06-auto-close-parent-and-sub-issues | Published 2024-09-06 |
| 12 | Linear: Parent and sub-issues docs | https://linear.app/docs/parent-and-sub-issues | 2026-03-06 (current) |
| 13 | GitHub Actions workflow syntax (`needs:`) | https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions | 2026-03-06 (current) |
| 14 | GitHub Actions: Required checks for conditional jobs | https://devopsdirective.com/posts/2025/08/github-actions-required-checks-for-conditional-jobs/ | Published 2025-08 |
| 15 | OpenAI Agents SDK | https://openai.github.io/openai-agents-python/ | 2026-03-06 (current) |
| 16 | OpenAI Swarm (experimental predecessor) | https://github.com/openai/swarm | Released Oct 2024 |
| 17 | CrewAI Agent concepts | https://docs.crewai.com/en/concepts/agents | 2026-03-06 (current) |
| 18 | CrewAI PR #2068: `allowed_agents` parameter | https://github.com/crewAIInc/crewAI/pull/2068 | Merged |
| 19 | LangGraph documentation | https://www.langchain.com/langgraph | GA announced May 2025 |
| 20 | LangGraph workflows and agents | https://docs.langchain.com/oss/python/langgraph/workflows-agents | 2026-03-06 (current) |
| 21 | Celery tasks documentation | https://docs.celeryq.dev/en/main/userguide/tasks.html | 2026-03-06 (Celery 5.6.2) |
| 22 | Celery visibility timeout optimization | https://medium.com/@bhagyarana80/optimizing-celery-retries-and-visibility-timeouts-at-high-scale-aa79f923d880 | 2026-03-06 |
| 23 | Argo Workflows — DAG | https://argo-workflows.readthedocs.io/en/latest/walk-through/dag/ | 2026-03-06 (current CNCF) |
| 24 | Argo Workflows — Enhanced Depends Logic | https://argo-workflows.readthedocs.io/en/latest/enhanced-depends-logic/ | 2026-03-06 (current) |
| 25 | Microsoft Azure: Event Sourcing pattern | https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing | 2026-03-06 (current) |
| 26 | microservices.io: Event Sourcing pattern | https://microservices.io/patterns/data/event-sourcing.html | Foundational (Chris Richardson) |
| 27 | Gunnar Morling: On Idempotency Keys | https://www.morling.dev/blog/on-idempotency-keys/ | 2026-03-06 |
| 28 | Idempotency keys HN discussion | https://news.ycombinator.com/item?id=46106411 | 2026-03-06 |
| 29 | FastAPI + Celery idempotent tasks | https://medium.com/@hjparmar1944/fastapi-celery-work-queues-idempotent-tasks-and-retries-that-dont-duplicate-d05e820c904b | Published Dec 2025 |
| 30 | Buildkite: Security controls | https://buildkite.com/docs/pipelines/best-practices/security-controls | 2026-03-06 (current) |
| 31 | Immutable audit log pipeline with OTel | https://oneuptime.com/blog/post/2026-02-06-immutable-audit-log-pipeline-otel/view | Published 2026-02-06 |

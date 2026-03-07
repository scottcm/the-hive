# V1 Design Validation Use Cases

Companion to `V1_DESIGN.md`. Each use case exercises one or more state machines
and cross-entity invariants end-to-end. A use case passes only if every
assertion holds. Section references point to `V1_DESIGN.md`.

---

## UC-01: Happy-path agent lifecycle

Covers: session state machine (7.1a), task state machine (7.4a), gate engine,
evidence, handoff.

### Preconditions

- Profile `scott.codex.worker` registered, active, trust=standard,
  capabilities include `python:strong`.
- Project P1 active, milestone M1 active under P1.
- Task T1 under M1: status=open, task_type=misc, required_capabilities=[python],
  min_trust_level=low, task_spec with acceptance_criteria, task contract set
  (allowed_paths, dependencies=[], review_policy={min_reviews:1,
  independent_required:true}).

### Steps

1. `start_agent_session(id='scott.codex.worker.01', profile_id='scott.codex.worker')`
   - Assert: session status=active, lease_expires_at set.
   - Assert: audit log entry `session_started`.

2. `get_next_task(agent_session_id='scott.codex.worker.01')`
   - Assert: T1 is returned (capability/trust filters pass).

3. `claim_task(task_id=T1, assigned_to='scott.codex.worker.01')`
   - Assert: T1 status=in_progress.
   - Assert: claim_token, claim_session_id, heartbeat_deadline all set.
   - Assert: claim_token returned in response.

4. `heartbeat_agent_session(id='scott.codex.worker.01')`
   - Assert: lease_expires_at extended.
   - Assert: heartbeat_deadline on T1 propagated to match new lease_expires_at.
   - Note: `heartbeat_task` is accepted but is a no-op in v1.0 (D1 deferral).

5. Record evidence: red_run, implementation_commit, green_run, review_output
   (reviewer != author profile), handoff_packet with required fields.
   - Assert: each artifact stored with actor_id='scott.codex.worker.01',
     immutable=true, SHA-256 hash.

6. `update_task(task_id=T1, status='done')`
   - Assert: G0-G5 all pass (G0 trivially — no children), gate events recorded.
   - Assert: T1 status=done, claim fields cleared.

7. `end_agent_session(id='scott.codex.worker.01')`
   - Assert: session status=inactive.
   - Assert: audit log entry `session_ended`.

### Postconditions

- T1 is done with full evidence chain.
- Session is inactive (terminal).
- All gate events and audit log entries exist.

---

## UC-02: Review with changes-requested cycle

Covers: review child task (7.6), review verdict lifecycle, G0_child_closure,
G4 profile-level self-review prevention, code review framing.

<!-- v1.1: expands to dual-review (judgment + coverage + reconciliation) — see V1.1_DEFERRED.md #D2 -->

### Preconditions

- Two profiles: `scott.codex.worker` (implementer), `scott.claude.reviewer`
  (reviewer). Different profile IDs.
- Task T-IMPL: task_type=implementation, status=open, task contract set.
- Task T-REV: task_type=review, parent_task_id=T-IMPL,
  task_spec contains review_ref='task/T-IMPL-branch'.

### Steps

1. Implementer session claims T-IMPL, completes implementation, records
   evidence (red_run, green_run, implementation_commit, handoff_packet).

2. Implementer attempts `update_task(T-IMPL, status='done')`.
   - Assert: **rejected** by G0_child_closure (T-REV not done).

3. Reviewer session (`scott.claude.reviewer.01`) claims T-REV.
   - Assert: G4 check passes (reviewer_profile_id != author_profile_id).

4. Implementer session (`scott.codex.worker.02`) attempts to claim T-REV.
   - Assert: **rejected** — same profile as implementer (G4 profile-level).

5. Reviewer performs code review, finds issues. Records review_output evidence
   with `verdict: "changes_requested"` and findings.
   - Assert: T-REV returns to status=open, claim fields cleared.

6. Implementer addresses findings on T-IMPL (still claimed, still in_progress).
   Pushes new commits to branch.

7. Reviewer (same or different reviewer profile) re-claims T-REV.
   - Assert: G4 re-evaluated on new claim.

8. Reviewer approves. Records review_output with `verdict: "approved"`.
   - Assert: T-REV moves to done.

9. Implementer retries `update_task(T-IMPL, status='done')`.
   - Assert: G0 passes (T-REV done). G1-G5 pass. T-IMPL done.

### Postconditions

- T-IMPL and T-REV both done.
- T-REV has two review_output evidence records (changes_requested + approved).
- No self-review occurred at profile level.

---

## UC-03: Stale-claim recovery and session expiry

Covers: session expiry (7.1a), stale-claim recovery (7.9), heartbeat_expired
gate event, task state machine claim release.

### Preconditions

- Session S1 active, claimed task T1 (in_progress) and task T2 (blocked,
  claimed — agent raised a clarification while working).
- S1.lease_expires_at is in the past (agent crashed, no heartbeats).

### Steps

1. Recovery job runs.
   - Assert: S1 status changes to expired.
   - Assert: T1 status=open, claim fields cleared (in_progress -> open).
   - Assert: T2 status=blocked, claim fields cleared (blocked-claimed ->
     blocked-unclaimed).
   - Assert: gate_event logged for T1 with gate_name='heartbeat_expired'.
   - Assert: gate_event logged for T2 with gate_name='heartbeat_expired'.
   - Assert: audit log entry `session_expired` for S1.

2. New session S2 starts for same profile.
   - Assert: S2 gets a new session ID (S1's ID cannot be reused).
   - Assert: S2 status=active.

3. S2 calls `get_next_task`.
   - Assert: T1 is visible (status=open).
   - Assert: T2 is not returned (status=blocked).

4. S2 claims T1.
   - Assert: T1 in_progress with S2's claim fields.

5. Someone answers T2's clarification.
   - Assert: T2 transitions to open (unclaimed, no claim to preserve).

### Postconditions

- S1 is expired (terminal), S2 is active.
- T1 is in_progress under S2.
- T2 is open and claimable.

---

## UC-04: Claim-aware clarification blocking

Covers: clarification state machine (7.7a), claim-aware blocking (7.4a),
multi-pending unblock.

### Preconditions

- Session S1 active, claimed task T1 (in_progress).

### Steps

1. S1 raises clarification C1 on T1.
   - Assert: C1 status=pending.
   - Assert: T1 status=blocked, claim fields **preserved** (S1 keeps claim).

2. S1 raises clarification C2 on T1.
   - Assert: C2 status=pending.
   - Assert: T1 status=blocked (no-op, already blocked).

3. Owner answers C1.
   - Assert: C1 status=answered.
   - Assert: T1 stays blocked (C2 still pending).

4. Owner answers C2.
   - Assert: C2 status=answered.
   - Assert: T1 returns to **in_progress** (not open — claim preserved).
   - Assert: claim_token, claim_session_id, heartbeat_deadline unchanged.

5. S1 continues work and completes T1.
   - Assert: T1 done, gates pass.

### Postconditions

- T1 done. Agent never had to re-claim after being blocked.
- C1, C2 both answered (terminal).

---

## UC-05: Clarification on unclaimed task

Covers: clarification creation on open task (7.7a), unclaimed blocking path.

### Preconditions

- Task T1 status=open, no claim.

### Steps

1. Manager creates clarification C1 on T1 (question about requirements).
   - Assert: T1 status=blocked, claim fields stay NULL.

2. `get_next_task` is called by an agent.
   - Assert: T1 is NOT returned (status=blocked).

3. Owner answers C1.
   - Assert: T1 returns to **open** (unclaimed, no claim to restore).

4. Agent claims T1.
   - Assert: T1 in_progress with claim fields set.

### Postconditions

- Normal claim flow resumed after clarification resolved.

---

## UC-06: Clarification rejected on terminal task

Covers: creation constraint in 7.7a.

### Steps

1. Task T1 status=done.
   - `create_clarification(task_id=T1, ...)` -> Assert: **rejected**.

2. Task T2 status=superseded.
   - `create_clarification(task_id=T2, ...)` -> Assert: **rejected**.

3. Task T3 status=blocked.
   - `create_clarification(task_id=T3, ...)` -> Assert: **succeeds**.

---

## UC-07: Capability and trust routing

Covers: capability-filtered selection (7.5), trust levels, gate_compliant.

### Preconditions

- Profile A: capabilities=[python:strong, review-judgment:strong],
  trust=standard, gate_compliant=true.
- Profile B: capabilities=[python:marginal], trust=low, gate_compliant=false.
- Task T1: required_capabilities=[python], min_trust_level=standard.
- Task T2: required_capabilities=[python], min_trust_level=low.
- Task T3: required_capabilities=[review-judgment], min_trust_level=standard.

### Steps

1. Session for Profile B calls `get_next_task`.
   - Assert: T1 NOT returned (trust too low).
   - Assert: T2 returned (trust=low, capability present even if marginal).
   - Assert: T3 NOT returned (missing review-judgment capability).

2. Session for Profile A calls `get_next_task`.
   - Assert: T1, T2, T3 all eligible.

3. Profile B session claims T1.
   - Assert: **rejected** at re-validation (trust too low).

4. Profile A session claims T1.
   - Assert: succeeds.

---

## UC-08: Execution policy workspace safety

Covers: execution policy (7.8), branch name safety, claim-time enforcement.

### Preconditions

- Task T1 execution_policy:
  `{workspace_mode: "dedicated_worktree", branch_mode: "per_task_branch",
  branch_name_template: "task/{task_id}-{agent_session_id}",
  allow_shared_clone: false, require_clean_worktree_on_claim: true}`.
- Session S1 with valid ID format and `worktree_path='/workspaces/agent-s1'`.

### Steps

1. S1 claims T1.
   - Assert: branch name constructed as `task/<T1_id>-<S1_id>`.
   - Assert: interpolated values pass `^[a-zA-Z0-9._-]+$` validation.
   - Assert: claim succeeds, execution_policy attached to task.

2. Session S2 (same profile, different session) attempts to claim T1.
   - Assert: **rejected** (T1 already claimed).

3. S1 completes T1. Another task T2 has same execution_policy.
   S1 claims T2.
   - Assert: different branch name `task/<T2_id>-<S1_id>`.
   - Assert: no branch collision.

---

## UC-08a: Worktree path conflict detection

Covers: worktree_path uniqueness (7.8, 8.2), session isolation, claim-time
worktree_path validation.

### Preconditions

- Task T1 with `allow_shared_clone: false`.
- Task T2 with `allow_shared_clone: false`.

### Steps

1. `start_agent_session(id='s1', profile_id='worker-a',
   worktree_path='/workspaces/agent-s1')`
   - Assert: succeeds, session S1 active with worktree_path recorded.

2. `start_agent_session(id='s2', profile_id='worker-b',
   worktree_path='/workspaces/agent-s2')`
   - Assert: succeeds, session S2 active with different worktree_path.

3. `start_agent_session(id='s3', profile_id='worker-c',
   worktree_path='/workspaces/agent-s1')`
   - Assert: **rejected** (worktree_path conflicts with active session S1).

4. S1 claims T1.
   - Assert: succeeds (S1 has non-null worktree_path, allow_shared_clone
     satisfied).

5. `start_agent_session(id='s4', profile_id='worker-d',
   worktree_path=NULL)`
   - Assert: succeeds (NULL worktree_path is allowed for manager sessions).

6. S4 attempts to claim T2.
   - Assert: **rejected** (T2 has `allow_shared_clone: false` but S4 has
     no worktree_path).

7. `end_agent_session(id='s1')` — S1 becomes inactive.

8. `start_agent_session(id='s5', profile_id='worker-e',
   worktree_path='/workspaces/agent-s1')`
   - Assert: succeeds (S1 is no longer active, path is available).

---

## UC-09: Profile deactivation cascade

Covers: profile deactivation (7.1a), session expiry cascade, task release.

### Preconditions

- Profile P1 active with two active sessions: S1 (claimed T1, in_progress),
  S2 (claimed T2, blocked with clarification).

### Steps

1. `update_agent_profile(id=P1, active=false)`
   - Assert: S1 status=expired, S2 status=expired.
   - Assert: T1 status=open, claim fields cleared.
   - Assert: T2 status=blocked (unclaimed), claim fields cleared.
   - Assert: audit log entries: `session_expired` for S1, `session_expired` for S2.

2. Attempt `start_agent_session(profile_id=P1)`.
   - Assert: **rejected** (profile is inactive).

3. `update_agent_profile(id=P1, active=true)`.
   - Assert: P1 is active again.
   - Assert: S1 and S2 remain expired (terminal). New sessions required.

4. `start_agent_session(id='P1.new.01', profile_id=P1)`.
   - Assert: new session active.

---

## UC-10: Project and milestone lifecycle

Covers: project state machine (7.3a), milestone state machine (7.3b),
task-completion preconditions.

### Preconditions

- Project P1 active.
- Milestone M1 active under P1 with tasks T1 (done), T2 (open).

### Steps

1. `update_milestone(M1, status='done')`
   - Assert: **rejected** (T2 is open).

2. `update_project(P1, status='archived')`
   - Assert: **rejected** (M1 is active).

3. Supersede T2: `supersede_task(T2, replacement_task_id=T3, ...)`.
   - Assert: T2 status=superseded.

4. `update_milestone(M1, status='done')`
   - Assert: succeeds (T1=done, T2=superseded).

5. `update_project(P1, status='archived')`
   - Assert: succeeds (M1=done).

6. `update_project(P1, status='active')` — reactivate.
   - Assert: P1 active. M1 still done.

7. `update_milestone(M1, status='active')` — reopen milestone.
   - Assert: M1 active. New tasks can be created under it.

---

## UC-11: Milestone archived cannot transition to done

Covers: milestone invalid transition (7.3b).

### Preconditions

- Milestone M1 active, all tasks done.

### Steps

1. `update_milestone(M1, status='archived')` -> Assert: succeeds.
2. `update_milestone(M1, status='done')` -> Assert: **rejected** (archived -> done invalid).
3. `update_milestone(M1, status='active')` -> Assert: succeeds.
4. `update_milestone(M1, status='done')` -> Assert: succeeds (active -> done valid).

---

## UC-12: Task supersession workflow

Covers: supersede_task, reopen_task, status canonicalization (8.11).

### Preconditions

- Task T1 status=open.
- Task T2 status=in_progress (claimed by session S1).

### Steps

1. Create replacement task T3 (open).

2. `supersede_task(T1, replacement_task_id=T3, ...)`
   - Assert: T1 status=superseded, claim fields NULL.

3. `supersede_task(T2, replacement_task_id=T3, ...)`
   - Assert: T2 status=superseded, claim fields **cleared**.

4. `update_task(T1, status='done')` -> Assert: **rejected** (superseded -> done invalid).

5. `reopen_task(T1, ...)` -> Assert: T1 status=open, claim fields NULL.

6. `reopen_task(T2, ...)` -> Assert: T2 status=open, claim fields NULL.

---

## UC-13: Invalid task transitions

Covers: task state machine invalid paths (7.4a).

### Steps

1. Task T1 status=open.
   - `update_task(T1, status='done')` -> Assert: **rejected** (open -> done).

2. Task T2 status=done.
   - `update_task(T2, status='in_progress')` -> Assert: **rejected**.
   - `update_task(T2, status='blocked')` -> Assert: **rejected**.
   - Must `reopen_task(T2)` first, then claim.

3. Task T3 status=superseded.
   - `update_task(T3, status='done')` -> Assert: **rejected**.
   - `update_task(T3, status='in_progress')` -> Assert: **rejected**.
   - `update_task(T3, status='blocked')` -> Assert: **rejected**.

---

## UC-14: Session end with active claims

Covers: graceful shutdown auto-release (7.1a).

### Preconditions

- Session S1 active.
- T1 in_progress claimed by S1.
- T2 blocked (claimed) by S1.

### Steps

1. `end_agent_session(S1)`
   - Assert: S1 status=inactive.
   - Assert: T1 status=open, claim fields cleared.
   - Assert: T2 status=blocked, claim fields cleared (blocked-unclaimed).
   - Assert: audit log `session_ended`.

2. `heartbeat_agent_session(S1)` -> Assert: **rejected** (inactive).

3. `claim_task(T1, session=S1)` -> Assert: **rejected** (session inactive).

4. New session S2 claims T1 -> Assert: succeeds.

---

## UC-15: Idempotent operations

Covers: idempotency keys (8.8).

### Steps

1. `create_task(title='T1', idempotency_key='key-abc')` -> returns task T1.

2. `create_task(title='T1', idempotency_key='key-abc')` (replay).
   - Assert: returns same T1 (no duplicate created).

3. `claim_task(task_id=T1, ..., idempotency_key='claim-xyz')` -> returns claim.

4. `claim_task(task_id=T1, ..., idempotency_key='claim-xyz')` (replay).
   - Assert: returns same claim result (no error, no double-claim).

---

## UC-16: Review task requires review_ref

Covers: review_ref validation (7.6), T33.

### Steps

1. `create_task(task_type='review', parent_task_id=T-IMPL,
   task_spec={})`
   - Assert: **rejected** (task_spec missing review_ref).

2. `create_task(task_type='review', parent_task_id=T-IMPL,
   task_spec={review_ref: ''})`
   - Assert: **rejected** (review_ref empty).

3. `create_task(task_type='review', parent_task_id=T-IMPL,
   task_spec={review_ref: 'task/42-scott.codex.worker.01'})`
   - Assert: succeeds.

4. `create_task(task_type='implementation', task_spec={})`
   - Assert: succeeds (review_ref not required for non-review types).

---

## UC-17: Parent-child depth enforcement

Covers: single-level nesting (7.4), self-reference prevention (8.6).

### Preconditions

- Task T-IMPL (implementation, parent_task_id=NULL).
- Task T-RJ (review, parent_task_id=T-IMPL).

### Steps

1. `create_task(task_type='misc', parent_task_id=T-RJ)`
   - Assert: **rejected** (T-RJ already has a parent — no grandchildren).

2. `create_task(task_type='misc', parent_task_id=T-IMPL)`
   - Assert: succeeds (T-IMPL has no parent).

---

## UC-18: Routing field write restrictions

Covers: routing field policy (7.4), created_by ownership.

### Preconditions

- Task T1 created by actor 'manager-01', preferred_agent='scott.codex.worker',
  excluded_agents=['scott.gemini.scout'].

### Steps

1. Actor 'worker-01' calls `update_task(T1, preferred_agent='worker-01')`.
   - Assert: **rejected** (actor is not T1's creator or project/milestone owner).

2. Actor 'manager-01' calls `update_task(T1, preferred_agent='scott.gemini.scout')`.
   - Assert: succeeds (actor matches created_by).

3. Actor 'worker-01' calls `update_task(T1, title='new title')`.
   - Assert: succeeds (title is not a routing field — no restriction).

---

## UC-19: Evidence requires active claim and session

Covers: evidence claim/session binding (9, modified tools).

### Preconditions

- Session S1 active, claimed task T1 with claim_token CT1.
- Session S2 active (different agent).

### Steps

1. `record_task_evidence(task_id=T1, session=S1, claim_token=CT1,
   artifact_type='green_run', ...)`
   - Assert: succeeds.

2. `record_task_evidence(task_id=T1, session=S2, claim_token=CT1, ...)`
   - Assert: **rejected** (session doesn't match claim_session_id).

3. `record_task_evidence(task_id=T1, session=S1, claim_token='wrong-token', ...)`
   - Assert: **rejected** (wrong claim_token).

4. End session S1. Then attempt evidence write.
   - Assert: **rejected** (session inactive).

---

## UC-20: Clarification routing chain

Covers: clarification routing (7.7), escalation.

### Preconditions

- Project P1 owner='project-lead'.
- Milestone M1 under P1 owner='domain-expert', domain='api'.
- Task T1 under M1, claimed by session S1.

### Steps

1. S1 creates clarification C1 on T1.
   - Assert: C1.routed_to = 'domain-expert' (milestone owner first).

2. `list_clarifications(routed_to='domain-expert')`
   - Assert: C1 appears.

3. Clarification C1 remains unanswered, escalation triggers.
   - Assert: C1.routed_to updated to 'project-lead' (project owner).

4. Still unanswered, escalation triggers again.
   - Assert: C1.routed_to updated to human-required queue.

---

## UC-21: JSONB payload size limits

Covers: size constraints (8.4, 8.5, 8.6).

### Steps

1. `create_task(task_spec=<65KB+ JSON>)` -> Assert: **rejected** (exceeds 64KB).
2. `create_task(execution_policy=<17KB JSON>)` -> Assert: **rejected** (exceeds 16KB).
3. `create_project(project_spec=<65KB+ JSON>)` -> Assert: **rejected**.
4. `create_task(task_spec=<small valid JSON>)` -> Assert: succeeds.

---

## UC-22: Actor identity unification

Covers: actor_id column rename (8.9), actor tracking.

### Steps

1. After migration, insert gate event with `actor_id='scott.codex.worker.01'`.
   - Assert: stored successfully.

2. Insert override with `actor_id='manager-01'`.
   - Assert: stored successfully.

3. Insert evidence artifact with `actor_id='scott.codex.worker.01'`.
   - Assert: stored successfully.

4. Query using old column names (`actor`, `approved_by`, `captured_by`).
   - Assert: **fails** (columns renamed).

---

## UC-23: Concurrent sessions from same profile

Covers: session concurrency (7.1a, 7.5), workspace isolation (7.8).

### Preconditions

- Profile P1 active.
- Two tasks T1, T2 both open, both eligible for P1.

### Steps

1. `start_agent_session(id='P1.01', profile_id='P1')` -> active.
2. `start_agent_session(id='P1.02', profile_id='P1')` -> active.

3. P1.01 claims T1 -> succeeds.
4. P1.02 claims T2 -> succeeds.

5. P1.01 and P1.02 get different branch names from execution_policy template.
   - Assert: no branch collision.

6. Both complete their tasks independently.
   - Assert: both T1 and T2 done.

---

## UC-24: Gate override with expiry

Covers: override system, expire_override, gate re-evaluation.

### Preconditions

- Task T1 in_progress, contract set, G3 (verification) would fail (missing
  green_run evidence).

### Steps

1. `update_task(T1, status='done')` -> Assert: **rejected** (G3 fails).

2. `create_task_override(task_id=T1, gate_name='G3_verification',
   scope='missing test infra', actor_id='manager-01',
   reason='test framework not ready', expires_at=<future>)`
   - Assert: override created.

3. `update_task(T1, status='done')` -> Assert: succeeds (G3 overridden).

4. Create task T2 with similar setup. Create same override but with
   expires_at=<past>.
   - `update_task(T2, status='done')` -> Assert: **rejected** (override expired).

---

## UC-25: Full project lifecycle end-to-end

Covers: all state machines in sequence — project, milestone, task, session,
clarification, review.

<!-- v1.1: expands to dual-review (judgment + coverage + reconciliation) — see V1.1_DEFERRED.md #D2 -->

### Steps

1. Create project P1 (active) with project_spec and execution_policy.
2. Create milestone M1 (active) under P1 with domain and owner.
3. Create implementation task T1 under M1 with task_spec.
4. Create review task T-REV as child of T1 with review_ref.

5. Worker session starts, claims T1, implements, records evidence.
6. Worker raises clarification -> T1 blocked (claimed).
7. Owner answers -> T1 resumes to in_progress.
8. Worker finishes implementation.

9. Worker attempts done -> rejected by G0 (T-REV not done).

10. Reviewer session claims T-REV, reviews, requests changes -> T-REV returns to open.
11. Worker fixes, reviewer re-claims T-REV, approves -> T-REV done.

12. Worker retries done on T1 -> G0 passes, G1-G5 pass, T1 done.
13. Worker executes completion actions (push, PR creation per execution_policy).
14. Worker session ends.

15. `update_milestone(M1, status='done')` -> succeeds (all tasks done/superseded).
16. `update_project(P1, status='archived')` -> succeeds (M1 done).

### Postconditions

- All entities in terminal states.
- Full audit trail: gate events, evidence artifacts, clarifications, audit log.
- No orphaned claims, no zombie sessions.

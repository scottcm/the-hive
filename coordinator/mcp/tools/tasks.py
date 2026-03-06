import fnmatch
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

TASK_STATUSES = {"open", "in_progress", "blocked", "done", "cancelled", "superseded"}
SUMMARY_SELECT = """
    SELECT
        t.id,
        t.milestone_id,
        t.title,
        t.description,
        t.status,
        t.assigned_to,
        t.github_issues,
        t.tags,
        t.relevant_docs,
        t.sequence_order,
        t.depends_on,
        t.created_at,
        t.updated_at,
        m.name AS milestone_name,
        m.description AS milestone_description
    FROM hive.tasks t
    LEFT JOIN hive.milestones m ON m.id = t.milestone_id
"""

DEPS_MET_CONDITION = """
    NOT EXISTS (
        SELECT 1 FROM unnest(t.depends_on) AS dep_id
        JOIN hive.tasks dt ON dt.id = dep_id
        WHERE dt.status NOT IN ('done', 'cancelled')
    )
"""

DONE_GATE_SEQUENCE = (
    "G1_scope_lock",
    "G2_tdd_order",
    "G3_verification",
    "G4_review_separation",
    "G5_handoff_completeness",
)

OVERRIDABLE_GATES = {
    "G1_scope_lock",
    "G2_tdd_order",
    "G3_verification",
    "G4_review_separation",
    "G5_handoff_completeness",
    "G_start_dependencies",
}


def _validate_path_list(
    field_name: str,
    paths: list[Any],
    *,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(paths, list):
        raise ValueError(f"Task contract {field_name} must be a list of strings")
    if not allow_empty and len(paths) == 0:
        raise ValueError(f"Task contract {field_name} must not be empty")
    normalized: list[str] = []
    for path in paths:
        if not isinstance(path, str) or path.strip() == "":
            raise ValueError(
                f"Task contract {field_name} must contain non-empty strings"
            )
        normalized.append(path.strip())
    return normalized


def _validate_int_list(
    field_name: str,
    values: list[Any],
) -> list[int]:
    if not isinstance(values, list):
        raise ValueError(f"Task contract {field_name} must be a list of integers")
    normalized: list[int] = []
    for value in values:
        if not isinstance(value, int):
            raise ValueError(f"Task contract {field_name} must contain integers")
        normalized.append(value)
    return normalized


def _validate_required_tests(required_tests: Any) -> dict[str, list[str]]:
    if not isinstance(required_tests, dict):
        raise ValueError("Task contract required_tests must be an object")
    red_raw = required_tests.get("red")
    green_raw = required_tests.get("green")
    red = _validate_path_list("required_tests.red", red_raw, allow_empty=False)
    green = _validate_path_list(
        "required_tests.green",
        green_raw,
        allow_empty=False,
    )
    return {"red": red, "green": green}


def _validate_review_policy(review_policy: Any) -> dict[str, Any]:
    if not isinstance(review_policy, dict):
        raise ValueError("Task contract review_policy must be an object")

    min_reviews = review_policy.get("min_reviews")
    independent_required = review_policy.get("independent_required")

    if not isinstance(min_reviews, int) or min_reviews < 1:
        raise ValueError("Task contract review_policy.min_reviews must be >= 1")
    if not isinstance(independent_required, bool):
        raise ValueError(
            "Task contract review_policy.independent_required must be boolean"
        )
    return {
        "min_reviews": min_reviews,
        "independent_required": independent_required,
    }


def _normalize_task_contract_payload(
    *,
    allowed_paths: list[Any],
    forbidden_paths: list[Any],
    dependencies: list[Any],
    required_tests: Any,
    review_policy: Any,
    handoff_template: str,
    contract_version: int,
) -> dict[str, Any]:
    if not isinstance(contract_version, int) or contract_version < 1:
        raise ValueError("Task contract contract_version must be >= 1")
    if not isinstance(handoff_template, str) or handoff_template.strip() == "":
        raise ValueError("Task contract handoff_template must be a non-empty string")

    return {
        "contract_version": contract_version,
        "allowed_paths": _validate_path_list(
            "allowed_paths",
            allowed_paths,
            allow_empty=False,
        ),
        "forbidden_paths": _validate_path_list(
            "forbidden_paths",
            forbidden_paths,
            allow_empty=True,
        ),
        "dependencies": _validate_int_list("dependencies", dependencies),
        "required_tests": _validate_required_tests(required_tests),
        "review_policy": _validate_review_policy(review_policy),
        "handoff_template": handoff_template.strip(),
    }


def _serialize_task_contract(row: dict[str, Any]) -> dict[str, Any]:
    required_tests = row["required_tests"]
    review_policy = row["review_policy"]

    if isinstance(required_tests, str):
        required_tests = json.loads(required_tests)
    if isinstance(review_policy, str):
        review_policy = json.loads(review_policy)

    normalized = _normalize_task_contract_payload(
        allowed_paths=row["allowed_paths"],
        forbidden_paths=row["forbidden_paths"],
        dependencies=row["dependencies"],
        required_tests=required_tests,
        review_policy=review_policy,
        handoff_template=row["handoff_template"],
        contract_version=row["contract_version"],
    )
    return {
        "task_id": row["task_id"],
        **normalized,
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def _fetch_task_contract(
    task_id: int,
    conn: Any,
) -> dict[str, Any] | None:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        """
        SELECT
            task_id,
            contract_version,
            allowed_paths,
            forbidden_paths,
            dependencies,
            required_tests,
            review_policy,
            handoff_template,
            created_at,
            updated_at
        FROM hive.task_contracts
        WHERE task_id = %s
        """,
        (task_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _serialize_task_contract(row)


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        return {}
    return value


async def _fetch_task_evidence(task_id: int, conn: Any) -> dict[str, list[dict[str, Any]]]:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        """
        SELECT artifact_type, captured_at, metadata
        FROM hive.task_evidence_artifacts
        WHERE task_id = %s
        ORDER BY captured_at, id
        """,
        (task_id,),
    )
    rows = await cursor.fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["artifact_type"], []).append(
            {
                "captured_at": row["captured_at"],
                "metadata": _normalize_metadata(row["metadata"]),
            }
        )
    return grouped


async def _fetch_active_task_overrides(
    task_id: int,
    conn: Any,
) -> dict[str, dict[str, Any]]:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        """
        SELECT
            gate_name,
            approved_by,
            reason,
            expires_at,
            created_at
        FROM hive.task_overrides
        WHERE task_id = %s AND expires_at > now()
        ORDER BY created_at DESC, id DESC
        """,
        (task_id,),
    )
    overrides: dict[str, dict[str, Any]] = {}
    for row in await cursor.fetchall():
        if row["gate_name"] not in OVERRIDABLE_GATES:
            continue
        if row["gate_name"] not in overrides:
            overrides[row["gate_name"]] = row
    return overrides


def _apply_gate_overrides(
    gate_results: list[tuple[str, str, str]],
    overrides: dict[str, dict[str, Any]],
) -> list[tuple[str, str, str]]:
    evaluated: list[tuple[str, str, str]] = []
    for gate_name, decision, reason in gate_results:
        if decision == "fail" and gate_name in overrides:
            override = overrides[gate_name]
            evaluated.append(
                (
                    gate_name,
                    "override",
                    f"{reason} (override by {override['approved_by']}: {override['reason']})",
                )
            )
            continue
        evaluated.append((gate_name, decision, reason))
    return evaluated


def _evaluate_scope_lock_gate(
    contract: dict[str, Any],
    evidence: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    implementation_rows = evidence.get("implementation_commit", [])
    if not implementation_rows:
        return ("fail", "No implementation_commit evidence artifact found")

    changed_files: list[str] = []
    for row in implementation_rows:
        values = row["metadata"].get("changed_files")
        if isinstance(values, list):
            changed_files.extend(
                path.strip().replace("\\", "/")
                for path in values
                if isinstance(path, str) and path.strip() != ""
            )
    if not changed_files:
        return ("fail", "No changed_files metadata recorded for implementation commits")

    allowed_paths: list[str] = contract["allowed_paths"]
    forbidden_paths: list[str] = contract["forbidden_paths"]

    for path in changed_files:
        if any(fnmatch.fnmatch(path, pattern) for pattern in forbidden_paths):
            return ("fail", f"Out-of-scope forbidden path detected: {path}")
        if not any(fnmatch.fnmatch(path, pattern) for pattern in allowed_paths):
            return ("fail", f"Path not in allowed scope: {path}")
    return ("pass", "All implementation changed files are within contract scope")


def _evaluate_tdd_order_gate(
    evidence: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    red_rows = evidence.get("red_run", [])
    implementation_rows = evidence.get("implementation_commit", [])
    if not red_rows:
        return ("fail", "No red_run evidence artifact found")
    if not implementation_rows:
        return ("fail", "No implementation_commit evidence artifact found")

    has_failing_tests = any(
        isinstance(row["metadata"].get("failing_tests"), list)
        and len(row["metadata"]["failing_tests"]) > 0
        for row in red_rows
    )
    if not has_failing_tests:
        return ("fail", "RED evidence is missing failing_tests identifiers")

    first_red = red_rows[0]["captured_at"]
    first_implementation = implementation_rows[0]["captured_at"]
    if first_red >= first_implementation:
        return ("fail", "RED evidence must be captured before first implementation commit")
    return ("pass", "RED evidence precedes implementation and includes failing tests")


def _evaluate_verification_gate(
    contract: dict[str, Any],
    evidence: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    green_rows = evidence.get("green_run", [])
    if not green_rows:
        return ("fail", "No green_run evidence artifact found")

    passed_commands = {
        row["metadata"].get("command")
        for row in green_rows
        if isinstance(row["metadata"].get("command"), str)
        and row["metadata"].get("passed", True) is True
    }
    required_commands = contract["required_tests"]["green"]
    missing = [command for command in required_commands if command not in passed_commands]
    if missing:
        return (
            "fail",
            "Missing successful green_run evidence for commands: "
            + ", ".join(missing),
        )
    return ("pass", "Required verification commands have passing evidence")


def _evaluate_review_gate(
    contract: dict[str, Any],
    evidence: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    review_rows = evidence.get("review_output", [])
    if not review_rows:
        return ("fail", "No review_output evidence artifact found")

    policy = contract["review_policy"]
    min_reviews = policy["min_reviews"]
    independent_required = policy["independent_required"]

    parsed_reviews: list[tuple[str, str]] = []
    for row in review_rows:
        reviewer = row["metadata"].get("reviewer")
        author = row["metadata"].get("author")
        if isinstance(reviewer, str) and reviewer.strip() != "" and isinstance(
            author, str
        ) and author.strip() != "":
            parsed_reviews.append((reviewer.strip(), author.strip()))

    if len(parsed_reviews) < min_reviews:
        return (
            "fail",
            f"Review evidence count {len(parsed_reviews)} is below required {min_reviews}",
        )

    if independent_required:
        independent_reviews = [
            (reviewer, author)
            for reviewer, author in parsed_reviews
            if reviewer != author
        ]
        if len(independent_reviews) < 1:
            return (
                "fail",
                "Independent review requirement failed: reviewer must differ from author",
            )
    return ("pass", "Review policy requirements satisfied")


_HANDOFF_STR_FIELDS = ("what_changed", "why_changed")
_HANDOFF_LIST_FIELDS = ("residual_risks", "unresolved_questions", "verification_links", "next_actions")


def _evaluate_handoff_gate(
    evidence: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    handoff_rows = evidence.get("handoff_packet", [])
    if not handoff_rows:
        return ("fail", "No handoff_packet evidence artifact found")

    metadata = handoff_rows[-1]["metadata"]
    required_fields = _HANDOFF_STR_FIELDS + _HANDOFF_LIST_FIELDS
    missing = [field for field in required_fields if field not in metadata]
    if missing:
        return ("fail", "Handoff packet missing fields: " + ", ".join(missing))

    type_errors = []
    for field in _HANDOFF_STR_FIELDS:
        if not isinstance(metadata[field], str):
            type_errors.append(f"{field} must be a string")
    for field in _HANDOFF_LIST_FIELDS:
        if not isinstance(metadata[field], list):
            type_errors.append(f"{field} must be a list")
    if type_errors:
        return ("fail", "Handoff packet type errors: " + "; ".join(type_errors))

    links = metadata["verification_links"]
    if not links:
        return ("fail", "Handoff packet verification_links must contain at least one entry")
    invalid_links = [i for i, v in enumerate(links) if not isinstance(v, str) or not v.strip()]
    if invalid_links:
        return ("fail", f"Handoff packet verification_links has invalid entries at positions: {invalid_links}")

    return ("pass", "Handoff packet contains required fields")


async def _evaluate_done_gates(
    task_id: int,
    conn: Any,
) -> list[tuple[str, str, str]]:
    contract = await _fetch_task_contract(task_id, conn)
    if contract is None:
        return [
            (gate_name, "fail", "Task is missing required task contract")
            for gate_name in DONE_GATE_SEQUENCE
        ]

    evidence = await _fetch_task_evidence(task_id, conn)
    evaluations = (
        ("G1_scope_lock", _evaluate_scope_lock_gate(contract, evidence)),
        ("G2_tdd_order", _evaluate_tdd_order_gate(evidence)),
        ("G3_verification", _evaluate_verification_gate(contract, evidence)),
        ("G4_review_separation", _evaluate_review_gate(contract, evidence)),
        ("G5_handoff_completeness", _evaluate_handoff_gate(evidence)),
    )
    return [(name, decision, reason) for name, (decision, reason) in evaluations]


async def _record_gate_event(
    *,
    task_id: int,
    gate_name: str,
    decision: str,
    reason: str,
    actor: str,
    conn: Any,
) -> None:
    cursor = conn.cursor()
    await cursor.execute(
        """
        INSERT INTO hive.task_gate_events (
            task_id,
            gate_name,
            decision,
            reason,
            actor
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (task_id, gate_name, decision, reason, actor),
    )


async def _assert_task_can_start(
    task_id: int,
    conn: Any,
) -> None:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        """
        SELECT depends_on
        FROM hive.tasks
        WHERE id = %s
        """,
        (task_id,),
    )
    task_row = await cursor.fetchone()
    if task_row is None:
        raise ValueError(f"Task {task_id} not found")

    contract = await _fetch_task_contract(task_id, conn)
    if contract is None:
        raise ValueError(f"Task {task_id} is missing required task contract")

    depends_on = task_row["depends_on"] or []
    if sorted(contract["dependencies"]) != sorted(depends_on):
        raise ValueError(
            f"Task {task_id} contract dependencies do not match task depends_on"
        )

    await cursor.execute(
        """
        SELECT dt.id, dt.status
        FROM hive.tasks t
        CROSS JOIN LATERAL unnest(t.depends_on) AS dep_id
        JOIN hive.tasks dt ON dt.id = dep_id
        WHERE t.id = %s AND dt.status NOT IN ('done', 'cancelled')
        """,
        (task_id,),
    )
    unmet = await cursor.fetchall()
    if not unmet:
        return

    overrides = await _fetch_active_task_overrides(task_id, conn)
    if "G_start_dependencies" in overrides:
        return

    blockers = ", ".join(f"#{r['id']} ({r['status']})" for r in unmet)
    raise ValueError(
        f"Task {task_id} has unmet dependencies: {blockers}"
    )


def _serialize_summary_task(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "assigned_to": row["assigned_to"],
        "milestone_id": row["milestone_id"],
        "milestone_name": row["milestone_name"],
        "milestone_description": row["milestone_description"],
        "github_issues": row["github_issues"],
        "tags": row["tags"],
        "relevant_docs": row["relevant_docs"],
        "sequence_order": row["sequence_order"],
        "depends_on": row["depends_on"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _serialize_note(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "author": row["author"],
        "content": row["content"],
        "created_at": row["created_at"].isoformat(),
    }


async def _fetch_task_summary(task_id: int, conn: Any) -> dict[str, Any]:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        f"""
        {SUMMARY_SELECT}
        WHERE t.id = %s
        """,
        (task_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Task {task_id} not found")
    return _serialize_summary_task(row)


async def _fetch_task_full(task_id: int, conn: Any) -> dict[str, Any]:
    task = await _fetch_task_summary(task_id, conn)

    notes_cursor = conn.cursor(row_factory=dict_row)
    await notes_cursor.execute(
        """
        SELECT id, author, content, created_at
        FROM hive.task_notes
        WHERE task_id = %s
        ORDER BY created_at, id
        """,
        (task_id,),
    )
    task["notes"] = [_serialize_note(row) for row in await notes_cursor.fetchall()]

    clarifications_cursor = conn.cursor(row_factory=dict_row)
    await clarifications_cursor.execute(
        """
        SELECT id, asked_by, question, answer, status, created_at, answered_at
        FROM hive.clarifications
        WHERE task_id = %s
        ORDER BY created_at, id
        """,
        (task_id,),
    )
    all_clarifications = await clarifications_cursor.fetchall()
    task["pending_clarifications"] = [
        {"id": row["id"], "question": row["question"], "status": row["status"]}
        for row in all_clarifications
        if row["status"] == "pending"
    ]
    task["clarifications"] = [
        {
            "id": row["id"],
            "asked_by": row["asked_by"],
            "question": row["question"],
            "answer": row["answer"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "answered_at": row["answered_at"].isoformat() if row["answered_at"] else None,
        }
        for row in all_clarifications
    ]

    dep_ids = task.get("depends_on") or []
    if dep_ids:
        blocked_by_cursor = conn.cursor(row_factory=dict_row)
        await blocked_by_cursor.execute(
            """
            SELECT id, title, status
            FROM hive.tasks
            WHERE id = ANY(%s) AND status NOT IN ('done', 'cancelled')
            """,
            (dep_ids,),
        )
        task["blocked_by"] = [dict(row) for row in await blocked_by_cursor.fetchall()]
    else:
        task["blocked_by"] = []

    blocks_cursor = conn.cursor(row_factory=dict_row)
    await blocks_cursor.execute(
        """
        SELECT id, title, status
        FROM hive.tasks
        WHERE %s = ANY(depends_on)
        """,
        (task_id,),
    )
    task["blocks"] = [dict(row) for row in await blocks_cursor.fetchall()]

    return task


def _validate_task_status(status: str) -> None:
    if status not in TASK_STATUSES:
        raise ValueError(f"Invalid status: {status}")


async def get_task(task_id: int) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        return await _fetch_task_full(task_id, conn)


async def get_task_contract(task_id: int) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        contract = await _fetch_task_contract(task_id, conn)
        if contract is None:
            raise ValueError(f"Task {task_id} contract not found")
        return contract


async def create_task_override(
    task_id: int,
    gate_name: str,
    approved_by: str,
    reason: str,
    expires_at: str,
    scope: str = "status_transition",
) -> dict[str, Any]:
    if gate_name not in OVERRIDABLE_GATES:
        raise ValueError(f"Invalid gate_name for override: {gate_name}")
    if not isinstance(approved_by, str) or approved_by.strip() == "":
        raise ValueError("approved_by must be a non-empty string")
    if not isinstance(reason, str) or reason.strip() == "":
        raise ValueError("reason must be a non-empty string")
    if not isinstance(scope, str) or scope.strip() == "":
        raise ValueError("scope must be a non-empty string")
    if not isinstance(expires_at, str) or expires_at.strip() == "":
        raise ValueError("expires_at must be an ISO-8601 timestamp string")

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT id FROM hive.tasks WHERE id = %s",
                (task_id,),
            )
            if await cursor.fetchone() is None:
                raise ValueError(f"Task {task_id} not found")

            await cursor.execute(
                """
                INSERT INTO hive.task_overrides (
                    task_id,
                    gate_name,
                    scope,
                    approved_by,
                    reason,
                    expires_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::timestamptz)
                RETURNING
                    id,
                    task_id,
                    gate_name,
                    scope,
                    approved_by,
                    reason,
                    expires_at,
                    created_at
                """,
                (
                    task_id,
                    gate_name,
                    scope.strip(),
                    approved_by.strip(),
                    reason.strip(),
                    expires_at.strip(),
                ),
            )
            row = await cursor.fetchone()
            assert row is not None
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "gate_name": row["gate_name"],
                "scope": row["scope"],
                "approved_by": row["approved_by"],
                "reason": row["reason"],
                "expires_at": row["expires_at"].isoformat(),
                "created_at": row["created_at"].isoformat(),
            }


async def list_task_overrides(
    task_id: int,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        if active_only:
            await cursor.execute(
                """
                SELECT
                    id,
                    task_id,
                    gate_name,
                    scope,
                    approved_by,
                    reason,
                    expires_at,
                    created_at
                FROM hive.task_overrides
                WHERE task_id = %s
                  AND expires_at > now()
                ORDER BY created_at DESC, id DESC
                """,
                (task_id,),
            )
        else:
            await cursor.execute(
                """
                SELECT
                    id,
                    task_id,
                    gate_name,
                    scope,
                    approved_by,
                    reason,
                    expires_at,
                    created_at
                FROM hive.task_overrides
                WHERE task_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (task_id,),
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "gate_name": row["gate_name"],
                "scope": row["scope"],
                "approved_by": row["approved_by"],
                "reason": row["reason"],
                "expires_at": row["expires_at"].isoformat(),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]


async def set_task_contract(
    task_id: int,
    allowed_paths: list[str],
    forbidden_paths: list[str] | None = None,
    dependencies: list[int] | None = None,
    required_tests: dict[str, list[str]] | None = None,
    review_policy: dict[str, Any] | None = None,
    handoff_template: str = "v1_task_handoff",
    contract_version: int = 1,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT id, depends_on FROM hive.tasks WHERE id = %s",
                (task_id,),
            )
            task_row = await cursor.fetchone()
            if task_row is None:
                raise ValueError(f"Task {task_id} not found")

            task_dependencies = task_row["depends_on"] or []
            effective_dependencies = (
                dependencies if dependencies is not None else task_dependencies
            )
            if sorted(effective_dependencies) != sorted(task_dependencies):
                raise ValueError(
                    "Task contract dependencies must match task depends_on"
                )

            normalized = _normalize_task_contract_payload(
                allowed_paths=allowed_paths,
                forbidden_paths=forbidden_paths or [],
                dependencies=effective_dependencies,
                required_tests=required_tests
                or {
                    "red": ["pytest tests/ -k <task_red>"],
                    "green": ["pytest tests/ -v"],
                },
                review_policy=review_policy
                or {
                    "min_reviews": 1,
                    "independent_required": True,
                },
                handoff_template=handoff_template,
                contract_version=contract_version,
            )

            await cursor.execute(
                """
                INSERT INTO hive.task_contracts (
                    task_id,
                    contract_version,
                    allowed_paths,
                    forbidden_paths,
                    dependencies,
                    required_tests,
                    review_policy,
                    handoff_template,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, now())
                ON CONFLICT (task_id) DO UPDATE
                SET
                    contract_version = EXCLUDED.contract_version,
                    allowed_paths = EXCLUDED.allowed_paths,
                    forbidden_paths = EXCLUDED.forbidden_paths,
                    dependencies = EXCLUDED.dependencies,
                    required_tests = EXCLUDED.required_tests,
                    review_policy = EXCLUDED.review_policy,
                    handoff_template = EXCLUDED.handoff_template,
                    updated_at = now()
                """,
                (
                    task_id,
                    normalized["contract_version"],
                    normalized["allowed_paths"],
                    normalized["forbidden_paths"],
                    normalized["dependencies"],
                    json.dumps(normalized["required_tests"]),
                    json.dumps(normalized["review_policy"]),
                    normalized["handoff_template"],
                ),
            )

            contract = await _fetch_task_contract(task_id, conn)
            assert contract is not None
            return contract


async def get_current_task(assigned_to: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            {SUMMARY_SELECT}
            WHERE t.assigned_to = %s
              AND t.status IN ('in_progress', 'blocked', 'open')
            ORDER BY
                CASE t.status WHEN 'in_progress' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
                m.priority DESC NULLS LAST,
                t.sequence_order,
                t.id
            LIMIT 1
            """,
            (assigned_to,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return await _fetch_task_full(row["id"], conn)


async def get_next_task(assigned_to: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            {SUMMARY_SELECT}
            WHERE t.status = 'open'
              AND (t.assigned_to = %s OR t.assigned_to IS NULL)
              AND {DEPS_MET_CONDITION}
              AND EXISTS (
                    SELECT 1
                    FROM hive.task_contracts tc
                    WHERE tc.task_id = t.id
                      AND COALESCE(
                            (
                                SELECT array_agg(dep ORDER BY dep)
                                FROM unnest(tc.dependencies) AS dep
                            ),
                            '{{}}'::int[]
                        ) = COALESCE(
                            (
                                SELECT array_agg(dep ORDER BY dep)
                                FROM unnest(t.depends_on) AS dep
                            ),
                            '{{}}'::int[]
                        )
                )
            ORDER BY
                CASE WHEN t.assigned_to = %s THEN 0 ELSE 1 END,
                m.priority DESC NULLS LAST,
                t.sequence_order,
                t.id
            LIMIT 1
            """,
            (assigned_to, assigned_to),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _serialize_summary_task(row)


async def claim_task(task_id: int, assigned_to: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)

            await cursor.execute(
                """
                SELECT status, depends_on
                FROM hive.tasks
                WHERE id = %s
                """,
                (task_id,),
            )
            existing = await cursor.fetchone()
            if existing is None:
                raise ValueError(f"Task {task_id} not found")
            if existing["status"] != "open":
                raise ValueError(f"Task {task_id} is not open")
            await _assert_task_can_start(task_id, conn)

            await cursor.execute(
                """
                UPDATE hive.tasks
                SET status = 'in_progress', assigned_to = %s, updated_at = now()
                WHERE id = %s AND status = 'open'
                RETURNING id
                """,
                (assigned_to, task_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} is not open")
            return await _fetch_task_full(task_id, conn)


async def release_task(task_id: int) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                """
                UPDATE hive.tasks
                SET status = 'open', assigned_to = NULL, updated_at = now()
                WHERE id = %s AND status = 'in_progress'
                RETURNING id
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                # Distinguish "not found" from "wrong status"
                await cursor.execute(
                    "SELECT status FROM hive.tasks WHERE id = %s",
                    (task_id,),
                )
                existing = await cursor.fetchone()
                if existing is None:
                    raise ValueError(f"Task {task_id} not found")
                raise ValueError(
                    f"Task {task_id} cannot be released"
                    f" (status is '{existing['status']}',"
                    f" must be 'in_progress')"
                )
            return await _fetch_task_full(task_id, conn)


async def list_tasks(
    assigned_to: str | None = None,
    status: str | None = None,
    milestone_id: int | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    if status is not None:
        _validate_task_status(status)

    conditions: list[str] = []
    params: list[Any] = []

    if assigned_to is not None:
        conditions.append("t.assigned_to = %s")
        params.append(assigned_to)
    if status is not None:
        conditions.append("t.status = %s")
        params.append(status)
    if milestone_id is not None:
        conditions.append("t.milestone_id = %s")
        params.append(milestone_id)
    if tag is not None:
        conditions.append("%s = ANY(t.tags)")
        params.append(tag)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            {SUMMARY_SELECT}
            {where_clause}
            ORDER BY m.priority DESC NULLS LAST, t.sequence_order, t.id
            """,
            params,
        )
        return [_serialize_summary_task(row) for row in await cursor.fetchall()]


async def update_task(
    task_id: int,
    status: str | None = None,
    assigned_to: str | None = None,
) -> dict[str, Any]:
    if status is not None:
        _validate_task_status(status)

    set_clauses = ["updated_at = now()"]
    params: list[Any] = []

    if status is not None:
        set_clauses.append("status = %s")
        params.append(status)
    if assigned_to is not None:
        set_clauses.append("assigned_to = %s")
        params.append(assigned_to)

    params.append(task_id)

    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            "SELECT id, status, assigned_to FROM hive.tasks WHERE id = %s",
            (task_id,),
        )
        existing = await cursor.fetchone()
        if existing is None:
            raise ValueError(f"Task {task_id} not found")

        actor = (
            assigned_to.strip()
            if isinstance(assigned_to, str) and assigned_to.strip() != ""
            else (
                existing["assigned_to"].strip()
                if isinstance(existing["assigned_to"], str)
                and existing["assigned_to"].strip() != ""
                else "system"
            )
        )

        if status == "in_progress" and existing["status"] != "in_progress":
            async with conn.transaction():
                await _assert_task_can_start(task_id, conn)

        if status == "done":
            gate_results: list[tuple[str, str, str]]
            async with conn.transaction():
                gate_results = await _evaluate_done_gates(task_id, conn)
                overrides = await _fetch_active_task_overrides(task_id, conn)
                gate_results = _apply_gate_overrides(gate_results, overrides)
                for gate_name, decision, reason in gate_results:
                    await _record_gate_event(
                        task_id=task_id,
                        gate_name=gate_name,
                        decision=decision,
                        reason=reason,
                        actor=actor,
                        conn=conn,
                    )

            failures = [
                f"{gate_name}: {reason}"
                for gate_name, decision, reason in gate_results
                if decision == "fail"
            ]
            if failures:
                raise ValueError(
                    "Task "
                    f"{task_id} failed gate checks: "
                    + "; ".join(failures)
                )

        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                f"""
                UPDATE hive.tasks
                SET {", ".join(set_clauses)}
                WHERE id = %s
                RETURNING id, status, updated_at
                """,
                params,
            )
            row = await cursor.fetchone()
            assert row is not None
            if row["status"] == "done":
                await cursor.execute(
                    """
                    UPDATE hive.task_evidence_artifacts
                    SET retention_until = GREATEST(
                        retention_until,
                        %s + INTERVAL '180 days'
                    )
                    WHERE task_id = %s
                    """,
                    (row["updated_at"], task_id),
                )
            return await _fetch_task_full(task_id, conn)


async def create_task(
    title: str,
    description: str | None = None,
    milestone_id: int | None = None,
    assigned_to: str | None = None,
    sequence_order: int = 0,
    github_issues: list[int] | None = None,
    tags: list[str] | None = None,
    relevant_docs: list[str] | None = None,
    depends_on: list[int] | None = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            try:
                await cursor.execute(
                    """
                    INSERT INTO hive.tasks (
                        title,
                        description,
                        milestone_id,
                        assigned_to,
                        sequence_order,
                        github_issues,
                        tags,
                        relevant_docs,
                        depends_on
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        title,
                        description,
                        milestone_id,
                        assigned_to,
                        sequence_order,
                        github_issues or [],
                        tags or [],
                        relevant_docs or [],
                        depends_on or [],
                    ),
                )
            except psycopg.errors.ForeignKeyViolation as exc:
                raise ValueError(f"Milestone {milestone_id} not found") from exc

            row = await cursor.fetchone()
            assert row is not None
            return await _fetch_task_summary(row["id"], conn)


async def list_gate_events(
    task_id: int,
    gate_name: str | None = None,
    decision: str | None = None,
    limit: int = 100,
    cursor: int | None = None,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.connection() as conn:
        check = conn.cursor()
        await check.execute("SELECT 1 FROM hive.tasks WHERE id = %s", (task_id,))
        if await check.fetchone() is None:
            raise ValueError(f"Task {task_id} not found")

        conditions = ["task_id = %s"]
        params: list[Any] = [task_id]
        if gate_name is not None:
            conditions.append("gate_name = %s")
            params.append(gate_name)
        if decision is not None:
            conditions.append("decision = %s")
            params.append(decision)
        if cursor is not None:
            conditions.append("id < %s")
            params.append(cursor)
        params.append(limit)

        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            f"""
            SELECT id, task_id, gate_name, decision, reason, actor, artifact_ref, created_at
            FROM hive.task_gate_events
            WHERE {" AND ".join(conditions)}
            ORDER BY id DESC
            LIMIT %s
            """,
            params,
        )
        rows = await cur.fetchall()
    return [
        {
            "id": row["id"],
            "task_id": row["task_id"],
            "gate_name": row["gate_name"],
            "decision": row["decision"],
            "reason": row["reason"],
            "actor": row["actor"],
            "artifact_ref": row["artifact_ref"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


async def expire_override(
    override_id: int,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                """
                UPDATE hive.task_overrides
                SET expires_at = now(), updated_at = now()
                WHERE id = %s
                RETURNING id, task_id, gate_name, scope, approved_by, reason, expires_at, created_at
                """,
                (override_id,),
            )
            row = await cur.fetchone()
            if row is None:
                raise ValueError(f"Override {override_id} not found")
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "gate_name": row["gate_name"],
                "scope": row["scope"],
                "approved_by": row["approved_by"],
                "reason": row["reason"],
                "expires_at": row["expires_at"].isoformat(),
                "created_at": row["created_at"].isoformat(),
                "expired_by": actor,
                "expired_reason": reason,
            }


async def reopen_task(task_id: int, actor: str, reason: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, status FROM hive.tasks WHERE id = %s",
                (task_id,),
            )
            row = await cur.fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} not found")
            if row["status"] not in ("done", "cancelled", "superseded"):
                raise ValueError(
                    f"Cannot reopen task {task_id} with status '{row['status']}': "
                    "only done, cancelled, or superseded tasks can be reopened"
                )
            await cur.execute(
                """
                UPDATE hive.tasks
                SET status = 'open', updated_at = now()
                WHERE id = %s
                """,
                (task_id,),
            )
            return await _fetch_task_full(task_id, conn)


async def supersede_task(
    task_id: int,
    replacement_task_id: int,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute("SELECT id FROM hive.tasks WHERE id = %s", (task_id,))
            if await cur.fetchone() is None:
                raise ValueError(f"Task {task_id} not found")
            await cur.execute(
                "SELECT id FROM hive.tasks WHERE id = %s", (replacement_task_id,)
            )
            if await cur.fetchone() is None:
                raise ValueError(f"Replacement task {replacement_task_id} not found")
            await cur.execute(
                """
                UPDATE hive.tasks
                SET status = 'superseded', updated_at = now()
                WHERE id = %s
                """,
                (task_id,),
            )
            return await _fetch_task_full(task_id, conn)


async def validate_task_contract(task_id: int) -> dict[str, Any]:
    """Dry-run the done gates for a task without recording any events."""
    pool = await get_pool()
    async with pool.connection() as conn:
        contract = await _fetch_task_contract(task_id, conn)
        if contract is None:
            raise ValueError(f"Task {task_id} has no contract")
        gate_results = await _evaluate_done_gates(task_id, conn)
        overrides = await _fetch_active_task_overrides(task_id, conn)
        gate_results = _apply_gate_overrides(gate_results, overrides)
    return {
        "task_id": task_id,
        "gates": [
            {"gate_name": gate_name, "decision": decision, "reason": reason}
            for gate_name, decision, reason in gate_results
        ],
        "all_pass": all(decision == "pass" for _, decision, _ in gate_results),
    }

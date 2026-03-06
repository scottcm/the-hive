import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

TASK_STATUSES = {"open", "in_progress", "blocked", "done", "cancelled"}
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
        SELECT id, question, status
        FROM hive.clarifications
        WHERE task_id = %s AND status = 'pending'
        ORDER BY created_at, id
        """,
        (task_id,),
    )
    task["pending_clarifications"] = [
        {
            "id": row["id"],
            "question": row["question"],
            "status": row["status"],
        }
        for row in await clarifications_cursor.fetchall()
    ]
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
    normalized = _normalize_task_contract_payload(
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths or [],
        dependencies=dependencies or [],
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

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT id FROM hive.tasks WHERE id = %s",
                (task_id,),
            )
            task_row = await cursor.fetchone()
            if task_row is None:
                raise ValueError(f"Task {task_id} not found")

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

            contract = await _fetch_task_contract(task_id, conn)
            if contract is None:
                raise ValueError(
                    f"Task {task_id} is missing required task contract"
                )

            depends_on = existing["depends_on"] or []
            if sorted(contract["dependencies"]) != sorted(depends_on):
                raise ValueError(
                    f"Task {task_id} contract dependencies do not match task depends_on"
                )

            # Check for unmet dependencies before allowing claim
            await cursor.execute(
                """
                SELECT dt.id, dt.title, dt.status
                FROM hive.tasks t
                CROSS JOIN LATERAL unnest(t.depends_on) AS dep_id
                JOIN hive.tasks dt ON dt.id = dep_id
                WHERE t.id = %s AND dt.status NOT IN ('done', 'cancelled')
                """,
                (task_id,),
            )
            unmet = await cursor.fetchall()
            if unmet:
                blockers = ", ".join(
                    f"#{r['id']} ({r['status']})" for r in unmet
                )
                raise ValueError(
                    f"Task {task_id} has unmet dependencies: {blockers}"
                )

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
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                f"""
                UPDATE hive.tasks
                SET {", ".join(set_clauses)}
                WHERE id = %s
                RETURNING id
                """,
                params,
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} not found")
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

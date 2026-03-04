from typing import Any

import psycopg
from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

TASK_STATUSES = {"open", "in_progress", "blocked", "done", "cancelled"}
SUMMARY_SELECT = """
    SELECT
        t.id,
        t.section_id,
        t.title,
        t.description,
        t.status,
        t.assigned_to,
        t.github_issue,
        t.relevant_docs,
        t.sequence_order,
        s.name AS section_name,
        s.description AS section_description
    FROM hive.tasks t
    LEFT JOIN hive.sections s ON s.id = t.section_id
"""


def _serialize_summary_task(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "assigned_to": row["assigned_to"],
        "section_id": row["section_id"],
        "section_name": row["section_name"],
        "section_description": row["section_description"],
        "github_issue": row["github_issue"],
        "relevant_docs": row["relevant_docs"],
        "sequence_order": row["sequence_order"],
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


async def get_current_task(assigned_to: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            {SUMMARY_SELECT}
            WHERE t.assigned_to = %s
              AND t.status IN ('in_progress', 'open')
            ORDER BY
                CASE t.status WHEN 'in_progress' THEN 0 ELSE 1 END,
                s.priority DESC NULLS LAST,
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
            ORDER BY
                CASE WHEN t.assigned_to = %s THEN 0 ELSE 1 END,
                s.priority DESC NULLS LAST,
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
                WHERE id = %s
                RETURNING id
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} not found")
            return await _fetch_task_full(task_id, conn)


async def list_tasks(
    assigned_to: str | None = None,
    status: str | None = None,
    section_id: int | None = None,
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
    if section_id is not None:
        conditions.append("t.section_id = %s")
        params.append(section_id)

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
            ORDER BY s.priority DESC NULLS LAST, t.sequence_order, t.id
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
    section_id: int | None = None,
    assigned_to: str | None = None,
    sequence_order: int = 0,
    github_issue: int | None = None,
    relevant_docs: list[str] | None = None,
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
                        section_id,
                        assigned_to,
                        sequence_order,
                        github_issue,
                        relevant_docs
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        title,
                        description,
                        section_id,
                        assigned_to,
                        sequence_order,
                        github_issue,
                        relevant_docs or [],
                    ),
                )
            except psycopg.errors.ForeignKeyViolation as exc:
                raise ValueError(f"Section {section_id} not found") from exc

            row = await cursor.fetchone()
            assert row is not None
            return await _fetch_task_summary(row["id"], conn)

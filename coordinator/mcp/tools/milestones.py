from typing import Any

import psycopg
from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

MILESTONE_STATUSES = {"active", "done", "archived"}
MILESTONE_SELECT = """
    SELECT
        m.id,
        m.project_id,
        m.name,
        m.description,
        m.priority,
        m.status,
        p.name AS project_name,
        COUNT(t.id) FILTER (WHERE t.status = 'open') AS open_count,
        COUNT(t.id) FILTER (WHERE t.status = 'in_progress') AS in_progress_count,
        COUNT(t.id) FILTER (WHERE t.status = 'done') AS done_count,
        COUNT(t.id) FILTER (WHERE t.status = 'blocked') AS blocked_count
    FROM hive.milestones m
    LEFT JOIN hive.projects p ON p.id = m.project_id
    LEFT JOIN hive.tasks t ON t.milestone_id = m.id
"""


def _serialize_milestone(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "project_name": row["project_name"],
        "name": row["name"],
        "description": row["description"],
        "priority": row["priority"],
        "status": row["status"],
        "task_counts": {
            "open": row["open_count"],
            "in_progress": row["in_progress_count"],
            "done": row["done_count"],
            "blocked": row["blocked_count"],
        },
    }


def _validate_milestone_status(status: str) -> None:
    if status not in MILESTONE_STATUSES:
        raise ValueError(f"Invalid status: {status}")


async def _fetch_milestone(milestone_id: int, conn: Any) -> dict[str, Any]:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        f"""
        {MILESTONE_SELECT}
        WHERE m.id = %s
        GROUP BY m.id, p.name
        """,
        (milestone_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Milestone {milestone_id} not found")
    return _serialize_milestone(row)


async def list_milestones(
    status: str | None = None,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    if status is not None:
        _validate_milestone_status(status)

    conditions: list[str] = []
    params: list[Any] = []
    if status is not None:
        conditions.append("m.status = %s")
        params.append(status)
    if project_id is not None:
        conditions.append("m.project_id = %s")
        params.append(project_id)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            {MILESTONE_SELECT}
            {where_clause}
            GROUP BY m.id, p.name
            ORDER BY m.priority DESC, m.id
            """,
            params,
        )
        return [_serialize_milestone(row) for row in await cursor.fetchall()]


async def create_milestone(
    name: str,
    description: str | None = None,
    priority: int = 0,
    project_id: int | None = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            try:
                await cursor.execute(
                    """
                    INSERT INTO hive.milestones (name, description, priority, project_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (name, description, priority, project_id),
                )
            except psycopg.errors.ForeignKeyViolation as exc:
                raise ValueError(
                    f"Project {project_id} not found"
                ) from exc
            row = await cursor.fetchone()
            assert row is not None
            return await _fetch_milestone(row["id"], conn)


async def update_milestone(
    milestone_id: int,
    name: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    if status is not None:
        _validate_milestone_status(status)

    set_clauses = ["updated_at = now()"]
    params: list[Any] = []

    if name is not None:
        set_clauses.append("name = %s")
        params.append(name)
    if description is not None:
        set_clauses.append("description = %s")
        params.append(description)
    if priority is not None:
        set_clauses.append("priority = %s")
        params.append(priority)
    if status is not None:
        set_clauses.append("status = %s")
        params.append(status)

    params.append(milestone_id)

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                f"""
                UPDATE hive.milestones
                SET {", ".join(set_clauses)}
                WHERE id = %s
                RETURNING id
                """,
                params,
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Milestone {milestone_id} not found")
            return await _fetch_milestone(milestone_id, conn)

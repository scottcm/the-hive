from typing import Any

from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

PROJECT_STATUSES = {"active", "archived"}
PROJECT_SELECT = """
    SELECT
        p.id,
        p.name,
        p.description,
        p.status,
        COUNT(DISTINCT m.id) AS milestone_count,
        COUNT(t.id) FILTER (WHERE t.status = 'open') AS open_count,
        COUNT(t.id) FILTER (WHERE t.status = 'in_progress') AS in_progress_count,
        COUNT(t.id) FILTER (WHERE t.status = 'blocked') AS blocked_count,
        COUNT(t.id) FILTER (WHERE t.status = 'done') AS done_count
    FROM hive.projects p
    LEFT JOIN hive.milestones m ON m.project_id = p.id
    LEFT JOIN hive.tasks t ON t.milestone_id = m.id
"""


def _serialize_project(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "milestone_count": row["milestone_count"],
        "task_counts": {
            "open": row["open_count"],
            "in_progress": row["in_progress_count"],
            "blocked": row["blocked_count"],
            "done": row["done_count"],
        },
    }


def _validate_project_status(status: str) -> None:
    if status not in PROJECT_STATUSES:
        raise ValueError(f"Invalid status: {status}")


async def _fetch_project(project_id: int, conn: Any) -> dict[str, Any]:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        f"""
        {PROJECT_SELECT}
        WHERE p.id = %s
        GROUP BY p.id
        """,
        (project_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Project {project_id} not found")
    return _serialize_project(row)


async def list_projects(status: str | None = None) -> list[dict[str, Any]]:
    if status is not None:
        _validate_project_status(status)

    where_clause = ""
    params: list[Any] = []
    if status is not None:
        where_clause = "WHERE p.status = %s"
        params.append(status)

    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            {PROJECT_SELECT}
            {where_clause}
            GROUP BY p.id
            ORDER BY p.name
            """,
            params,
        )
        return [_serialize_project(row) for row in await cursor.fetchall()]


async def create_project(
    name: str,
    description: str | None = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                """
                INSERT INTO hive.projects (name, description)
                VALUES (%s, %s)
                RETURNING id
                """,
                (name, description),
            )
            row = await cursor.fetchone()
            assert row is not None
            return await _fetch_project(row["id"], conn)


async def update_project(
    project_id: int,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    if status is not None:
        _validate_project_status(status)

    set_clauses = ["updated_at = now()"]
    params: list[Any] = []

    if name is not None:
        set_clauses.append("name = %s")
        params.append(name)
    if description is not None:
        set_clauses.append("description = %s")
        params.append(description)
    if status is not None:
        set_clauses.append("status = %s")
        params.append(status)

    params.append(project_id)

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                f"""
                UPDATE hive.projects
                SET {", ".join(set_clauses)}
                WHERE id = %s
                RETURNING id
                """,
                params,
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Project {project_id} not found")
            return await _fetch_project(project_id, conn)

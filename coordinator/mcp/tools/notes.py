import psycopg
from psycopg.rows import dict_row

from coordinator.db.connection import get_pool


async def add_note(task_id: int, author: str, content: str) -> dict[str, str | int]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            task_cursor = conn.cursor()
            await task_cursor.execute(
                "SELECT 1 FROM hive.tasks WHERE id = %s",
                (task_id,),
            )
            if await task_cursor.fetchone() is None:
                raise ValueError(f"Task {task_id} not found")

            cursor = conn.cursor(row_factory=dict_row)
            try:
                await cursor.execute(
                    """
                    INSERT INTO hive.task_notes (task_id, author, content)
                    VALUES (%s, %s, %s)
                    RETURNING id, task_id, author, content, created_at
                    """,
                    (task_id, author, content),
                )
            except psycopg.errors.ForeignKeyViolation as exc:
                raise ValueError(f"Task {task_id} not found") from exc

            row = await cursor.fetchone()
            assert row is not None
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "author": row["author"],
                "content": row["content"],
                "created_at": row["created_at"].isoformat(),
            }


async def list_notes(
    task_id: int,
    limit: int = 100,
    cursor: int | None = None,
) -> list[dict[str, str | int]]:
    pool = await get_pool()
    async with pool.connection() as conn:
        check = conn.cursor()
        await check.execute("SELECT 1 FROM hive.tasks WHERE id = %s", (task_id,))
        if await check.fetchone() is None:
            raise ValueError(f"Task {task_id} not found")

        conditions = ["task_id = %s"]
        params: list = [task_id]
        if cursor is not None:
            conditions.append("id < %s")
            params.append(cursor)
        params.append(limit)

        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            f"""
            SELECT id, task_id, author, content, created_at
            FROM hive.task_notes
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
            "author": row["author"],
            "content": row["content"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]

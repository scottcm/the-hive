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

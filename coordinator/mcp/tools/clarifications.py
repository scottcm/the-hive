from typing import Any

from psycopg.rows import dict_row

from coordinator.db.connection import get_pool


def _serialize_clarification_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "asked_by": row["asked_by"],
        "question": row["question"],
        "answer": row["answer"],
        "status": row["status"],
        "answered_at": row["answered_at"].isoformat() if row["answered_at"] is not None else None,
    }


async def create_clarification(task_id: int, asked_by: str, question: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            task_cursor = conn.cursor(row_factory=dict_row)
            await task_cursor.execute(
                """
                UPDATE hive.tasks
                SET status = 'blocked', updated_at = now()
                WHERE id = %s
                RETURNING id
                """,
                (task_id,),
            )
            if await task_cursor.fetchone() is None:
                raise ValueError(f"Task {task_id} not found")

            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                """
                INSERT INTO hive.clarifications (task_id, asked_by, question)
                VALUES (%s, %s, %s)
                RETURNING id, task_id, asked_by, question, answer, status, answered_at
                """,
                (task_id, asked_by, question),
            )
            row = await cursor.fetchone()
            assert row is not None
            clarification = _serialize_clarification_row(row)
            return {
                "id": clarification["id"],
                "task_id": clarification["task_id"],
                "asked_by": clarification["asked_by"],
                "question": clarification["question"],
                "status": clarification["status"],
            }


async def answer_clarification(clarification_id: int, answer: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            """
            UPDATE hive.clarifications
            SET answer = %s, status = 'answered', answered_at = now()
            WHERE id = %s
            RETURNING id, task_id, asked_by, question, answer, status, answered_at
            """,
            (answer, clarification_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Clarification {clarification_id} not found")
        return _serialize_clarification_row(row)

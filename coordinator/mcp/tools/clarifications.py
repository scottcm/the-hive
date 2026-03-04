from typing import Any

from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

CLARIFICATION_STATUSES = {"pending", "answered"}


def _serialize_clarification(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "asked_by": row["asked_by"],
        "question": row["question"],
        "answer": row["answer"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "answered_at": (
            row["answered_at"].isoformat() if row["answered_at"] is not None else None
        ),
    }


def _validate_clarification_status(status: str) -> None:
    if status not in CLARIFICATION_STATUSES:
        raise ValueError(f"Invalid status: {status}")


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
            task_row = await task_cursor.fetchone()
            if task_row is None:
                raise ValueError(f"Task {task_id} not found")

            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                """
                INSERT INTO hive.clarifications (task_id, asked_by, question)
                VALUES (%s, %s, %s)
                RETURNING id, task_id, asked_by, question, answer, status, created_at, answered_at
                """,
                (task_id, asked_by, question),
            )
            row = await cursor.fetchone()
            assert row is not None
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "asked_by": row["asked_by"],
                "question": row["question"],
                "status": row["status"],
            }


async def answer_clarification(clarification_id: int, answer: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                """
                UPDATE hive.clarifications
                SET answer = %s, status = 'answered', answered_at = now()
                WHERE id = %s
                RETURNING id, task_id, asked_by, question, answer, status, created_at, answered_at
                """,
                (answer, clarification_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Clarification {clarification_id} not found")

            clarification = _serialize_clarification(row)

            count_cursor = conn.cursor()
            await count_cursor.execute(
                """
                SELECT COUNT(*)
                FROM hive.clarifications
                WHERE task_id = %s AND status = 'pending'
                """,
                (clarification["task_id"],),
            )
            remaining_pending = (await count_cursor.fetchone())[0]

            if remaining_pending == 0:
                task_cursor = conn.cursor()
                await task_cursor.execute(
                    """
                    UPDATE hive.tasks
                    SET status = 'open', updated_at = now()
                    WHERE id = %s AND status = 'blocked'
                    """,
                    (clarification["task_id"],),
                )

            return clarification


async def list_clarifications(
    status: str | None = None,
    task_id: int | None = None,
    asked_by: str | None = None,
) -> list[dict[str, Any]]:
    if status is not None:
        _validate_clarification_status(status)

    conditions: list[str] = []
    params: list[Any] = []

    if status is not None:
        conditions.append("c.status = %s")
        params.append(status)
    if task_id is not None:
        conditions.append("c.task_id = %s")
        params.append(task_id)
    if asked_by is not None:
        conditions.append("c.asked_by = %s")
        params.append(asked_by)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            SELECT
                c.id,
                c.task_id,
                t.title AS task_title,
                c.asked_by,
                c.question,
                c.answer,
                c.status,
                c.created_at,
                c.answered_at
            FROM hive.clarifications c
            JOIN hive.tasks t ON t.id = c.task_id
            {where_clause}
            ORDER BY c.created_at DESC, c.id DESC
            """,
            params,
        )
        rows = await cursor.fetchall()

    return [
        {
            "id": row["id"],
            "task_id": row["task_id"],
            "task_title": row["task_title"],
            "asked_by": row["asked_by"],
            "question": row["question"],
            "answer": row["answer"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "answered_at": (
                row["answered_at"].isoformat()
                if row["answered_at"] is not None
                else None
            ),
        }
        for row in rows
    ]

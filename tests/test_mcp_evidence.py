from datetime import datetime, timedelta, timezone

import pytest

from coordinator.mcp.tools import evidence


async def insert_task(db_pool, *, title: str) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (title)
            VALUES (%s)
            RETURNING id
            """,
            (title,),
        )
        return (await cursor.fetchone())[0]


async def test_record_task_evidence_round_trip(db_pool):
    task_id = await insert_task(db_pool, title="Evidence target")
    captured_at = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)

    artifact = await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="a" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        captured_at=captured_at.isoformat(),
        immutable=True,
        metadata={
            "command": "uv run pytest tests/test_mcp_evidence.py -k red -v",
            "summary": "1 failed",
        },
    )

    assert artifact["task_id"] == task_id
    assert artifact["artifact_type"] == "red_run"
    assert artifact["artifact_hash_sha256"] == "a" * 64
    assert artifact["storage_ref"] == "file://artifacts/red.log"
    assert artifact["captured_by"] == "codex"
    assert artifact["immutable"] is True
    assert artifact["metadata"]["summary"] == "1 failed"
    assert datetime.fromisoformat(artifact["captured_at"]) == captured_at
    assert datetime.fromisoformat(artifact["retention_until"]) == (
        captured_at + timedelta(days=180)
    )

    artifacts = await evidence.list_task_evidence(task_id=task_id)
    assert [row["id"] for row in artifacts] == [artifact["id"]]


async def test_record_task_evidence_rejects_invalid_artifact_type(db_pool):
    task_id = await insert_task(db_pool, title="Evidence target")

    with pytest.raises(ValueError, match="artifact_type"):
        await evidence.record_task_evidence(
            task_id=task_id,
            artifact_type="unknown",
            artifact_hash_sha256="b" * 64,
            storage_ref="file://artifacts/unknown.log",
            captured_by="codex",
        )


async def test_record_task_evidence_rejects_invalid_hash(db_pool):
    task_id = await insert_task(db_pool, title="Evidence target")

    with pytest.raises(ValueError, match="artifact_hash_sha256"):
        await evidence.record_task_evidence(
            task_id=task_id,
            artifact_type="green_run",
            artifact_hash_sha256="not-a-sha",
            storage_ref="file://artifacts/green.log",
            captured_by="codex",
        )


async def test_record_task_evidence_task_not_found(db_pool):
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await evidence.record_task_evidence(
            task_id=9999,
            artifact_type="review_output",
            artifact_hash_sha256="c" * 64,
            storage_ref="file://artifacts/review.md",
            captured_by="codex",
        )


async def test_list_task_evidence_filters_by_artifact_type(db_pool):
    task_id = await insert_task(db_pool, title="Evidence target")

    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="d" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
    )
    green = await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="e" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
    )

    filtered = await evidence.list_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
    )

    assert [row["id"] for row in filtered] == [green["id"]]

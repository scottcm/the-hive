from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from coordinator.mcp.tools import evidence, tasks


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


async def set_task_done_at(db_pool, *, task_id: int, done_at: datetime) -> None:
    async with db_pool.connection() as conn:
        await conn.execute(
            """
            UPDATE hive.tasks
            SET status = 'done', updated_at = %s
            WHERE id = %s
            """,
            (done_at, task_id),
        )


async def fetch_evidence_retention(db_pool, *, artifact_id: int) -> datetime:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT retention_until
            FROM hive.task_evidence_artifacts
            WHERE id = %s
            """,
            (artifact_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row[0]


async def fetch_task_updated_at(db_pool, *, task_id: int) -> datetime:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT updated_at FROM hive.tasks WHERE id = %s",
            (task_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row[0]


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


async def test_record_evidence_for_done_task_anchors_retention_to_done_time(db_pool):
    task_id = await insert_task(db_pool, title="Done task")
    captured_at = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    done_at = datetime(2026, 3, 10, 9, 30, tzinfo=timezone.utc)
    await set_task_done_at(db_pool, task_id=task_id, done_at=done_at)

    artifact = await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="f" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        captured_at=captured_at.isoformat(),
    )

    assert datetime.fromisoformat(artifact["retention_until"]) == (
        done_at + timedelta(days=180)
    )


async def test_marking_task_done_refreshes_existing_evidence_retention_floor(db_pool):
    task_id = await insert_task(db_pool, title="Open task")
    captured_at = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    await tasks.set_task_contract(
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        required_tests={
            "red": ["pytest tests/test_mcp_evidence.py -k retention -v"],
            "green": ["pytest tests/ -v"],
        },
        review_policy={"min_reviews": 1, "independent_required": True},
    )

    artifact = await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="9" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        captured_at=captured_at.isoformat(),
        metadata={
            "failing_tests": [
                "tests/test_mcp_evidence.py::test_marking_task_done_refreshes_existing_evidence_retention_floor"
            ]
        },
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="7" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/evidence.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="6" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={"command": "pytest tests/ -v", "passed": True},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="5" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="claude",
        metadata={"author": "codex", "reviewer": "claude"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="4" * 64,
        storage_ref="file://artifacts/handoff.json",
        captured_by="codex",
        metadata={
            "what_changed": "Updated evidence retention behavior.",
            "why_changed": "Ensure done-transition retention floor.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run companion review"],
        },
    )

    await tasks.update_task(task_id=task_id, status="done")
    done_at = await fetch_task_updated_at(db_pool, task_id=task_id)
    retention_until = await fetch_evidence_retention(
        db_pool,
        artifact_id=artifact["id"],
    )

    assert retention_until == done_at + timedelta(days=180)


async def test_task_with_evidence_cannot_be_deleted(db_pool):
    task_id = await insert_task(db_pool, title="Protected task")
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="8" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="codex",
    )

    async with db_pool.connection() as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await conn.execute("DELETE FROM hive.tasks WHERE id = %s", (task_id,))

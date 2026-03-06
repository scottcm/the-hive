from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any

from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

EVIDENCE_ARTIFACT_TYPES = {
    "red_run",
    "implementation_commit",
    "green_run",
    "review_output",
    "handoff_packet",
}

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_artifact_type(artifact_type: str) -> str:
    if artifact_type not in EVIDENCE_ARTIFACT_TYPES:
        raise ValueError(f"Invalid artifact_type: {artifact_type}")
    return artifact_type


def _validate_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid artifact_hash_sha256: expected 64 lowercase hex chars")
    return normalized


def _validate_non_empty(field_name: str, value: str) -> str:
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def _parse_captured_at(captured_at: str | None) -> datetime | None:
    if captured_at is None:
        return None
    text = captured_at.strip()
    if text == "":
        raise ValueError("captured_at must be a non-empty ISO-8601 string")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("captured_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include timezone offset")
    return parsed


def _serialize_artifact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "artifact_type": row["artifact_type"],
        "artifact_hash_sha256": row["artifact_hash_sha256"],
        "storage_ref": row["storage_ref"],
        "captured_by": row["captured_by"],
        "captured_at": row["captured_at"].isoformat(),
        "immutable": row["immutable"],
        "metadata": row["metadata"],
        "retention_until": row["retention_until"].isoformat(),
        "created_at": row["created_at"].isoformat(),
    }


async def record_task_evidence(
    task_id: int,
    artifact_type: str,
    artifact_hash_sha256: str,
    storage_ref: str,
    captured_by: str,
    captured_at: str | None = None,
    immutable: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_artifact_type = _validate_artifact_type(artifact_type)
    normalized_hash = _validate_sha256(artifact_hash_sha256)
    normalized_storage_ref = _validate_non_empty("storage_ref", storage_ref)
    normalized_captured_by = _validate_non_empty("captured_by", captured_by)
    normalized_captured_at = _parse_captured_at(captured_at)
    effective_captured_at = normalized_captured_at or datetime.now(timezone.utc)
    retention_until = effective_captured_at + timedelta(days=180)
    normalized_metadata = metadata or {}
    if not isinstance(normalized_metadata, dict):
        raise ValueError("metadata must be an object")

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            task_cursor = conn.cursor(row_factory=dict_row)
            await task_cursor.execute(
                "SELECT id FROM hive.tasks WHERE id = %s",
                (task_id,),
            )
            task_row = await task_cursor.fetchone()
            if task_row is None:
                raise ValueError(f"Task {task_id} not found")

            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                """
                INSERT INTO hive.task_evidence_artifacts (
                    task_id,
                    artifact_type,
                    artifact_hash_sha256,
                    storage_ref,
                    captured_by,
                    captured_at,
                    retention_until,
                    immutable,
                    metadata
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::jsonb
                )
                RETURNING
                    id,
                    task_id,
                    artifact_type,
                    artifact_hash_sha256,
                    storage_ref,
                    captured_by,
                    captured_at,
                    immutable,
                    metadata,
                    retention_until,
                    created_at
                """,
                (
                    task_id,
                    normalized_artifact_type,
                    normalized_hash,
                    normalized_storage_ref,
                    normalized_captured_by,
                    effective_captured_at,
                    retention_until,
                    immutable,
                    json.dumps(normalized_metadata),
                ),
            )
            row = await cursor.fetchone()
            assert row is not None
            return _serialize_artifact(row)


async def list_task_evidence(
    task_id: int,
    artifact_type: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [task_id]
    where_clause = "WHERE e.task_id = %s"

    if artifact_type is not None:
        normalized_artifact_type = _validate_artifact_type(artifact_type)
        where_clause += " AND e.artifact_type = %s"
        params.append(normalized_artifact_type)

    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            SELECT
                e.id,
                e.task_id,
                e.artifact_type,
                e.artifact_hash_sha256,
                e.storage_ref,
                e.captured_by,
                e.captured_at,
                e.immutable,
                e.metadata,
                e.retention_until,
                e.created_at
            FROM hive.task_evidence_artifacts e
            {where_clause}
            ORDER BY e.captured_at, e.id
            """,
            params,
        )
        return [_serialize_artifact(row) for row in await cursor.fetchall()]

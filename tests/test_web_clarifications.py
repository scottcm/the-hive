import pytest
from httpx import ASGITransport, AsyncClient

from coordinator.web.app import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_task(client: AsyncClient, title: str = "Task") -> dict:
    resp = await client.post("/api/tasks", json={"title": title})
    assert resp.status_code == 201
    return resp.json()


async def _fetch_task_status(db_pool, task_id: int) -> str:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT status FROM hive.tasks WHERE id = %s",
            (task_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row[0]


async def test_list_clarifications_empty(db_pool, client):
    resp = await client.get("/api/clarifications")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_clarification_blocks_task(db_pool, client):
    task = await _create_task(client, "Needs input")

    resp = await client.post(
        "/api/clarifications",
        json={
            "task_id": task["id"],
            "asked_by": "codex-scott",
            "question": "Should this use batching?",
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] > 0
    assert data["task_id"] == task["id"]
    assert data["asked_by"] == "codex-scott"
    assert data["question"] == "Should this use batching?"
    assert data["status"] == "pending"
    assert await _fetch_task_status(db_pool, task["id"]) == "blocked"


async def test_list_clarifications_filters(db_pool, client):
    first = await _create_task(client, "First")
    second = await _create_task(client, "Second")

    first_clar = await client.post(
        "/api/clarifications",
        json={
            "task_id": first["id"],
            "asked_by": "codex-scott",
            "question": "First pending?",
        },
    )
    second_clar = await client.post(
        "/api/clarifications",
        json={
            "task_id": second["id"],
            "asked_by": "codex-scott",
            "question": "Second pending?",
        },
    )

    assert first_clar.status_code == 201
    assert second_clar.status_code == 201

    answer_resp = await client.patch(
        f"/api/clarifications/{first_clar.json()['id']}",
        json={"answer": "Answered"},
    )
    assert answer_resp.status_code == 200

    by_status = await client.get("/api/clarifications", params={"status": "pending"})
    by_task = await client.get(
        "/api/clarifications",
        params={"task_id": second["id"], "status": "pending"},
    )

    assert by_status.status_code == 200
    assert [item["id"] for item in by_status.json()] == [second_clar.json()["id"]]
    assert by_task.status_code == 200
    assert [item["id"] for item in by_task.json()] == [second_clar.json()["id"]]


async def test_answer_clarification_auto_unblocks_task(db_pool, client):
    task = await _create_task(client, "Auto unblock")
    create_resp = await client.post(
        "/api/clarifications",
        json={
            "task_id": task["id"],
            "asked_by": "codex-scott",
            "question": "Can this proceed?",
        },
    )
    clar_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/clarifications/{clar_id}",
        json={"answer": "Yes, proceed."},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == clar_id
    assert data["task_id"] == task["id"]
    assert data["answer"] == "Yes, proceed."
    assert data["status"] == "answered"
    assert data["answered_at"] is not None
    assert await _fetch_task_status(db_pool, task["id"]) == "open"


async def test_answer_clarification_keeps_task_blocked_with_other_pending(db_pool, client):
    task = await _create_task(client, "Still blocked")
    first = await client.post(
        "/api/clarifications",
        json={
            "task_id": task["id"],
            "asked_by": "codex-scott",
            "question": "First?",
        },
    )
    second = await client.post(
        "/api/clarifications",
        json={
            "task_id": task["id"],
            "asked_by": "codex-scott",
            "question": "Second?",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201

    resp = await client.patch(
        f"/api/clarifications/{first.json()['id']}",
        json={"answer": "Only one answered."},
    )

    assert resp.status_code == 200
    assert await _fetch_task_status(db_pool, task["id"]) == "blocked"


async def test_pending_count_endpoint(db_pool, client):
    first = await _create_task(client, "First")
    second = await _create_task(client, "Second")

    first_clar = await client.post(
        "/api/clarifications",
        json={
            "task_id": first["id"],
            "asked_by": "codex-scott",
            "question": "Pending first?",
        },
    )
    await client.post(
        "/api/clarifications",
        json={
            "task_id": second["id"],
            "asked_by": "codex-scott",
            "question": "Pending second?",
        },
    )
    await client.patch(
        f"/api/clarifications/{first_clar.json()['id']}",
        json={"answer": "Resolved"},
    )

    resp = await client.get("/api/clarifications/pending-count")

    assert resp.status_code == 200
    assert resp.json() == {"count": 1}


async def test_create_clarification_not_found_returns_404(db_pool, client):
    resp = await client.post(
        "/api/clarifications",
        json={
            "task_id": 9999,
            "asked_by": "codex-scott",
            "question": "Missing task?",
        },
    )

    assert resp.status_code == 404
    assert resp.json()["error"] == "Task 9999 not found"


async def test_patch_clarification_not_found_returns_404(db_pool, client):
    resp = await client.patch(
        "/api/clarifications/9999",
        json={"answer": "No-op"},
    )

    assert resp.status_code == 404
    assert resp.json()["error"] == "Clarification 9999 not found"


async def test_list_clarifications_invalid_status_returns_422(db_pool, client):
    resp = await client.get("/api/clarifications", params={"status": "unknown"})

    assert resp.status_code == 422
    assert "Invalid status" in resp.json()["error"]

import json

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


async def _create_project(client: AsyncClient, name: str = "Project") -> int:
    resp = await client.post("/api/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_milestone(client: AsyncClient, name: str = "Milestone") -> int:
    project_id = await _create_project(client)
    resp = await client.post(
        "/api/milestones",
        json={"name": name, "project_id": project_id},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _insert_clarification(
    db_pool,
    *,
    task_id: int,
    asked_by: str,
    question: str,
    answer: str | None = None,
    status: str = "pending",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.clarifications (task_id, asked_by, question, answer, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (task_id, asked_by, question, answer, status),
        )
        return (await cursor.fetchone())[0]


async def _insert_task_contract(
    db_pool,
    *,
    task_id: int,
    dependencies: list[int] | None = None,
) -> None:
    async with db_pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO hive.task_contracts (
                task_id,
                contract_version,
                allowed_paths,
                forbidden_paths,
                dependencies,
                required_tests,
                review_policy,
                handoff_template
            )
            VALUES (
                %s, 1, %s, %s, %s, %s::jsonb, %s::jsonb, %s
            )
            """,
            (
                task_id,
                ["coordinator/**"],
                [],
                dependencies or [],
                '{"red":["pytest tests/test_web_tasks.py -k claim"],"green":["pytest tests/test_web_tasks.py -k claim"]}',
                '{"min_reviews":1,"independent_required":true}',
                "v1_task_handoff",
            ),
        )


async def _insert_task_evidence(
    db_pool,
    *,
    task_id: int,
    artifact_type: str,
    artifact_hash_sha256: str,
    captured_by: str,
    metadata: dict,
) -> None:
    async with db_pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO hive.task_evidence_artifacts (
                task_id,
                artifact_type,
                artifact_hash_sha256,
                storage_ref,
                captured_by,
                immutable,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                task_id,
                artifact_type,
                artifact_hash_sha256,
                f"file://artifacts/{artifact_type}.json",
                captured_by,
                True,
                json.dumps(metadata),
            ),
        )


async def test_list_tasks_empty(db_pool, client):
    resp = await client.get("/api/tasks")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_task_minimal(db_pool, client):
    resp = await client.post("/api/tasks", json={"title": "Ship API"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Ship API"
    assert data["status"] == "open"
    assert data["assigned_to"] is None
    assert data["milestone_id"] is None
    assert data["github_issues"] == []
    assert data["tags"] == []
    assert data["relevant_docs"] == []
    assert data["depends_on"] == []


async def test_create_task_full(db_pool, client):
    milestone_id = await _create_milestone(client)
    dep = await _create_task(client, "Dependency")

    resp = await client.post(
        "/api/tasks",
        json={
            "title": "Implement endpoint",
            "description": "Task API endpoint implementation",
            "milestone_id": milestone_id,
            "assigned_to": "codex1",
            "sequence_order": 7,
            "github_issues": [5],
            "tags": ["api", "backend"],
            "relevant_docs": ["docs/design/DASHBOARD.md"],
            "depends_on": [dep["id"]],
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Implement endpoint"
    assert data["description"] == "Task API endpoint implementation"
    assert data["milestone_id"] == milestone_id
    assert data["assigned_to"] == "codex1"
    assert data["sequence_order"] == 7
    assert data["github_issues"] == [5]
    assert data["tags"] == ["api", "backend"]
    assert data["relevant_docs"] == ["docs/design/DASHBOARD.md"]
    assert data["depends_on"] == [dep["id"]]


async def test_list_tasks_filters(db_pool, client):
    milestone_id = await _create_milestone(client)
    await client.post("/api/tasks", json={"title": "Open alpha", "tags": ["alpha"]})
    done_task_resp = await client.post(
        "/api/tasks",
        json={
            "title": "Done beta",
            "milestone_id": milestone_id,
            "tags": ["beta"],
        },
    )
    done_task_id = done_task_resp.json()["id"]
    await _insert_task_contract(db_pool, task_id=done_task_id)
    await _insert_task_evidence(
        db_pool,
        task_id=done_task_id,
        artifact_type="red_run",
        artifact_hash_sha256="1" * 64,
        captured_by="codex1",
        metadata={"failing_tests": ["tests/test_web_tasks.py::test_list_tasks_filters"]},
    )
    await _insert_task_evidence(
        db_pool,
        task_id=done_task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="2" * 64,
        captured_by="codex1",
        metadata={"changed_files": ["coordinator/web/routes/tasks.py"]},
    )
    await _insert_task_evidence(
        db_pool,
        task_id=done_task_id,
        artifact_type="green_run",
        artifact_hash_sha256="3" * 64,
        captured_by="codex1",
        metadata={
            "command": "pytest tests/test_web_tasks.py -k claim",
            "passed": True,
        },
    )
    await _insert_task_evidence(
        db_pool,
        task_id=done_task_id,
        artifact_type="review_output",
        artifact_hash_sha256="4" * 64,
        captured_by="claude",
        metadata={"author": "codex1", "reviewer": "claude"},
    )
    await _insert_task_evidence(
        db_pool,
        task_id=done_task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="5" * 64,
        captured_by="codex1",
        metadata={
            "what_changed": "Updated task route.",
            "why_changed": "Need filter coverage.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green_run.json"],
            "next_actions": ["Run companion review"],
        },
    )
    await client.patch(
        f"/api/tasks/{done_task_id}",
        json={"status": "done", "assigned_to": "codex1"},
    )

    by_status = await client.get("/api/tasks", params={"status": "done"})
    by_assignee = await client.get("/api/tasks", params={"assignee": "codex1"})
    by_milestone = await client.get("/api/tasks", params={"milestone_id": milestone_id})
    by_tag = await client.get("/api/tasks", params={"tag": "beta"})

    assert by_status.status_code == 200
    assert [t["title"] for t in by_status.json()] == ["Done beta"]
    assert [t["title"] for t in by_assignee.json()] == ["Done beta"]
    assert [t["title"] for t in by_milestone.json()] == ["Done beta"]
    assert [t["title"] for t in by_tag.json()] == ["Done beta"]


async def test_get_task_full_includes_notes_and_pending_clarifications(db_pool, client):
    task = await _create_task(client, "Inspect detail")
    note_resp = await client.post(
        f"/api/tasks/{task['id']}/notes",
        json={"author": "codex1", "content": "Started work"},
    )
    await _insert_clarification(
        db_pool,
        task_id=task["id"],
        asked_by="scott",
        question="Need a route map?",
        status="pending",
    )
    await _insert_clarification(
        db_pool,
        task_id=task["id"],
        asked_by="scott",
        question="Already resolved",
        answer="yes",
        status="answered",
    )

    resp = await client.get(f"/api/tasks/{task['id']}")

    assert note_resp.status_code == 201
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task["id"]
    assert len(data["notes"]) == 1
    assert data["notes"][0]["author"] == "codex1"
    assert data["pending_clarifications"] == [
        {
            "id": data["pending_clarifications"][0]["id"],
            "question": "Need a route map?",
            "status": "pending",
        }
    ]


async def test_patch_task_updates_fields(db_pool, client):
    task = await _create_task(client, "Patch me")

    resp = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"status": "in_progress", "assigned_to": "codex1"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "in_progress"
    assert data["assigned_to"] == "codex1"


async def test_claim_and_release_task(db_pool, client):
    task = await _create_task(client, "Claim me")
    await _insert_task_contract(db_pool, task_id=task["id"])

    claim_resp = await client.post(
        f"/api/tasks/{task['id']}/claim",
        json={"assigned_to": "codex1"},
    )
    release_resp = await client.post(f"/api/tasks/{task['id']}/release")

    assert claim_resp.status_code == 200
    assert claim_resp.json()["status"] == "in_progress"
    assert claim_resp.json()["assigned_to"] == "codex1"
    assert release_resp.status_code == 200
    assert release_resp.json()["status"] == "open"
    assert release_resp.json()["assigned_to"] is None


async def test_add_note(db_pool, client):
    task = await _create_task(client, "Note me")

    resp = await client.post(
        f"/api/tasks/{task['id']}/notes",
        json={"author": "codex1", "content": "Starting task"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["task_id"] == task["id"]
    assert data["author"] == "codex1"
    assert data["content"] == "Starting task"


async def test_get_task_not_found_returns_404_error(db_pool, client):
    resp = await client.get("/api/tasks/9999")

    assert resp.status_code == 404
    assert resp.json()["error"] == "Task 9999 not found"


async def test_claim_task_invalid_state_returns_409_error(db_pool, client):
    task = await _create_task(client, "Already in progress")
    await _insert_task_contract(db_pool, task_id=task["id"])
    await client.post(f"/api/tasks/{task['id']}/claim", json={"assigned_to": "codex1"})

    resp = await client.post(
        f"/api/tasks/{task['id']}/claim",
        json={"assigned_to": "codex1"},
    )

    assert resp.status_code == 409
    assert "not open" in resp.json()["error"]


async def test_claim_task_missing_contract_returns_409_error(db_pool, client):
    task = await _create_task(client, "Missing contract")

    resp = await client.post(
        f"/api/tasks/{task['id']}/claim",
        json={"assigned_to": "codex1"},
    )

    assert resp.status_code == 409
    assert "missing required task contract" in resp.json()["error"]


async def test_invalid_task_status_returns_422_error(db_pool, client):
    task = await _create_task(client, "Bad status")

    patch_resp = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"status": "unknown"},
    )
    list_resp = await client.get("/api/tasks", params={"status": "unknown"})

    assert patch_resp.status_code == 422
    assert "Invalid status" in patch_resp.json()["error"]
    assert list_resp.status_code == 422
    assert "Invalid status" in list_resp.json()["error"]


async def test_create_task_invalid_milestone_returns_422_error(db_pool, client):
    resp = await client.post(
        "/api/tasks",
        json={"title": "Invalid relation", "milestone_id": 9999},
    )

    assert resp.status_code == 422
    assert "Milestone 9999 not found" in resp.json()["error"]

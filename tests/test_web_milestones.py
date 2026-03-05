import pytest
from httpx import ASGITransport, AsyncClient

from coordinator.web.app import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_project(client, name="TestProject") -> int:
    resp = await client.post("/api/projects", json={"name": name})
    return resp.json()["id"]


async def test_list_milestones_empty(db_pool, client):
    resp = await client.get("/api/milestones")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_milestone_minimal(db_pool, client):
    resp = await client.post("/api/milestones", json={"name": "Planning"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Planning"
    assert data["description"] is None
    assert data["priority"] == 0
    assert data["status"] == "active"
    assert data["project_id"] is None
    assert data["task_counts"] == {"open": 0, "in_progress": 0, "done": 0, "blocked": 0}


async def test_create_milestone_full(db_pool, client):
    project_id = await _create_project(client)

    resp = await client.post(
        "/api/milestones",
        json={
            "name": "Execution",
            "description": "Implementation work",
            "priority": 8,
            "project_id": project_id,
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Execution"
    assert data["description"] == "Implementation work"
    assert data["priority"] == 8
    assert data["project_id"] == project_id
    assert data["project_name"] == "TestProject"


async def test_create_milestone_invalid_project(db_pool, client):
    resp = await client.post(
        "/api/milestones",
        json={"name": "Bad", "project_id": 9999},
    )

    assert resp.status_code == 400


async def test_list_milestones_filter_by_status(db_pool, client):
    await client.post("/api/milestones", json={"name": "Active"})
    create_resp = await client.post("/api/milestones", json={"name": "ToDone"})
    milestone_id = create_resp.json()["id"]
    await client.patch(f"/api/milestones/{milestone_id}", json={"status": "done"})

    resp = await client.get("/api/milestones", params={"status": "active"})

    assert resp.status_code == 200
    names = [m["name"] for m in resp.json()]
    assert names == ["Active"]


async def test_list_milestones_filter_by_project(db_pool, client):
    project_id = await _create_project(client)
    await client.post(
        "/api/milestones",
        json={"name": "InProject", "project_id": project_id},
    )
    await client.post("/api/milestones", json={"name": "Orphan"})

    resp = await client.get("/api/milestones", params={"project_id": project_id})

    assert resp.status_code == 200
    names = [m["name"] for m in resp.json()]
    assert names == ["InProject"]


async def test_list_milestones_ordered_by_priority(db_pool, client):
    await client.post("/api/milestones", json={"name": "Low", "priority": 1})
    await client.post("/api/milestones", json={"name": "High", "priority": 9})
    await client.post("/api/milestones", json={"name": "Mid", "priority": 4})

    resp = await client.get("/api/milestones")

    names = [m["name"] for m in resp.json()]
    assert names == ["High", "Mid", "Low"]


async def test_update_milestone(db_pool, client):
    create_resp = await client.post(
        "/api/milestones",
        json={"name": "Old", "priority": 1},
    )
    milestone_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/milestones/{milestone_id}",
        json={"name": "New", "priority": 7, "status": "done"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New"
    assert data["priority"] == 7
    assert data["status"] == "done"


async def test_update_milestone_not_found(db_pool, client):
    resp = await client.patch("/api/milestones/9999", json={"name": "Nope"})

    assert resp.status_code == 404

import pytest
from httpx import ASGITransport, AsyncClient

from coordinator.web.app import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_projects_empty(db_pool, client):
    resp = await client.get("/api/projects")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_project_minimal(db_pool, client):
    resp = await client.post("/api/projects", json={"name": "GLADyS"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "GLADyS"
    assert data["description"] is None
    assert data["status"] == "active"
    assert data["milestone_count"] == 0
    assert data["task_counts"] == {"open": 0, "in_progress": 0, "blocked": 0, "done": 0}


async def test_create_project_full(db_pool, client):
    resp = await client.post(
        "/api/projects",
        json={"name": "the-hive", "description": "Work coordination"},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "the-hive"
    assert data["description"] == "Work coordination"


async def test_list_projects_returns_created(db_pool, client):
    await client.post("/api/projects", json={"name": "Alpha"})
    await client.post("/api/projects", json={"name": "Zebra"})

    resp = await client.get("/api/projects")

    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert names == ["Alpha", "Zebra"]


async def test_list_projects_filter_by_status(db_pool, client):
    await client.post("/api/projects", json={"name": "Active"})
    create_resp = await client.post("/api/projects", json={"name": "ToArchive"})
    project_id = create_resp.json()["id"]
    await client.patch(f"/api/projects/{project_id}", json={"status": "archived"})

    resp = await client.get("/api/projects", params={"status": "active"})

    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert names == ["Active"]


async def test_update_project(db_pool, client):
    create_resp = await client.post("/api/projects", json={"name": "Old"})
    project_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/projects/{project_id}",
        json={"name": "New", "description": "Updated", "status": "archived"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New"
    assert data["description"] == "Updated"
    assert data["status"] == "archived"


async def test_update_project_not_found(db_pool, client):
    resp = await client.patch("/api/projects/9999", json={"name": "Nope"})

    assert resp.status_code == 404


async def test_create_project_missing_name(db_pool, client):
    resp = await client.post("/api/projects", json={})

    assert resp.status_code == 422

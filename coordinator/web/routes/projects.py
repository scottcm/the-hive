from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from coordinator.mcp.tools import projects

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


@router.get("/projects")
async def list_projects(status: str | None = None) -> list[dict[str, Any]]:
    try:
        return await projects.list_projects(status=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate) -> dict[str, Any]:
    return await projects.create_project(
        name=body.name,
        description=body.description,
    )


@router.patch("/projects/{project_id}")
async def update_project(project_id: int, body: ProjectUpdate) -> dict[str, Any]:
    try:
        return await projects.update_project(
            project_id,
            name=body.name,
            description=body.description,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

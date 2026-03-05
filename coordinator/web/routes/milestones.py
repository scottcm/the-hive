from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from coordinator.mcp.tools import milestones

router = APIRouter(tags=["milestones"])


class MilestoneCreate(BaseModel):
    name: str
    description: str | None = None
    priority: int = 0
    project_id: int | None = None


class MilestoneUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    priority: int | None = None
    status: str | None = None


@router.get("/milestones")
async def list_milestones(
    status: str | None = None,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    try:
        return await milestones.list_milestones(status=status, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/milestones", status_code=201)
async def create_milestone(body: MilestoneCreate) -> dict[str, Any]:
    try:
        return await milestones.create_milestone(
            name=body.name,
            description=body.description,
            priority=body.priority,
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/milestones/{milestone_id}")
async def update_milestone(milestone_id: int, body: MilestoneUpdate) -> dict[str, Any]:
    try:
        return await milestones.update_milestone(
            milestone_id,
            name=body.name,
            description=body.description,
            priority=body.priority,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

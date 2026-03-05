from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from coordinator.mcp.tools import notes, tasks

router = APIRouter(tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    milestone_id: int | None = None
    assigned_to: str | None = None
    sequence_order: int = 0
    github_issues: list[int] | None = None
    tags: list[str] | None = None
    relevant_docs: list[str] | None = None
    depends_on: list[int] | None = None


class TaskUpdate(BaseModel):
    status: str | None = None
    assigned_to: str | None = None


class TaskClaim(BaseModel):
    assigned_to: str


class TaskNoteCreate(BaseModel):
    author: str
    content: str


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def _map_value_error(exc: ValueError) -> JSONResponse:
    message = str(exc)
    lowered = message.lower()
    if "invalid status" in lowered:
        return _error(422, message)
    if "not found" in lowered:
        return _error(404, message)
    return _error(409, message)


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    assignee: str | None = None,
    milestone_id: int | None = None,
    tag: str | None = None,
) -> Any:
    try:
        return await tasks.list_tasks(
            assigned_to=assignee,
            status=status,
            milestone_id=milestone_id,
            tag=tag,
        )
    except ValueError as exc:
        return _map_value_error(exc)


@router.post("/tasks", status_code=201)
async def create_task(body: TaskCreate) -> Any:
    try:
        return await tasks.create_task(
            title=body.title,
            description=body.description,
            milestone_id=body.milestone_id,
            assigned_to=body.assigned_to,
            sequence_order=body.sequence_order,
            github_issues=body.github_issues,
            tags=body.tags,
            relevant_docs=body.relevant_docs,
            depends_on=body.depends_on,
        )
    except ValueError as exc:
        message = str(exc)
        if "milestone" in message.lower() and "not found" in message.lower():
            return _error(422, message)
        return _map_value_error(exc)


@router.get("/tasks/{task_id}")
async def get_task(task_id: int) -> Any:
    try:
        return await tasks.get_task(task_id)
    except ValueError as exc:
        return _map_value_error(exc)


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, body: TaskUpdate) -> Any:
    try:
        return await tasks.update_task(
            task_id,
            status=body.status,
            assigned_to=body.assigned_to,
        )
    except ValueError as exc:
        return _map_value_error(exc)


@router.post("/tasks/{task_id}/claim")
async def claim_task(task_id: int, body: TaskClaim) -> Any:
    try:
        return await tasks.claim_task(task_id=task_id, assigned_to=body.assigned_to)
    except ValueError as exc:
        return _map_value_error(exc)


@router.post("/tasks/{task_id}/release")
async def release_task(task_id: int) -> Any:
    try:
        return await tasks.release_task(task_id=task_id)
    except ValueError as exc:
        return _map_value_error(exc)


@router.post("/tasks/{task_id}/notes", status_code=201)
async def add_note(task_id: int, body: TaskNoteCreate) -> Any:
    try:
        return await notes.add_note(
            task_id=task_id,
            author=body.author,
            content=body.content,
        )
    except ValueError as exc:
        return _map_value_error(exc)

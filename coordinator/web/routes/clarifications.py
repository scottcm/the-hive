from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from coordinator.mcp.tools import clarifications

router = APIRouter(tags=["clarifications"])


class ClarificationCreate(BaseModel):
    task_id: int
    asked_by: str
    question: str


class ClarificationAnswer(BaseModel):
    answer: str


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


@router.get("/clarifications")
async def list_clarifications(
    status: str | None = None,
    task_id: int | None = None,
) -> Any:
    try:
        return await clarifications.list_clarifications(status=status, task_id=task_id)
    except ValueError as exc:
        return _map_value_error(exc)


@router.post("/clarifications", status_code=201)
async def create_clarification(body: ClarificationCreate) -> Any:
    try:
        return await clarifications.create_clarification(
            task_id=body.task_id,
            asked_by=body.asked_by,
            question=body.question,
        )
    except ValueError as exc:
        return _map_value_error(exc)


@router.patch("/clarifications/{clarification_id}")
async def answer_clarification(clarification_id: int, body: ClarificationAnswer) -> Any:
    try:
        return await clarifications.answer_clarification(
            clarification_id=clarification_id,
            answer=body.answer,
        )
    except ValueError as exc:
        return _map_value_error(exc)


@router.get("/clarifications/pending-count")
async def get_pending_count(task_id: int | None = None) -> Any:
    try:
        pending = await clarifications.list_clarifications(status="pending", task_id=task_id)
        return {"count": len(pending)}
    except ValueError as exc:
        return _map_value_error(exc)

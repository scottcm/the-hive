from dataclasses import dataclass
from datetime import datetime


@dataclass
class Section:
    id: int
    name: str
    description: str | None
    priority: int
    status: str
    assigned_to: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class Task:
    id: int
    section_id: int | None
    title: str
    description: str | None
    status: str
    priority: int
    sequence_order: int
    assigned_to: str | None
    github_issue: int | None
    relevant_docs: list[str]
    notes: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class Clarification:
    id: int
    task_id: int
    asked_by: str
    question: str
    answer: str | None
    status: str
    created_at: datetime
    answered_at: datetime | None

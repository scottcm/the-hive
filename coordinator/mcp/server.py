import asyncio
import os
import sys
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from coordinator.db.connection import close_pool, get_pool
from coordinator.db.migrate import run_migrations
from coordinator.mcp.tools import (
    clarifications,
    evidence,
    milestones,
    notes,
    projects,
    tasks,
)


@asynccontextmanager
async def lifespan(server):
    pool = await get_pool()
    await run_migrations(pool)
    yield
    await close_pool()


mcp = FastMCP("hive", lifespan=lifespan)

# Task tools
mcp.tool()(tasks.get_task)
mcp.tool()(tasks.get_task_contract)
mcp.tool()(tasks.get_current_task)
mcp.tool()(tasks.get_next_task)
mcp.tool()(tasks.claim_task)
mcp.tool()(tasks.release_task)
mcp.tool()(tasks.list_tasks)
mcp.tool()(tasks.update_task)
mcp.tool()(tasks.create_task)
mcp.tool()(tasks.set_task_contract)
mcp.tool()(tasks.create_task_override)
mcp.tool()(tasks.list_task_overrides)

# Note tools (1)
mcp.tool()(notes.add_note)

# Evidence tools (2)
mcp.tool()(evidence.record_task_evidence)
mcp.tool()(evidence.list_task_evidence)

# Project tools (3)
mcp.tool()(projects.list_projects)
mcp.tool()(projects.create_project)
mcp.tool()(projects.update_project)

# Milestone tools (3)
mcp.tool()(milestones.list_milestones)
mcp.tool()(milestones.create_milestone)
mcp.tool()(milestones.update_milestone)

# Clarification tools (3)
mcp.tool()(clarifications.create_clarification)
mcp.tool()(clarifications.answer_clarification)
mcp.tool()(clarifications.list_clarifications)


def _ensure_compatible_event_loop_policy() -> None:
    if (
        sys.platform.startswith("win")
        and hasattr(asyncio, "WindowsSelectorEventLoopPolicy")
    ):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    transport = os.getenv("HIVE_TRANSPORT", "stdio")
    _ensure_compatible_event_loop_policy()
    mcp.run(transport=transport)

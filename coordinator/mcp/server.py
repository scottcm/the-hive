import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from coordinator.db.connection import close_pool, get_pool
from coordinator.db.migrate import run_migrations
from coordinator.mcp.tools import clarifications, notes, sections, tasks


@asynccontextmanager
async def lifespan(server):
    pool = await get_pool()
    await run_migrations(pool)
    yield
    await close_pool()


mcp = FastMCP("hive", lifespan=lifespan)

# Task tools (7)
mcp.tool()(tasks.get_current_task)
mcp.tool()(tasks.get_next_task)
mcp.tool()(tasks.claim_task)
mcp.tool()(tasks.release_task)
mcp.tool()(tasks.list_tasks)
mcp.tool()(tasks.update_task)
mcp.tool()(tasks.create_task)

# Note tools (1)
mcp.tool()(notes.add_note)

# Section tools (3)
mcp.tool()(sections.list_sections)
mcp.tool()(sections.create_section)
mcp.tool()(sections.update_section)

# Clarification tools (3)
mcp.tool()(clarifications.create_clarification)
mcp.tool()(clarifications.answer_clarification)
mcp.tool()(clarifications.list_clarifications)

if __name__ == "__main__":
    transport = os.getenv("HIVE_TRANSPORT", "stdio")
    mcp.run(transport=transport)

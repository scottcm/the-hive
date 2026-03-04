"""Seed the hive with dashboard project, milestones, and tasks.

Run: python scripts/seed_dashboard_tasks.py

Requires HIVE_DB_URL env var (or .env file).
"""

import asyncio
import selectors

from dotenv import load_dotenv

load_dotenv()

from coordinator.db.connection import close_pool, get_pool
from coordinator.db.migrate import run_migrations
from coordinator.mcp.tools import milestones, projects, tasks


async def main():
    pool = await get_pool()
    await run_migrations(pool)

    # 1. Create project
    project = await projects.create_project(
        "the-hive",
        description="Shared work coordination system for developers and AI agents",
    )
    pid = project["id"]
    print(f"Project: the-hive (id={pid})")

    # 2. Create milestones
    m_backend = await milestones.create_milestone(
        "API Backend",
        description="FastAPI REST API serving project, milestone, task, and clarification endpoints",
        priority=10,
        project_id=pid,
    )
    m_frontend = await milestones.create_milestone(
        "Dashboard Frontend",
        description="Svelte SPA providing board view, task detail, and project management UI",
        priority=5,
        project_id=pid,
    )
    print(f"Milestone: API Backend (id={m_backend['id']})")
    print(f"Milestone: Dashboard Frontend (id={m_frontend['id']})")

    # 3. Create tasks (backend)
    t1 = await tasks.create_task(
        "FastAPI scaffold + project/milestone API",
        description=(
            "Set up FastAPI app with lifespan (DB pool), project CRUD endpoints, "
            "milestone CRUD endpoints, static file serving placeholder, and tests. "
            "Web routes call coordinator.mcp.tools.* functions directly — no SQL duplication."
        ),
        milestone_id=m_backend["id"],
        sequence_order=1,
        github_issues=[4],
        tags=["api", "backend"],
        relevant_docs=[
            "docs/design/DASHBOARD.md",
            "docs/design/COORDINATOR.md",
        ],
    )
    print(f"Task: {t1['title']} (id={t1['id']})")

    t2 = await tasks.create_task(
        "Task API endpoints",
        description=(
            "Task CRUD endpoints including claim/release, note creation, "
            "full task detail (notes + clarifications), tag filtering. "
            "Reuse coordinator.mcp.tools.tasks."
        ),
        milestone_id=m_backend["id"],
        sequence_order=2,
        github_issues=[5],
        tags=["api", "backend"],
        relevant_docs=[
            "docs/design/DASHBOARD.md",
            "docs/design/COORDINATOR.md",
        ],
        depends_on=[t1["id"]],
    )
    print(f"Task: {t2['title']} (id={t2['id']}) depends_on=[{t1['id']}]")

    t3 = await tasks.create_task(
        "Clarification API endpoints",
        description=(
            "Clarification CRUD and answer endpoints with auto-unblock logic. "
            "Pending clarification count for dashboard banner. "
            "Reuse coordinator.mcp.tools.clarifications."
        ),
        milestone_id=m_backend["id"],
        sequence_order=3,
        github_issues=[6],
        tags=["api", "backend"],
        relevant_docs=[
            "docs/design/DASHBOARD.md",
            "docs/design/COORDINATOR.md",
        ],
        depends_on=[t1["id"]],
    )
    print(f"Task: {t3['title']} (id={t3['id']}) depends_on=[{t1['id']}]")

    # 4. Create tasks (frontend)
    t4 = await tasks.create_task(
        "Svelte scaffold + board view",
        description=(
            "Svelte project setup (Vite), project selector dropdown, "
            "board view with collapsible milestone groups, task cards, "
            "filter bar (status, assignee, tag), clarification banner."
        ),
        milestone_id=m_frontend["id"],
        sequence_order=1,
        github_issues=[7],
        tags=["frontend", "dashboard"],
        relevant_docs=[
            "docs/design/DASHBOARD.md",
            "mockups/board.html",
        ],
        depends_on=[t1["id"], t2["id"]],
    )
    print(f"Task: {t4['title']} (id={t4['id']}) depends_on=[{t1['id']}, {t2['id']}]")

    t5 = await tasks.create_task(
        "Task detail view",
        description=(
            "Task detail component with Context/Activity tabs. "
            "Context: description, docs, GitHub section. "
            "Activity: clarifications (read + answer), notes (read + add). "
            "Sidebar with editable fields. Dependency display (blocked by / blocks)."
        ),
        milestone_id=m_frontend["id"],
        sequence_order=2,
        github_issues=[8],
        tags=["frontend", "dashboard"],
        relevant_docs=[
            "docs/design/DASHBOARD.md",
            "mockups/task-detail.html",
        ],
        depends_on=[t2["id"], t3["id"]],
    )
    print(f"Task: {t5['title']} (id={t5['id']}) depends_on=[{t2['id']}, {t3['id']}]")

    t6 = await tasks.create_task(
        "GitHub integration",
        description=(
            "Backend proxy endpoint for closing issues (keeps tokens server-side). "
            "Close issue button on task detail. Live issue/PR status. CI status display."
        ),
        milestone_id=m_frontend["id"],
        sequence_order=3,
        github_issues=[9],
        tags=["frontend", "github"],
        relevant_docs=[
            "docs/design/DASHBOARD.md",
        ],
        depends_on=[t5["id"]],
    )
    print(f"Task: {t6['title']} (id={t6['id']}) depends_on=[{t5['id']}]")

    # Summary
    print("\n--- Dependency graph ---")
    print(f"T{t1['id']}: FastAPI scaffold (no deps — start here)")
    print(f"T{t2['id']}: Task API → depends on T{t1['id']}")
    print(f"T{t3['id']}: Clarification API → depends on T{t1['id']}  (parallel with T{t2['id']})")
    print(f"T{t4['id']}: Board view → depends on T{t1['id']}, T{t2['id']}")
    print(f"T{t5['id']}: Task detail → depends on T{t2['id']}, T{t3['id']}")
    print(f"T{t6['id']}: GitHub integration → depends on T{t5['id']}")

    await close_pool()


if __name__ == "__main__":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()

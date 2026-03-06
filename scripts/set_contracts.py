"""One-shot script to set reliability contracts on active tasks (Task 15 migration)."""
import asyncio
import selectors
import sys

# Must set SelectorEventLoop on Windows before any psycopg pool usage
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from coordinator.mcp.tools import tasks


async def main() -> None:
    contracts = [
        dict(
            task_id=5,
            allowed_paths=["dashboard/**"],
            forbidden_paths=[],
            dependencies=[2, 3],
            required_tests={
                "red": ["cd dashboard && npx vitest run"],
                "green": ["cd dashboard && npx vitest run"],
            },
            review_policy={"min_reviews": 1, "independent_required": True},
            handoff_template="v1_task_handoff",
        ),
        dict(
            task_id=6,
            allowed_paths=["dashboard/**", "coordinator/web/**", "tests/**"],
            forbidden_paths=[],
            dependencies=[5],
            required_tests={
                "red": [
                    "cd dashboard && npx vitest run",
                    "python -m pytest tests/test_web_tasks.py -v",
                ],
                "green": [
                    "cd dashboard && npx vitest run",
                    "python -m pytest tests/ -v",
                ],
            },
            review_policy={"min_reviews": 1, "independent_required": True},
            handoff_template="v1_task_handoff",
        ),
        dict(
            task_id=8,
            allowed_paths=["dashboard/**"],
            forbidden_paths=[],
            dependencies=[4],
            required_tests={
                "red": ["cd dashboard && npx vitest run"],
                "green": ["cd dashboard && npx vitest run"],
            },
            review_policy={"min_reviews": 1, "independent_required": True},
            handoff_template="v1_task_handoff",
        ),
        dict(
            task_id=22,
            allowed_paths=["coordinator/**", "tests/**"],
            forbidden_paths=[],
            dependencies=[12],
            required_tests={
                "red": ["python -m pytest tests/test_mcp_tasks.py -k override -v"],
                "green": [
                    "python -m pytest tests/test_mcp_tasks.py -k override -v",
                    "python -m pytest tests/ -v",
                ],
            },
            review_policy={"min_reviews": 1, "independent_required": True},
            handoff_template="v1_task_handoff",
        ),
        # Task 15 is a meta/ops task — no code files to scope-lock or TDD.
        # G1 and G2 require waivers; green test is full suite passing.
        dict(
            task_id=15,
            allowed_paths=[],
            forbidden_paths=[],
            dependencies=[13, 14],
            required_tests={
                "red": ["# ops task — no automated RED; verification via API spot-checks"],
                "green": ["python -m pytest tests/ -v"],
            },
            review_policy={"min_reviews": 1, "independent_required": True},
            handoff_template="v1_task_handoff",
        ),
    ]

    for c in contracts:
        await tasks.set_task_contract(**c)
        print(f"Task {c['task_id']} contract set")


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )

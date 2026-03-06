import asyncio

import pytest

from coordinator.mcp import server


@pytest.fixture(autouse=True)
async def clean_db():
    yield


def test_ensure_compatible_event_loop_policy_sets_selector_on_windows(monkeypatch):
    if not hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        monkeypatch.setattr(server.sys, "platform", "linux")
        assert server._ensure_compatible_event_loop_policy() is None
        return

    monkeypatch.setattr(server.sys, "platform", "win32")

    class MarkerPolicy(asyncio.DefaultEventLoopPolicy):
        pass

    marker = MarkerPolicy()
    monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", lambda: marker)

    server._ensure_compatible_event_loop_policy()

    assert asyncio.get_event_loop_policy() is marker

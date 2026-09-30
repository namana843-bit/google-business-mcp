"""
Tests for high-level sequence executor (browser_execute).
"""

import pytest
from browser_mcp.tools.browser import browser_execute


@pytest.mark.asyncio
async def test_execute_success_sequence(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)

    steps = [
        {"action": "navigate", "url": test_site_url},
        {
            "action": "fill",
            "selector": {"type": "label", "value": "Search Query"},
            "value": "Sequential execution test",
        },
        {
            "action": "click",
            "selector": {"type": "role", "value": "button", "name": "Submit Form"},
        },
    ]

    res = await browser_execute(manager, steps=steps)
    assert res.success is True
    assert res.data["completed_steps"] == 3

    # Verify form was submitted
    status_text = await manager.get_text(selector="#form-status")
    assert "Submitted: Sequential execution test" in status_text.data["text"]

    await manager.close()


@pytest.mark.asyncio
async def test_execute_failure_stops_with_screenshot(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)

    steps = [
        {"action": "navigate", "url": test_site_url},
        {
            "action": "click",
            "selector": "#non-existent-button-xyz",
        },
        {
            "action": "fill",
            "selector": "#user-bio",
            "value": "Should not reach here",
        },
    ]

    res = await browser_execute(manager, steps=steps)
    assert res.success is False
    assert res.data["step"] == 2
    assert res.data["completed_steps"] == 1
    assert res.data["screenshot_available"] is True
    assert res.screenshot is not None

    # Step 3 must not have executed
    bio_text = await manager.get_text(selector="#user-bio")
    assert "Should not reach here" not in bio_text.data["text"]

    await manager.close()

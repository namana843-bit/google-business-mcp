"""
Tests for screenshot capture and element screenshots.
"""

import base64
import pytest


@pytest.mark.asyncio
async def test_full_page_and_element_screenshot(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # 1. Full page screenshot
    full_ss = await manager.screenshot(full_page=True)
    assert full_ss.success is True
    assert full_ss.screenshot is not None
    # Validate base64
    decoded = base64.b64decode(full_ss.screenshot)
    assert len(decoded) > 1000

    # 2. Targeted element screenshot
    elem_ss = await manager.screenshot(selector="#reviews-section")
    assert elem_ss.success is True
    assert elem_ss.screenshot is not None
    decoded_elem = base64.b64decode(elem_ss.screenshot)
    assert len(decoded_elem) > 500

    await manager.close()

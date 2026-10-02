"""
Tests for browser user interaction tools (click, fill, type, check, select, scroll).
"""

import pytest
from browser_mcp.models.schemas import ElementSelector, SelectorType


@pytest.mark.asyncio
async def test_form_interaction_flow(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # 1. Fill search input by label
    label_sel = ElementSelector(type=SelectorType.LABEL, value="Search Query")
    fill_res = await manager.fill(selector=label_sel, value="Autonomous Agent")
    assert fill_res.success is True

    # 2. Type into textarea by CSS selector
    type_res = await manager.type_text(selector="#user-bio", text="Antigravity Test Agent")
    assert type_res.success is True

    # 3. Select country dropdown
    sel_res = await manager.select_option(selector="#country-select", value="CA")
    assert sel_res.success is True

    # 4. Check checkbox
    check_res = await manager.check(selector="#terms-check")
    assert check_res.success is True

    # 5. Click counter button
    click_res = await manager.click(selector="#counter-btn")
    assert click_res.success is True

    # Verify counter text changed
    btn_text = await manager.get_text(selector="#counter-btn")
    assert "Clicked 1" in btn_text.data["text"]

    # 6. Submit form and verify submission text
    submit_sel = ElementSelector(type=SelectorType.ROLE, value="button", name="Submit Form")
    await manager.click(selector=submit_sel)

    status_text = await manager.get_text(selector="#form-status")
    assert "Submitted: Autonomous Agent" in status_text.data["text"]

    await manager.close()


@pytest.mark.asyncio
async def test_scroll_and_hover(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    hover_res = await manager.hover(selector="#submit-btn")
    assert hover_res.success is True

    scroll_res = await manager.scroll(direction="down", amount=300)
    assert scroll_res.success is True

    await manager.close()

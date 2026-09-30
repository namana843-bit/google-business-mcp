"""
Tests for page navigation and DOM inspection tools.
"""

import pytest
from browser_mcp.models.schemas import ElementSelector, SelectorType


@pytest.mark.asyncio
async def test_navigation_and_url_title(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)

    nav_res = await manager.navigate(test_site_url)
    assert nav_res.success is True

    url_res = await manager.get_url()
    assert "index.html" in url_res.url

    title_res = await manager.get_title()
    assert title_res.title == "Test Playground - Universal Browser MCP"

    # Reload
    reload_res = await manager.reload()
    assert reload_res.success is True

    await manager.close()


@pytest.mark.asyncio
async def test_text_and_html_extraction(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # Page text
    text_res = await manager.get_text()
    assert text_res.success is True
    assert "Local Test Suite Dashboard" in text_res.data["text"]

    # Element text by CSS selector
    el_text_res = await manager.get_text(selector="#description")
    assert el_text_res.success is True
    assert "Testing ground for generic browser automation tools." in el_text_res.data["text"]

    # HTML extraction
    html_res = await manager.get_html(selector="h1")
    assert html_res.success is True
    assert "Local Test Suite Dashboard" in html_res.data["html"]

    # Links extraction
    links_res = await manager.get_links()
    assert links_res.success is True
    hrefs = [l["href"] for l in links_res.data["links"]]
    assert any("login.html" in h for h in hrefs)

    await manager.close()


@pytest.mark.asyncio
async def test_semantic_element_finding(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # 1. Find by role
    find_role = await manager.find(selector_type="role", selector="button", name="Submit Form")
    assert find_role.success is True
    assert find_role.data["found"] is True
    assert find_role.data["tag"] == "button"
    assert find_role.data["visible"] is True
    assert find_role.data["enabled"] is True

    # 2. Find by text
    find_text = await manager.find(selector_type="text", selector="Alice Walker")
    assert find_text.success is True
    assert find_text.data["found"] is True
    assert "Alice Walker" in find_text.data["text"]

    # 3. Find by label
    find_label = await manager.find(selector_type="label", selector="Search Query")
    assert find_label.success is True
    assert find_label.data["found"] is True
    assert find_label.data["tag"] == "input"

    # 4. Find by placeholder
    find_ph = await manager.find(selector_type="placeholder", selector="Type query here...")
    assert find_ph.success is True
    assert find_ph.data["found"] is True

    # 5. Non-existent element
    find_missing = await manager.find(selector_type="css", selector="#non-existent-id-999")
    assert find_missing.success is False
    assert find_missing.data["found"] is False

    await manager.close()

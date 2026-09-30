"""
Tests for browser lifecycle, persistent profiles, and tab management.
"""

import pytest
from browser_mcp.models.schemas import ActionResult


@pytest.mark.asyncio
async def test_browser_launch_and_close(temp_env):
    manager = temp_env["manager"]

    # Initial status
    status = await manager.status()
    assert not status.running

    # Launch browser
    res = await manager.launch(profile="test-profile", headless=True)
    assert res.success is True
    assert manager.is_running is True

    # Status check
    status = await manager.status()
    assert status.running is True
    assert status.profile == "test-profile"
    assert status.page_count == 1

    # Close browser
    close_res = await manager.close()
    assert close_res.success is True
    assert manager.is_running is False


@pytest.mark.asyncio
async def test_persistent_profile_creation(temp_env):
    manager = temp_env["manager"]
    pm = temp_env["pm"]

    # Launch two distinct profiles sequentially
    await manager.launch(profile="profile-alpha", headless=True)
    await manager.close()

    await manager.launch(profile="profile-beta", headless=True)
    await manager.close()

    profiles = pm.list_profiles()
    assert "profile-alpha" in profiles
    assert "profile-beta" in profiles


@pytest.mark.asyncio
async def test_tab_management(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(profile="tabs-profile", headless=True)

    # Initial page
    pages = await manager.list_pages()
    assert len(pages) == 1

    # Open a new tab
    new_page_res = await manager.new_page(url=test_site_url)
    assert new_page_res.success is True

    pages = await manager.list_pages()
    assert len(pages) == 2
    assert pages[1].is_active is True

    # Switch back to first page
    switch_res = await manager.switch_page(0)
    assert switch_res.success is True
    pages = await manager.list_pages()
    assert pages[0].is_active is True

    # Close the second page
    close_page_res = await manager.close_page(1)
    assert close_page_res.success is True
    pages = await manager.list_pages()
    assert len(pages) == 1

    await manager.close()


@pytest.mark.asyncio
async def test_custom_profile_and_spaces(temp_env):
    pm = temp_env["pm"]
    # Verify profile names with spaces like "Profile 8"
    p8 = pm.get_profile_path("Profile 8")
    assert p8.name == "Profile 8"

    # Verify direct profile path resolution
    direct_pm = temp_env["manager"].profile_manager.__class__(base_dir=str(pm.base_dir))
    direct_pm.direct_profile_path = p8
    resolved = direct_pm.get_profile_path("default")
    assert resolved == p8


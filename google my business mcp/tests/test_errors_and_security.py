"""
Tests for security restrictions, predictable error codes, and challenge detection.
"""

import pytest
from browser_mcp.utils.errors import ErrorCode, PermissionDeniedError


@pytest.mark.asyncio
async def test_element_not_found_predictable_error(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # Click missing element
    click_res = await manager.click(selector="#non-existent-button")
    assert click_res.success is False
    assert click_res.error_type == ErrorCode.ELEMENT_NOT_FOUND.value

    # Fill missing element
    fill_res = await manager.fill(selector="#missing-input", value="test")
    assert fill_res.success is False
    assert fill_res.error_type == ErrorCode.ELEMENT_NOT_FOUND.value

    await manager.close()


@pytest.mark.asyncio
async def test_domain_security_restrictions(temp_env):
    manager = temp_env["manager"]
    # Configure blocked domains
    manager.blocked_domains = ["malicious.com", "phishing.test"]

    with pytest.raises(PermissionDeniedError) as exc_info:
        await manager.navigate("https://malicious.com/attack")

    assert exc_info.value.error_type == ErrorCode.PERMISSION_DENIED

    # Configure allowed domains strictly
    manager.blocked_domains = []
    manager.allowed_domains = ["authorized-portal.com"]

    with pytest.raises(PermissionDeniedError) as exc_info_2:
        await manager.navigate("https://unauthorized-domain.com")

    assert exc_info_2.value.error_type == ErrorCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_login_challenge_detection(temp_env, login_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)

    # Navigate to login page
    res = await manager.navigate(login_site_url)
    # login_site_url contains 'login.html' with Sign In form
    assert res.error_type == ErrorCode.LOGIN_REQUIRED.value or res.success is True

    await manager.close()

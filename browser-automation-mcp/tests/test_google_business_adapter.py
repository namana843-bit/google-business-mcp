"""
Tests for Google Business Profile adapter using local mock site and approval flow.
"""

import pytest
from browser_mcp.sites.google_business import (
    GoogleBusinessAdapter,
    create_google_business_post,
    get_google_business_profile,
    get_google_business_reviews,
    reply_to_google_business_review,
)
from browser_mcp.tools.sessions import (
    browser_approve_action,
    get_approval_controller,
)
from browser_mcp.utils.errors import ApprovalRequiredError


@pytest.mark.asyncio
async def test_google_business_adapter_interface(temp_env):
    adapter = GoogleBusinessAdapter()
    assert adapter.name == "google_business"
    assert "business.google.com" in adapter.allowed_domains


@pytest.mark.asyncio
async def test_google_business_profile_extraction_mock(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # Extract profile from mock test site
    res = await get_google_business_profile(manager)
    assert res.success is True
    assert res.data["name"] == "Acme Automation Studio"
    assert res.data["category"] == "Software Company"
    assert "123 Tech Boulevard" in res.data["address"]
    assert "+1-800-555-0199" in res.data["phone"]

    await manager.close()


@pytest.mark.asyncio
async def test_google_business_reviews_discovery_mock(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # Extract reviews
    res = await get_google_business_reviews(manager)
    assert res.success is True
    reviews = res.data["reviews"]
    assert len(reviews) >= 2
    assert reviews[0]["review_id"] == "rev-101"
    assert reviews[0]["author"] == "Alice Walker"
    assert "Fantastic service" in reviews[0]["content"]

    await manager.close()


@pytest.mark.asyncio
async def test_google_business_reply_with_approval_flow(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # 1. Reply without approval triggers ApprovalRequiredError
    with pytest.raises(ApprovalRequiredError) as exc_info:
        await reply_to_google_business_review(
            manager,
            review_id="rev-101",
            reply_text="Thank you so much Alice!",
        )

    approval_id = exc_info.value.details["approval_id"]
    assert approval_id is not None

    # 2. Operator grants approval
    await browser_approve_action(manager, approval_id=approval_id, approved=True)

    # 3. Reply again with the approval_id -> successfully submits in UI
    res = await reply_to_google_business_review(
        manager,
        review_id="rev-101",
        reply_text="Thank you so much Alice!",
        approval_id=approval_id,
    )
    assert res.success is True
    assert "Successfully submitted reply" in res.message

    await manager.close()


@pytest.mark.asyncio
async def test_google_business_post_with_approval_flow(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    # 1. Attempt post creation without approval -> raises ApprovalRequiredError
    with pytest.raises(ApprovalRequiredError) as exc_info:
        await create_google_business_post(
            manager,
            content="Exciting updates this autumn! Stop by today.",
        )

    approval_id = exc_info.value.details["approval_id"]

    # 2. Approve action
    await browser_approve_action(manager, approval_id=approval_id, approved=True)

    # 3. Create post with approval token -> submits in UI
    res = await create_google_business_post(
        manager,
        content="Exciting updates this autumn! Stop by today.",
        approval_id=approval_id,
    )
    assert res.success is True
    assert "published" in res.message.lower()

    await manager.close()


@pytest.mark.asyncio
async def test_google_business_post_with_media_upload(temp_env, test_site_url, tmp_path):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    test_img = tmp_path / "post_photo.png"
    test_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82")

    with pytest.raises(ApprovalRequiredError) as exc_info:
        await create_google_business_post(
            manager,
            content="Check out our brand new offer!",
            media_path=str(test_img),
        )

    approval_id = exc_info.value.details["approval_id"]
    await browser_approve_action(manager, approval_id=approval_id, approved=True)

    res = await create_google_business_post(
        manager,
        content="Check out our brand new offer!",
        media_path=str(test_img),
        approval_id=approval_id,
    )
    assert res.success is True
    assert res.data["media_path"] == str(test_img)
    assert "published" in res.message.lower()

    await manager.close()

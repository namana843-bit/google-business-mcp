"""Google Business public update/post publishing and deletion."""

import re
from pathlib import Path
from typing import Optional

from playwright.async_api import Locator, Page

from browser_mcp.approvals import get_approval_controller
from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult
from browser_mcp.sites.base import abort_with_screenshot
from browser_mcp.sites.google_business.locators import first_visible
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.utils.logging import get_logger

logger = get_logger("google_business.posts")


def _css_attr_value(value: str) -> str:
    """Escapes a string for safe interpolation inside a single-quoted CSS attribute selector."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


_CREATE_BUTTON_QUERIES = (
    "button:has-text('Add update')",
    "button:has-text('Create post')",
    "div[role='button']:has-text('Add update')",
)

_CONTENT_FIELD_SELECTORS = (
    "div[role='dialog'] textarea",
    "textarea[placeholder*='update' i]",
    "textarea[aria-label*='update' i]",
    "div[contenteditable='true']",
    "textarea",
)

_PUBLISH_SELECTORS = (
    "div[role='dialog'] button:has-text('Post')",
    "div[role='dialog'] button:has-text('Publish')",
    "button:has-text('Publish')",
)

_DELETE_MENU_SELECTORS = (
    "button[aria-label*='More' i]",
    "button[aria-label*='Options' i]",
)

# Only the first 120 characters of a post are shown in the approval prompt;
# enough for a human to recognise it without flooding the approvals list.
_APPROVAL_PREVIEW_CHARS = 120


async def find_create_post_button(page: Page) -> Optional[Locator]:
    """Finds the 'Add update' / 'Create post' control."""
    return await first_visible(
        (
            page.get_by_role("button", name="Add update"),
            page.get_by_role("button", name="Create post"),
            page.get_by_role("button", name="Add update/offer"),
            *(page.locator(q) for q in _CREATE_BUTTON_QUERIES),
        )
    )


async def _attach_media(page: Page, media_path: str) -> None:
    """Uploads a photo to the open post composer.

    Best-effort: a composer that offers no upload affordance is not a reason to
    abandon publishing the text post.
    """
    try:
        direct_input = page.locator("div[role='dialog'] input[type='file'], input[type='file']")
        if await direct_input.count() > 0:
            await direct_input.first.set_input_files(media_path)
            await page.wait_for_timeout(1500)
            return

        photo_button = await first_visible(
            page.locator(sel)
            for sel in (
                "div[role='dialog'] button:has-text('photo')",
                "div[role='dialog'] button:has-text('Photos')",
                "div[role='dialog'] [aria-label*='photo' i]",
            )
        )
        if photo_button is not None:
            async with page.expect_file_chooser(timeout=5000) as chooser_info:
                await photo_button.click()
            await (await chooser_info.value).set_files(media_path)
            await page.wait_for_timeout(1500)
    except Exception as e:
        logger.warning(f"Error attaching media to post: {e}")


async def _apply_cta(page: Page, cta_type: Optional[str], cta_url: Optional[str]) -> None:
    """Sets the optional call-to-action button and destination URL."""
    try:
        if cta_type:
            dropdown = page.locator("div[role='dialog'] [role='combobox'], div[role='dialog'] select")
            if await dropdown.count() > 0:
                await dropdown.first.click()
                option = page.get_by_role("option", name=cta_type)
                if await option.count() > 0:
                    await option.first.click()

        if cta_url:
            url_input = page.locator(
                "div[role='dialog'] input[type='url'], div[role='dialog'] input[placeholder*='http']"
            )
            if await url_input.count() > 0:
                await url_input.first.fill(cta_url)
    except Exception as e:
        logger.debug(f"Optional CTA assignment skipped: {e}")


async def create_google_business_post(
    manager: BrowserManager,
    content: str,
    media_path: Optional[str] = None,
    image_path: Optional[str] = None,
    cta_type: Optional[str] = None,
    cta_url: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> ActionResult:
    """Publishes a public update post, optionally with a photo and a CTA.

    Gated on human approval: the published content is customer-visible.
    """
    attached_media = media_path or image_path
    if attached_media and not Path(attached_media).exists():
        return ActionResult(
            success=False,
            error_type=ErrorCode.INVALID_REQUEST.value,
            message=f"Local media file '{attached_media}' does not exist.",
        )

    get_approval_controller(manager.db).require_approval_if_needed(
        action_type="public_post_create",
        description="Publish public update to Google Business Profile",
        details={
            "content_preview": content[:_APPROVAL_PREVIEW_CHARS],
            "media_path": attached_media,
            "cta_type": cta_type,
            "cta_url": cta_url,
        },
        approval_id=approval_id,
    )

    page = await manager.get_active_page()

    create_button = await find_create_post_button(page)
    if not create_button:
        return await abort_with_screenshot(manager, page, "Could not find 'Add update' / 'Create post' button on page."
        )

    await create_button.click()
    await page.wait_for_timeout(800)

    composer = await first_visible(page.locator(s) for s in _CONTENT_FIELD_SELECTORS)
    if not composer:
        return await abort_with_screenshot(manager, page, "Post content textarea modal did not open.")

    if await composer.get_attribute("contenteditable") == "true":
        await composer.click()
        await composer.press_sequentially(content, delay=10)
    else:
        await composer.fill(content)

    if attached_media:
        await _attach_media(page, attached_media)

    await _apply_cta(page, cta_type, cta_url)

    publish = await first_visible(page.locator(s) for s in _PUBLISH_SELECTORS)
    if not publish:
        return await abort_with_screenshot(manager, page, "Publish button inside post modal not found.")

    await publish.click()
    await page.wait_for_timeout(1500)

    manager.db.log_action(
        "google_business_create_post",
        target_url=page.url,
        profile=manager.active_profile,
        status="SUCCESS",
        details={
            "content_length": len(content),
            "media_path": attached_media,
            "cta_type": cta_type,
        },
    )
    return ActionResult(
        success=True,
        message="Google Business post successfully published.",
        url=page.url,
        title=await page.title(),
        data={
            "content": content,
            "media_path": attached_media,
            "cta_type": cta_type,
            "cta_url": cta_url,
        },
    )


async def create_google_business_post_with_media(
    manager: BrowserManager,
    content: str,
    media_path: str,
    cta_type: Optional[str] = None,
    cta_url: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> ActionResult:
    """Publishes a public update post with an attached image.

    Identical to create_google_business_post with `media_path` set; retained as
    a distinct entry point for callers that require an attachment.
    """
    return await create_google_business_post(
        manager=manager,
        content=content,
        media_path=media_path,
        cta_type=cta_type,
        cta_url=cta_url,
        approval_id=approval_id,
    )


async def delete_google_business_post(
    manager: BrowserManager,
    post_id: str,
    approval_id: Optional[str] = None,
) -> ActionResult:
    """Deletes a public post, gated on human approval.

    The post is resolved by exact identity and the Delete option is scoped to
    that post's own container. A fuzzy page-wide text match could destroy the
    wrong post, which is irreversible.
    """
    get_approval_controller(manager.db).require_approval_if_needed(
        action_type="public_post_delete",
        description=f"Delete public post '{post_id}' from Google Business Profile",
        details={"post_id": post_id},
        approval_id=approval_id,
    )

    page = await manager.get_active_page()
    container = page.locator(f"div[data-post-id='{_css_attr_value(post_id)}']").first
    if await container.count() == 0:
        return await abort_with_screenshot(
            manager,
            page,
            f"Post '{post_id}' not found.",
            error_type=ErrorCode.ELEMENT_NOT_FOUND,
        )

    menu = await first_visible(container.locator(s) for s in _DELETE_MENU_SELECTORS)
    if menu is not None:
        await menu.click()
        await page.wait_for_timeout(300)

    # Prefer this post's own menu; fall back to the page-level menu only when
    # the composer rendered the options menu outside the container.
    delete_option = await first_visible(
        (
            container.locator("div[role='menuitem']:has-text('Delete')"),
            container.locator("button:has-text('Delete')"),
            page.locator("div[role='menu'] div[role='menuitem']:has-text('Delete')"),
        )
    )
    if delete_option is None:
        return await abort_with_screenshot(
            manager,
            page,
            "Delete option not found in post menu.",
            error_type=ErrorCode.ELEMENT_NOT_FOUND,
        )

    await delete_option.click()
    await page.wait_for_timeout(500)

    confirm = await first_visible(
        (page.locator("div[role='dialog'] button:has-text('Delete')"),)
    )
    if confirm is not None:
        await confirm.click()
        await page.wait_for_timeout(1000)

    manager.db.log_action(
        "google_business_delete_post",
        profile=manager.active_profile,
        status="SUCCESS",
        details={"post_id": post_id},
    )
    return ActionResult(
        success=True, message=f"Post '{post_id}' deleted successfully.", url=page.url
    )

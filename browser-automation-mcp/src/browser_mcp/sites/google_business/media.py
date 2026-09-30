"""Google Business photo/media extraction and upload."""

import os
from pathlib import Path
from typing import Optional

from browser_mcp.approvals import get_approval_controller
from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult
from browser_mcp.sites.base import abort_with_screenshot
from browser_mcp.sites.google_business.locators import first_visible
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.utils.logging import get_logger

logger = get_logger("google_business.media")

_MEDIA_IMAGE_SELECTORS = (
    "img[src*='googleusercontent.com']",
    "div[role='img']",
    ".photo-grid img",
)

# Cap per-selector scanning so a photo-heavy page cannot stall the tool.
_MAX_PER_SELECTOR = 30

_ADD_PHOTO_QUERIES = (
    "button:has-text('Add photo')",
    "button:has-text('Add photos')",
    "a[href*='photo']",
)


async def get_google_business_media(manager: BrowserManager) -> ActionResult:
    """Extracts photo URLs currently displayed on the Google Business profile."""
    page = await manager.get_active_page()

    discovered: dict[str, str] = {}
    for selector in _MEDIA_IMAGE_SELECTORS:
        images = page.locator(selector)
        for i in range(min(await images.count(), _MAX_PER_SELECTOR)):
            try:
                image = images.nth(i)
                src = await image.get_attribute("src") or await image.get_attribute("data-src")
                if not src or src.startswith("data:"):
                    continue
                # dict keyed on url so the same photo found by two selectors is
                # reported once.
                discovered.setdefault(src, (await image.get_attribute("alt") or "").strip())
            except Exception as e:
                logger.debug(f"Skipping unreadable media element: {e}")

    media = [{"url": url, "title": title} for url, title in discovered.items()]
    return ActionResult(
        success=True,
        message=f"Discovered {len(media)} media item(s).",
        url=page.url,
        title=await page.title(),
        data={"media": media, "total_found": len(media)},
    )


async def upload_google_business_media(
    manager: BrowserManager,
    file_path: str,
    category: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> ActionResult:
    """Uploads a photo to the Google Business Profile.

    Gated on human approval: an uploaded photo is customer-visible.
    """
    if not Path(file_path).exists():
        return ActionResult(
            success=False,
            error_type=ErrorCode.INVALID_REQUEST.value,
            message=f"Local media file '{file_path}' does not exist.",
        )

    get_approval_controller(manager.db).require_approval_if_needed(
        action_type="media_upload",
        description=(
            f"Upload media file '{os.path.basename(file_path)}' to Google Business Profile"
        ),
        details={"file_path": file_path, "category": category},
        approval_id=approval_id,
    )

    page = await manager.get_active_page()

    add_button = await first_visible(
        (
            page.get_by_role("button", name="Add photo"),
            *(page.locator(q) for q in _ADD_PHOTO_QUERIES),
        )
    )
    if add_button is None:
        return await abort_with_screenshot(
            manager, page, "Could not locate 'Add photo' button on page."
        )

    await add_button.click()
    await page.wait_for_timeout(800)

    file_input = page.locator("input[type='file']")
    if await file_input.count() == 0:
        return await abort_with_screenshot(
            manager,
            page,
            "File upload input not found after clicking Add photo.",
            ErrorCode.ELEMENT_NOT_FOUND,
        )

    await file_input.set_input_files(file_path)
    await page.wait_for_timeout(2000)

    manager.db.log_action(
        "google_business_upload_media",
        target_url=page.url,
        profile=manager.active_profile,
        status="SUCCESS",
        details={"file_name": os.path.basename(file_path), "category": category},
    )
    return ActionResult(
        success=True,
        message=f"Uploaded photo '{os.path.basename(file_path)}' successfully.",
        url=page.url,
        title=await page.title(),
        data={"file_path": file_path, "category": category},
    )

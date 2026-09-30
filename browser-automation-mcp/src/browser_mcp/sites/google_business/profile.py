"""Google Business Profile navigation and profile-data extraction."""

import urllib.parse
from typing import Optional

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult, GoogleBusinessProfile
from browser_mcp.sites.google_business.locators import first_visible_text
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.utils.logging import get_logger

logger = get_logger("google_business.profile")

GBP_DASHBOARD_URL = "https://business.google.com/"

# Google renders the same profile data under different markup in the in-search
# merchant view and the Business Manager dashboard, so each field is looked up
# through an ordered candidate list rather than a single selector.
_NAME_SELECTORS = (
    "[data-attrid='title']",
    "span[data-attrid='title']",
    "h1[data-attrid='title']",
    "div[role='heading'][aria-level='1']",
    ".header-business-name",
    "h1",
)
_CATEGORY_SELECTORS = (
    "[data-attrid='subtitle']",
    "span.category",
    "div[aria-label*='Category']",
    ".business-category",
)
_ADDRESS_SELECTORS = (
    "[data-item-id='address']",
    "button[data-tooltip*='address']",
    "span:has-text('Address:') + span",
    "[aria-label*='Address']",
)
_PHONE_SELECTORS = (
    "[data-item-id*='phone']",
    "button[data-tooltip*='phone']",
    "a[href^='tel:']",
    "[aria-label*='Phone']",
)
_RATING_SELECTORS = (
    "span[aria-label*='stars']",
    "span[aria-label*='star rating']",
    ".rating-number",
    "span.fontDisplayLarge",
)

# A heading this long is a page banner, not a business name.
_MAX_NAME_LENGTH = 100


def _is_login_wall(url: str) -> bool:
    return "accounts.google.com" in url or "signin" in url


async def open_google_business(
    manager: BrowserManager,
    business_name: Optional[str] = None,
    profile: Optional[str] = None,
) -> ActionResult:
    """Navigates to the Google Business dashboard, or to a business search."""
    if not manager.is_running:
        await manager.launch(profile=profile)

    if business_name:
        target = f"https://www.google.com/search?q={urllib.parse.quote(business_name)}"
    else:
        target = GBP_DASHBOARD_URL
    return await manager.navigate(target)


async def _parse_rating(page) -> Optional[float]:
    """Extracts the numeric star rating, ignoring any non-numeric decoration."""
    raw = await first_visible_text(page, _RATING_SELECTORS)
    if not raw:
        return None
    try:
        return float(raw.split()[0])
    except (ValueError, IndexError):
        return None


async def get_google_business_profile(manager: BrowserManager) -> ActionResult:
    """Extracts profile details from the current Google Business page."""
    page = await manager.get_active_page()

    try:
        if _is_login_wall(page.url.lower()):
            return ActionResult(
                success=False,
                error_type=ErrorCode.LOGIN_REQUIRED.value,
                message=(
                    "Google authentication required. Please sign into Google "
                    "in the browser window."
                ),
                url=page.url,
            )

        name = await first_visible_text(page, _NAME_SELECTORS)
        if name and len(name) >= _MAX_NAME_LENGTH:
            name = None

        profile_data = GoogleBusinessProfile(
            name=name or await page.title(),
            category=await first_visible_text(page, _CATEGORY_SELECTORS),
            address=await first_visible_text(page, _ADDRESS_SELECTORS),
            phone=await first_visible_text(page, _PHONE_SELECTORS),
            rating=await _parse_rating(page),
            url=page.url,
        )
        return ActionResult(
            success=True,
            message="Google Business Profile data extracted.",
            url=page.url,
            title=await page.title(),
            data=profile_data.model_dump(),
        )

    except Exception as e:
        logger.error(f"Failed to extract profile: {e}")
        return ActionResult(
            success=False,
            error_type=ErrorCode.UNKNOWN.value,
            message=f"Failed to extract profile: {e}",
            url=page.url,
        )

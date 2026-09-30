"""Google Business account and location discovery.

Scrapes the business.google.com dashboard to enumerate the accounts the signed-in
user manages and the locations under each one.
"""

from typing import Any, Optional

from playwright.async_api import Page

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult
from browser_mcp.sites.google_business.locators import text_or_default
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.utils.logging import get_logger

logger = get_logger("google_business.accounts")

GBP_DASHBOARD_URL = "https://business.google.com/"
GBP_ACCOUNTS_URL = "https://business.google.com/locations"

# Placeholder resource name meaning "whichever account is active in the browser".
SELF_ACCOUNT = "accounts/me"

_LOCATION_CARD_SELECTORS = (
    "div[data-location-id]",
    "div[jsdata*='location']",
    "li[data-location-id]",
    "div.location-list-item",
    "a[href*='/edit/']",
)

_ACCOUNT_SWITCHER_SELECTORS = ("a[href*='account=']", "a[href*='accounts%2F']")

_BUSINESS_NAME_SELECTORS = ("h1", "[data-attrid='title']", ".header-business-name")

# Text extracted from inside a single location card.
_CARD_HEADING_SELECTORS = ("h2", "h3", "[role='heading']", ".location-name", "span.name")
_ADDRESS_SELECTORS = ("[aria-label*='address' i]", ".address", "span.addr")

# Dashboard renders are JS-heavy; a fixed settle beat makes scraping reliable
# without paying for a full network-idle wait on every call.
_SETTLE_MS = 2500


def _clean(text: Optional[str]) -> Optional[str]:
    """Strips text, collapsing empty results to None."""
    if not text:
        return None
    return text.strip() or None


def _digits(fragment: str) -> Optional[str]:
    """Returns the leading run of digits in a fragment, if it is all digits."""
    candidate = fragment.split("?")[0].split("&")[0].split("/")[0]
    return candidate if candidate.isdigit() else None


def _account_from_href(href: str) -> Optional[str]:
    """Extracts an `accounts/<id>` resource name from a switcher link href."""
    for marker in ("accounts%2F", "account=accounts/"):
        if marker in href:
            account_id = _digits(href.split(marker, 1)[1])
            return f"accounts/{account_id}" if account_id else None
    return None


def _resource_name(account_name: str, location_id: Optional[str]) -> Optional[str]:
    """Builds `<account>/locations/<id>`, or None when the account is symbolic."""
    if location_id and account_name != SELF_ACCOUNT:
        return f"{account_name}/locations/{location_id}"
    return None


def _is_login_wall(url: str) -> bool:
    return "accounts.google.com" in url or "signin" in url


async def _ensure_dashboard(manager: BrowserManager) -> Page:
    """Returns a page on the GBP domain, navigating there if necessary."""
    if not manager.is_running:
        await manager.launch()
    page = await manager.get_active_page()
    if "business.google.com" not in page.url.lower():
        await manager.navigate(GBP_DASHBOARD_URL)
        page = await manager.get_active_page()
        await page.wait_for_timeout(2000)
    return page


async def _page_heading(page: Page, default: str) -> str:
    """Returns the first visible heading, falling back to `default`."""
    return await text_or_default(page, _BUSINESS_NAME_SELECTORS, default)



async def _accounts_from_switcher(page: Page) -> list[dict[str, Any]]:
    """Strategy 1: multi-account switcher links embed the account id in the href."""
    accounts: list[dict[str, Any]] = []
    for selector in _ACCOUNT_SWITCHER_SELECTORS:
        links = page.locator(selector)
        for i in range(await links.count()):
            link = links.nth(i)
            href = await link.get_attribute("href") or ""
            label = _clean(await link.text_content())
            account_name = _account_from_href(href)
            if label and account_name:
                accounts.append(
                    {
                        "account_name": account_name,
                        "display_name": label,
                        "url": (
                            f"https://business.google.com{href}"
                            if href.startswith("/")
                            else href
                        ),
                    }
                )
    return accounts


async def _account_from_current_url(page: Page) -> list[dict[str, Any]]:
    """Strategy 2: the account id is already in the current page URL."""
    url = page.url
    if "accounts%2F" not in url:
        return []
    account_id = _digits(url.split("accounts%2F", 1)[1])
    if not account_id:
        return []
    return [
        {
            "account_name": f"accounts/{account_id}",
            "display_name": await _page_heading(page, "My Business"),
            "url": url,
        }
    ]


async def _fallback_account(page: Page) -> list[dict[str, Any]]:
    """Strategy 3: single-account users expose no id, so report the symbolic one."""
    return [
        {
            "account_name": SELF_ACCOUNT,
            "display_name": await _page_heading(page, "My Business Account"),
            "url": page.url,
            "note": (
                "Account ID could not be extracted automatically. Use "
                f"'{SELF_ACCOUNT}' as a placeholder or check the URL manually."
            ),
        }
    ]


async def list_google_business_accounts(manager: BrowserManager) -> ActionResult:
    """Discovers all GBP accounts linked to the signed-in user.

    Accounts are returned as `accounts/<id>` resource names suitable for
    list_google_business_locations.
    """
    try:
        page = await _ensure_dashboard(manager)
        if _is_login_wall(page.url):
            return ActionResult(
                success=False,
                error_type=ErrorCode.LOGIN_REQUIRED.value,
                message=(
                    "Google login required. Please open the browser "
                    "(google_business_open) and sign in first."
                ),
                url=page.url,
            )

        await manager.navigate(GBP_ACCOUNTS_URL)
        page = await manager.get_active_page()
        await page.wait_for_timeout(_SETTLE_MS)

        accounts = (
            await _accounts_from_switcher(page)
            or await _account_from_current_url(page)
            or await _fallback_account(page)
        )
        return ActionResult(
            success=True,
            message=f"Found {len(accounts)} account(s) linked to the signed-in user.",
            url=page.url,
            title=await page.title(),
            data={"accounts": accounts, "total": len(accounts)},
        )

    except Exception as e:
        logger.error(f"list_google_business_accounts failed: {e}")
        return ActionResult(
            success=False,
            error_type=ErrorCode.UNKNOWN.value,
            message=f"Failed to list accounts: {e}",
        )


def _locations_url(account_name: str) -> str:
    """Builds the dashboard URL listing locations for an account."""
    if account_name == SELF_ACCOUNT or not account_name.startswith("accounts/"):
        return GBP_ACCOUNTS_URL
    account_id = account_name.removeprefix("accounts/")
    return f"{GBP_ACCOUNTS_URL}?account=accounts%2F{account_id}"


async def _locations_from_cards(page: Page, account_name: str) -> list[dict[str, Any]]:
    """Strategy 1: one card per location in the locations list."""
    for selector in _LOCATION_CARD_SELECTORS:
        cards = page.locator(selector)
        count = await cards.count()
        if count == 0:
            continue

        locations = []
        for i in range(count):
            card = cards.nth(i)
            location_id = await card.get_attribute("data-location-id")

            if not location_id and selector.startswith("a"):
                # An edit link looks like /edit/accounts/1/locations/456
                href = await card.get_attribute("href") or ""
                if "locations/" in href:
                    location_id = _digits(href.split("locations/", 1)[1])

            locations.append(
                {
                    "location_name": _resource_name(account_name, location_id),
                    "location_id": location_id,
                    "display_name": await _card_heading(card) or f"Location {i + 1}",
                    "address": await _card_heading(card, _ADDRESS_SELECTORS),
                }
            )
        return locations
    return []


async def _card_heading(
    card, selectors: tuple[str, ...] = _CARD_HEADING_SELECTORS
) -> Optional[str]:
    """Returns the first matching text inside a location card."""
    for selector in selectors:
        located = card.locator(selector)
        if await located.count() > 0 and (text := _clean(await located.first.text_content())):
            return text
    return None


async def _fallback_location(page: Page, account_name: str) -> list[dict[str, Any]]:
    """Strategy 2: a single-location account renders no list to scrape."""
    location_id = _digits(page.url.split("locations/", 1)[1]) if "locations/" in page.url else None
    return [
        {
            "location_name": _resource_name(account_name, location_id),
            "location_id": location_id,
            "display_name": await _page_heading(page, "My Location"),
            "address": None,
            "note": (
                "Only one location detected. If location_name is null, open the "
                "specific location's dashboard and call this tool again."
            ),
        }
    ]


async def list_google_business_locations(
    manager: BrowserManager,
    account_name: str,
) -> ActionResult:
    """Lists all locations under a GBP account.

    Returns `accounts/<id>/locations/<id>` resource names usable with
    google_business_get_reviews.
    """
    try:
        page = await _ensure_dashboard(manager)
        if _is_login_wall(page.url):
            return ActionResult(
                success=False,
                error_type=ErrorCode.LOGIN_REQUIRED.value,
                message="Google login required. Call google_business_open first.",
                url=page.url,
            )

        await manager.navigate(_locations_url(account_name))
        page = await manager.get_active_page()
        await page.wait_for_timeout(_SETTLE_MS)

        locations = (
            await _locations_from_cards(page, account_name)
            or await _fallback_location(page, account_name)
        )
        return ActionResult(
            success=True,
            message=f"Found {len(locations)} location(s) under {account_name}.",
            url=page.url,
            title=await page.title(),
            data={
                "locations": locations,
                "account_name": account_name,
                "total": len(locations),
            },
        )

    except Exception as e:
        logger.error(f"list_google_business_locations failed: {e}")
        return ActionResult(
            success=False,
            error_type=ErrorCode.UNKNOWN.value,
            message=f"Failed to list locations: {e}",
        )

"""FastMCP server exposing the generic browser tools and site adapters."""

import argparse
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.browser.pages import parse_selector
from browser_mcp.sites.google_business import (
    create_google_business_post,
    create_google_business_post_with_media,
    delete_google_business_post,
    get_google_business_media,
    get_google_business_profile,
    get_google_business_reviews,
    list_google_business_accounts,
    list_google_business_locations,
    open_google_business,
    reply_to_google_business_review,
    upload_google_business_media,
)
from browser_mcp.tools.browser import (
    browser_close,
    browser_close_page,
    browser_execute,
    browser_launch,
    browser_list_pages,
    browser_new_page,
    browser_status,
    browser_switch_page,
)
from browser_mcp.tools.extraction import (
    browser_find,
    browser_get_html,
    browser_get_links,
    browser_get_text,
    browser_get_title,
    browser_get_url,
)
from browser_mcp.tools.interaction import (
    browser_check,
    browser_click,
    browser_fill,
    browser_hover,
    browser_press,
    browser_scroll,
    browser_select,
    browser_type,
    browser_uncheck,
)
from browser_mcp.tools.navigation import (
    browser_back,
    browser_forward,
    browser_navigate,
    browser_reload,
    browser_wait,
)
from browser_mcp.tools.screenshot import browser_screenshot
from browser_mcp.tools.sessions import (
    browser_approve_action,
    browser_list_profiles,
    browser_pending_approvals,
)
from browser_mcp.utils.errors import BrowserMCPError, ErrorCode
from browser_mcp.utils.logging import get_logger, setup_logging

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if (_PACKAGE_ROOT / ".env").exists():
    load_dotenv(_PACKAGE_ROOT / ".env")
load_dotenv()
logger = get_logger("server")

mcp = FastMCP("browser-automation-mcp")

_manager: Optional[BrowserManager] = None


def get_manager() -> BrowserManager:
    """Returns the process-wide browser manager, creating it on first use."""
    global _manager
    if _manager is None:
        _manager = BrowserManager()
    return _manager


def _payload(result: Any) -> dict[str, Any]:
    """Normalises a tool return value into the MCP response shape."""
    if isinstance(result, BaseModel):
        return result.model_dump()
    if isinstance(result, list):
        return {"success": True, "pages": [p.model_dump() for p in result], "count": len(result)}
    return result


_UNSET = object()


async def _call(
    operation: Callable[..., Awaitable[Any]],
    selector: Any = _UNSET,
    selector_type: str = "css",
    name: Optional[str] = None,
    exact: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Runs a tool operation and converts any failure into a typed response.

    Selectors arrive in several shapes ("Submit", "text=Submit",
    {"type": "text", ...}), so `selector` is normalised here rather than at each
    call site. Parsing deliberately happens inside the guard: a malformed
    selector is a tool error, not a protocol-level crash.

    The error code comes from the exception itself rather than from a per-tool
    guess, so the same failure always reports the same code no matter which
    tool surfaced it, and a caller can branch on `error_type` reliably.
    """
    try:
        if selector is not _UNSET:
            kwargs["selector"] = parse_selector(selector, selector_type, name, exact)
        return _payload(await operation(get_manager(), **kwargs))
    except BrowserMCPError as e:
        return e.to_dict()
    except Exception as e:
        logger.exception(f"Unhandled error in MCP tool {operation.__name__}")
        return {
            "success": False,
            "error_type": ErrorCode.UNKNOWN.value,
            "message": str(e),
        }


# ==========================================
# 1. BROWSER LIFECYCLE
# ==========================================


@mcp.tool(name="browser_launch")
async def tool_browser_launch(
    profile: Optional[str] = None,
    headless: Optional[bool] = None,
    slow_mo: Optional[int] = None,
    executable_path: Optional[str] = None,
    cdp_url: Optional[str] = None,
) -> dict[str, Any]:
    """Launch or connect to a persistent Chromium browser profile.

    Manual logins and cookies persist inside the profile between restarts.
    """
    return await _call(
        browser_launch,
        profile=profile,
        headless=headless,
        slow_mo=slow_mo,
        executable_path=executable_path,
        cdp_url=cdp_url,
    )


@mcp.tool(name="browser_close")
async def tool_browser_close() -> dict[str, Any]:
    """Close the active Chromium session and save cookies/state to the profile."""
    return await _call(browser_close)


@mcp.tool(name="browser_status")
async def tool_browser_status() -> dict[str, Any]:
    """Retrieve operational status, active profile, open tabs, and current page."""
    return await _call(browser_status)


@mcp.tool(name="browser_list_pages")
async def tool_browser_list_pages() -> dict[str, Any]:
    """List all currently open tabs/pages in the browser."""
    return await _call(browser_list_pages)


@mcp.tool(name="browser_new_page")
async def tool_browser_new_page(url: Optional[str] = None) -> dict[str, Any]:
    """Open a new browser tab and optionally navigate to the given URL."""
    return await _call(browser_new_page, url=url)


@mcp.tool(name="browser_switch_page")
async def tool_browser_switch_page(index: int) -> dict[str, Any]:
    """Switch active tab focus to the page at the given index (0-based)."""
    return await _call(browser_switch_page, index=index)


@mcp.tool(name="browser_close_page")
async def tool_browser_close_page(index: Optional[int] = None) -> dict[str, Any]:
    """Close the tab at the given index, or the active tab if omitted."""
    return await _call(browser_close_page, index=index)


# ==========================================
# 2. NAVIGATION
# ==========================================


@mcp.tool(name="browser_navigate")
async def tool_browser_navigate(url: str, wait_until: str = "load") -> dict[str, Any]:
    """Navigate the active page to a URL.

    wait_until can be 'load', 'domcontentloaded', 'networkidle', or 'commit'.
    """
    return await _call(browser_navigate, url=url, wait_until=wait_until)


@mcp.tool(name="browser_back")
async def tool_browser_back() -> dict[str, Any]:
    """Navigate back to the previous page in history."""
    return await _call(browser_back)


@mcp.tool(name="browser_forward")
async def tool_browser_forward() -> dict[str, Any]:
    """Navigate forward to the next page in history."""
    return await _call(browser_forward)


@mcp.tool(name="browser_reload")
async def tool_browser_reload() -> dict[str, Any]:
    """Reload the current page."""
    return await _call(browser_reload)


@mcp.tool(name="browser_wait")
async def tool_browser_wait(
    seconds: Optional[float] = None,
    selector: Any = None,
    selector_type: str = "css",
    state: str = "visible",
) -> dict[str, Any]:
    """Wait for a number of seconds, or for an element to reach a state.

    state can be 'visible', 'hidden', 'attached', or 'detached'.
    """
    return await _call(
        browser_wait,
        seconds=seconds,
selector=selector,
        selector_type=selector_type,
        state=state,
    )


# ==========================================
# 3. PAGE INSPECTION
# ==========================================


@mcp.tool(name="browser_get_url")
async def tool_browser_get_url() -> dict[str, Any]:
    """Get the current URL of the active browser page."""
    return await _call(browser_get_url)


@mcp.tool(name="browser_get_title")
async def tool_browser_get_title() -> dict[str, Any]:
    """Get the document title of the active browser page."""
    return await _call(browser_get_title)


@mcp.tool(name="browser_get_text")
async def tool_browser_get_text(
    selector: Any = None,
    selector_type: str = "css",
    max_length: int = 5000,
) -> dict[str, Any]:
    """Extract visible text from the page or an element, capped at max_length."""
    return await _call(
        browser_get_text,
selector=selector,
        selector_type=selector_type,
        max_length=max_length,
    )


@mcp.tool(name="browser_get_html")
async def tool_browser_get_html(
    selector: Any = None,
    selector_type: str = "css",
    max_length: int = 10000,
) -> dict[str, Any]:
    """Extract HTML source from the page or an element, capped at max_length."""
    return await _call(
        browser_get_html,
selector=selector,
        selector_type=selector_type,
        max_length=max_length,
    )


@mcp.tool(name="browser_get_links")
async def tool_browser_get_links(limit: int = 50) -> dict[str, Any]:
    """Extract text and URLs for anchor links found on the page."""
    return await _call(browser_get_links, limit=limit)


@mcp.tool(name="browser_find")
async def tool_browser_find(
    selector_type: str = "css",
    selector: Any = "",
    name: Optional[str] = None,
    exact: bool = False,
) -> dict[str, Any]:
    """Find and inspect an element without modifying page state.

    Supports 'role', 'text', 'label', 'placeholder', 'css', 'xpath'.
    Accepts "Save", "text=Save", or {"type": "text", "value": "Save"}.
    Returns found, tag, text, visible, enabled, attributes, bounding_box.
    """
    return await _call(
        browser_find,
        selector=selector,
        selector_type=selector_type,
        name=name,
        exact=exact,
    )


# ==========================================
# 4. INTERACTION
# ==========================================


@mcp.tool(name="browser_click")
async def tool_browser_click(
    selector: Any,
    selector_type: str = "css",
    name: Optional[str] = None,
    exact: bool = False,
    timeout: Optional[int] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Click an element using a semantic (role/text/label/placeholder) or CSS/XPath selector.

    `selector` accepts "Submit" (CSS by default), a prefix form such as
    "text=Submit" / "role=button,Save" / "//div[@id='x']", or the object form
    {"type": "text", "value": "Submit"}.
    """
    return await _call(
        browser_click,
selector=selector,
        selector_type=selector_type,
        name=name,
        exact=exact,
        timeout=timeout,
        force=force,
    )


@mcp.tool(name="browser_type")
async def tool_browser_type(
    selector: Any,
    text: str,
    selector_type: str = "css",
    name: Optional[str] = None,
    exact: bool = False,
    delay: int = 50,
) -> dict[str, Any]:
    """Type text sequentially into an element with a realistic key delay."""
    return await _call(
        browser_type,
selector=selector,
        selector_type=selector_type,
        name=name,
        exact=exact,
        text=text,
        delay=delay,
    )


@mcp.tool(name="browser_fill")
async def tool_browser_fill(
    selector: Any,
    value: str,
    selector_type: str = "css",
    name: Optional[str] = None,
    exact: bool = False,
    timeout: Optional[int] = None,
) -> dict[str, Any]:
    """Fill an input/textarea with the exact value immediately."""
    return await _call(
        browser_fill,
selector=selector,
        selector_type=selector_type,
        name=name,
        exact=exact,
        value=value,
        timeout=timeout,
    )


@mcp.tool(name="browser_press")
async def tool_browser_press(
    key: str,
    selector: Any = None,
    selector_type: str = "css",
) -> dict[str, Any]:
    """Press a keyboard key (e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown')."""
    return await _call(
        browser_press,
        key=key,
selector=selector,
        selector_type=selector_type,
    )


@mcp.tool(name="browser_select")
async def tool_browser_select(
    selector: Any,
    value: str,
    selector_type: str = "css",
) -> dict[str, Any]:
    """Select an option in a <select> dropdown by value."""
    return await _call(
        browser_select,
selector=selector,
        selector_type=selector_type,
        value=value,
    )


@mcp.tool(name="browser_check")
async def tool_browser_check(selector: Any, selector_type: str = "css") -> dict[str, Any]:
    """Check a checkbox or radio button."""
    return await _call(browser_check, selector=selector, selector_type=selector_type)


@mcp.tool(name="browser_uncheck")
async def tool_browser_uncheck(selector: Any, selector_type: str = "css") -> dict[str, Any]:
    """Uncheck a checkbox."""
    return await _call(browser_uncheck, selector=selector, selector_type=selector_type)


@mcp.tool(name="browser_hover")
async def tool_browser_hover(selector: Any, selector_type: str = "css") -> dict[str, Any]:
    """Hover the cursor over an element."""
    return await _call(browser_hover, selector=selector, selector_type=selector_type)


@mcp.tool(name="browser_scroll")
async def tool_browser_scroll(direction: str = "down", amount: int = 500) -> dict[str, Any]:
    """Scroll the page 'up' or 'down' by a pixel amount."""
    return await _call(browser_scroll, direction=direction, amount=amount)


# ==========================================
# 5. SCREENSHOT
# ==========================================


@mcp.tool(name="browser_screenshot")
async def tool_browser_screenshot(
    full_page: bool = False,
    selector: Any = None,
    selector_type: str = "css",
    path: Optional[str] = None,
) -> dict[str, Any]:
    """Capture a screenshot of the active page or a specific element.

    Returns a base64 encoded image string for visual inspection.
    """
    return await _call(
        browser_screenshot,
        full_page=full_page,
selector=selector,
        selector_type=selector_type,
        path=path,
    )


# ==========================================
# 6. SESSIONS & HUMAN APPROVAL
# ==========================================


@mcp.tool(name="browser_list_profiles")
async def tool_browser_list_profiles() -> dict[str, Any]:
    """List all available persistent Chromium profile directories."""
    return await _call(browser_list_profiles)


@mcp.tool(name="browser_pending_approvals")
async def tool_browser_pending_approvals() -> dict[str, Any]:
    """List all risky actions pending human authorization."""
    return await _call(browser_pending_approvals)


@mcp.tool(name="browser_approve_action")
async def tool_browser_approve_action(
    approval_id: str, approved: bool = True
) -> dict[str, Any]:
    """Grant or deny approval for a pending risky action (posting, replying, deleting)."""
    return await _call(browser_approve_action, approval_id=approval_id, approved=approved)


# ==========================================
# 7. HIGH-LEVEL SEQUENCE EXECUTOR
# ==========================================


@mcp.tool(name="browser_execute")
async def tool_browser_execute(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute a sequence of browser operations sequentially.

    If a step fails, stops immediately and returns the failure step with a
    screenshot.
    """
    return await _call(browser_execute, steps=steps)


# ==========================================
# 8. GOOGLE BUSINESS PROFILE
# ==========================================


@mcp.tool(name="google_business_open")
async def tool_google_business_open(
    business_name: Optional[str] = None,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Open the Google Business Profile dashboard or in-search view."""
    return await _call(
        open_google_business, business_name=business_name, profile=profile
    )


@mcp.tool(name="google_business_get_profile")
async def tool_google_business_get_profile() -> dict[str, Any]:
    """Extract business name, category, address, phone, rating, and review count."""
    return await _call(get_google_business_profile)


@mcp.tool(name="google_business_list_accounts")
async def tool_google_business_list_accounts() -> dict[str, Any]:
    """List all Google Business Profile accounts linked to the authenticated user.

    The browser must already be signed in (call google_business_open first if
    needed). Returns a list of {account_name, display_name, url} objects. Use
    the returned account_name values with google_business_list_locations.
    """
    return await _call(list_google_business_accounts)


@mcp.tool(name="google_business_list_locations")
async def tool_google_business_list_locations(
    account_name: str = "accounts/me",
) -> dict[str, Any]:
    """List all locations (stores, offices) under a Google Business Profile account.

    Args:
        account_name: Account resource name from google_business_list_accounts,
            e.g. 'accounts/123456789'. Defaults to 'accounts/me', which uses
            whichever account is currently active in the browser.

    Returns a list of {location_name, display_name, address} objects. Use
    location_name with google_business_get_reviews to fetch reviews.
    """
    return await _call(list_google_business_locations, account_name=account_name)


@mcp.tool(name="google_business_get_reviews")
async def tool_google_business_get_reviews(limit: int = 10) -> dict[str, Any]:
    """Extract recent customer reviews and their reply status."""
    return await _call(get_google_business_reviews, limit=limit)


@mcp.tool(name="google_business_reply_review")
async def tool_google_business_reply_review(
    review_id: str,
    reply_text: str,
    approval_id: Optional[str] = None,
) -> dict[str, Any]:
    """Reply publicly to a Google customer review.

    Requires human approval under strict policy before publishing.
    """
    return await _call(
        reply_to_google_business_review,
        review_id=review_id,
        reply_text=reply_text,
        approval_id=approval_id,
    )


@mcp.tool(name="google_business_create_post")
async def tool_google_business_create_post(
    content: str,
    media_path: Optional[str] = None,
    image_path: Optional[str] = None,
    cta_type: Optional[str] = None,
    cta_url: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> dict[str, Any]:
    """Publish a public update/offer post, with an optional photo attachment.

    Requires human approval under strict policy.
    """
    return await _call(
        create_google_business_post,
        content=content,
        media_path=media_path or image_path,
        cta_type=cta_type,
        cta_url=cta_url,
        approval_id=approval_id,
    )


@mcp.tool(name="google_business_create_post_with_media")
async def tool_google_business_create_post_with_media(
    content: str,
    media_path: str,
    cta_type: Optional[str] = None,
    cta_url: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> dict[str, Any]:
    """Publish a public update post with an attached local image/photo file.

    Requires human approval under strict policy. Prefer
    google_business_create_post, which accepts the same media_path and treats a
    missing image as "text-only post" rather than a request error.
    """
    return await _call(
        create_google_business_post_with_media,
        content=content,
        media_path=media_path,
        cta_type=cta_type,
        cta_url=cta_url,
        approval_id=approval_id,
    )


@mcp.tool(name="google_business_delete_post")
async def tool_google_business_delete_post(
    post_id: str,
    approval_id: Optional[str] = None,
) -> dict[str, Any]:
    """Delete a public post from Google Business Profile. Requires human approval."""
    return await _call(
        delete_google_business_post, post_id=post_id, approval_id=approval_id
    )


@mcp.tool(name="google_business_get_media")
async def tool_google_business_get_media() -> dict[str, Any]:
    """List photos and media displayed on the Google Business Profile."""
    return await _call(get_google_business_media)


@mcp.tool(name="google_business_upload_media")
async def tool_google_business_upload_media(
    file_path: str,
    category: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> dict[str, Any]:
    """Upload a local photo to the Google Business Profile. Requires human approval."""
    return await _call(
        upload_google_business_media,
        file_path=file_path,
        category=category,
        approval_id=approval_id,
    )


# ==========================================
# CLI RUNNER
# ==========================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Universal Browser Automation MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("BROWSER_MCP_TRANSPORT", "stdio"),
        help="Transport type (stdio, sse, streamable-http)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("BROWSER_MCP_HOST", "127.0.0.1"),
        help="Host for SSE / HTTP transport",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("BROWSER_MCP_PORT", "8000")),
        help="Port for SSE / HTTP transport",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=os.getenv("BROWSER_MCP_HEADLESS", "false").lower() == "true",
        help="Run browser in headless mode",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint."""
    setup_logging()
    args = parse_args()

    if args.headless:
        os.environ["BROWSER_MCP_HEADLESS"] = "true"

    logger.info(f"Starting Browser Automation MCP Server (transport={args.transport})")

    if args.transport in ("sse", "streamable-http"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        logger.info(f"Serving on http://{args.host}:{args.port}")

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()

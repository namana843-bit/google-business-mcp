"""Screenshot capture tool."""

from typing import Optional

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult, SelectorInput


async def browser_screenshot(
    manager: BrowserManager,
    full_page: bool = False,
    selector: Optional[SelectorInput] = None,
    path: Optional[str] = None,
) -> ActionResult:
    """Captures a screenshot of the current page or a specific element.

    Returns the image encoded as base64 in the result.
    """
    return await manager.screenshot(full_page=full_page, selector=selector, path=path)

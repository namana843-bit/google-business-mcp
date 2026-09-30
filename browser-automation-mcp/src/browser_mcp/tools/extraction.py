"""DOM extraction and page inspection tools."""

from typing import Optional

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult, SelectorInput


async def browser_get_url(manager: BrowserManager) -> ActionResult:
    """Returns the URL of the active browser page."""
    return await manager.get_url()


async def browser_get_title(manager: BrowserManager) -> ActionResult:
    """Returns the title of the active browser page."""
    return await manager.get_title()


async def browser_get_text(
    manager: BrowserManager,
    selector: Optional[SelectorInput] = None,
    max_length: int = 5000,
) -> ActionResult:
    """Extracts visible text from the entire page or a targeted element."""
    return await manager.get_text(selector=selector, max_length=max_length)


async def browser_get_html(
    manager: BrowserManager,
    selector: Optional[SelectorInput] = None,
    max_length: int = 10000,
) -> ActionResult:
    """Extracts HTML source code from the full page or a targeted element."""
    return await manager.get_html(selector=selector, max_length=max_length)


async def browser_get_links(manager: BrowserManager, limit: int = 50) -> ActionResult:
    """Extracts the list of links (text and href) present on the page."""
    return await manager.get_links(limit=limit)


async def browser_find(
    manager: BrowserManager,
    selector: Optional[SelectorInput] = None,
    selector_type: str = "css",
    name: Optional[str] = None,
    exact: bool = False,
) -> ActionResult:
    """Finds and inspects an element without modifying page state.

    Supports semantic selectors: role, text, label, placeholder, css, xpath.
    """
    return await manager.find(
        selector=selector,
        selector_type=selector_type,
        name=name,
        exact=exact,
    )

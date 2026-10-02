"""Browser navigation tools."""

from typing import Optional

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult, SelectorInput


async def browser_navigate(manager: BrowserManager, url: str, wait_until: str = "load") -> ActionResult:
    """Navigates to the specified URL."""
    return await manager.navigate(url=url, wait_until=wait_until)


async def browser_back(manager: BrowserManager) -> ActionResult:
    """Navigates back to the previous page in history."""
    return await manager.back()


async def browser_forward(manager: BrowserManager) -> ActionResult:
    """Navigates forward in page history."""
    return await manager.forward()


async def browser_reload(manager: BrowserManager) -> ActionResult:
    """Reloads the current page."""
    return await manager.reload()


async def browser_wait(
    manager: BrowserManager,
    seconds: Optional[float] = None,
    selector: Optional[SelectorInput] = None,
    state: str = "visible",
) -> ActionResult:
    """Waits for a given duration (seconds) or for an element to reach a state."""
    return await manager.wait(seconds=seconds, selector=selector, state=state)

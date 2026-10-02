"""Browser interaction tools."""

from typing import Optional

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult, SelectorInput


async def browser_click(
    manager: BrowserManager,
    selector: SelectorInput,
    timeout: Optional[int] = None,
    force: bool = False,
) -> ActionResult:
    """Clicks an element matched by a semantic or CSS selector."""
    return await manager.click(selector=selector, timeout=timeout, force=force)


async def browser_type(
    manager: BrowserManager,
    selector: SelectorInput,
    text: str,
    delay: int = 50,
) -> ActionResult:
    """Types text sequentially with realistic keyboard delays."""
    return await manager.type_text(selector=selector, text=text, delay=delay)


async def browser_fill(
    manager: BrowserManager,
    selector: SelectorInput,
    value: str,
    timeout: Optional[int] = None,
) -> ActionResult:
    """Clears and fills an input or textarea with the exact value."""
    return await manager.fill(selector=selector, value=value, timeout=timeout)


async def browser_press(
    manager: BrowserManager,
    key: str,
    selector: Optional[SelectorInput] = None,
) -> ActionResult:
    """Presses a keyboard key (e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown')."""
    return await manager.press(key=key, selector=selector)


async def browser_select(
    manager: BrowserManager,
    selector: SelectorInput,
    value: str,
) -> ActionResult:
    """Selects an option by value in a <select> dropdown element."""
    return await manager.select_option(selector=selector, value=value)


async def browser_check(manager: BrowserManager, selector: SelectorInput) -> ActionResult:
    """Checks a checkbox or radio button."""
    return await manager.check(selector=selector)


async def browser_uncheck(manager: BrowserManager, selector: SelectorInput) -> ActionResult:
    """Unchecks a checkbox element."""
    return await manager.uncheck(selector=selector)


async def browser_hover(manager: BrowserManager, selector: SelectorInput) -> ActionResult:
    """Hovers the mouse cursor over an element."""
    return await manager.hover(selector=selector)


async def browser_scroll(
    manager: BrowserManager,
    direction: str = "down",
    amount: int = 500,
) -> ActionResult:
    """Scrolls the page up or down by the specified pixel amount."""
    return await manager.scroll(direction=direction, amount=amount)

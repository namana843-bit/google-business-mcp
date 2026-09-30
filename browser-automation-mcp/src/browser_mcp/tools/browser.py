"""Browser lifecycle tools and the generic sequence executor."""

from typing import Any, Optional, Union

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import (
    ActionResult,
    BrowserStatusResponse,
    ExecuteStep,
    PageInfo,
)
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.utils.logging import get_logger

logger = get_logger("tools.browser")

_WAIT_STATES = ("visible", "attached", "hidden", "detached")

# Each sequence action names the step fields it requires, so a missing field is
# reported as a precise validation error instead of a KeyError or a silent no-op.
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "navigate": ("url",),
    "click": ("selector",),
    "fill": ("selector", "value"),
    "type": ("selector", "value"),
    "press": ("value",),
    "select": ("selector", "value"),
    "check": ("selector",),
    "uncheck": ("selector",),
    "hover": ("selector",),
}

# Pressing a key is the one action whose payload lives in `value` rather than a
# dedicated field, which is worth spelling out when reporting a missing field.
_REQUIREMENT_HINTS = {"press": " (the key to press)"}


async def browser_launch(
    manager: BrowserManager,
    profile: Optional[str] = None,
    headless: Optional[bool] = None,
    slow_mo: Optional[int] = None,
    executable_path: Optional[str] = None,
    cdp_url: Optional[str] = None,
) -> ActionResult:
    """Launches or connects to a persistent browser instance with the given profile."""
    return await manager.launch(
        profile=profile,
        headless=headless,
        slow_mo=slow_mo,
        executable_path=executable_path,
        cdp_url=cdp_url,
    )


async def browser_close(manager: BrowserManager) -> ActionResult:
    """Closes the current browser instance and flushes cookies/sessions to disk."""
    return await manager.close()


async def browser_status(manager: BrowserManager) -> BrowserStatusResponse:
    """Retrieves operational status of the browser."""
    return await manager.status()


async def browser_list_pages(manager: BrowserManager) -> list[PageInfo]:
    """Lists all open tabs/pages in the browser."""
    return await manager.list_pages()


async def browser_new_page(manager: BrowserManager, url: Optional[str] = None) -> ActionResult:
    """Opens a new tab/page and optionally navigates to a URL."""
    return await manager.new_page(url=url)


async def browser_switch_page(manager: BrowserManager, index: int) -> ActionResult:
    """Switches active page focus to the specified index."""
    return await manager.switch_page(index=index)


async def browser_close_page(manager: BrowserManager, index: Optional[int] = None) -> ActionResult:
    """Closes a tab/page by index, or the active page if omitted."""
    return await manager.close_page(index=index)


async def browser_execute(
    manager: BrowserManager,
    steps: list[Union[ExecuteStep, dict[str, Any]]],
) -> ActionResult:
    """Executes a sequence of browser operations sequentially.

    Returns a per-step report and halts at the first failure, attaching a
    screenshot of the page at that moment.
    """
    if not manager.is_running:
        await manager.launch()

    report: list[dict[str, Any]] = []
    for number, raw in enumerate(steps, start=1):
        step = ExecuteStep(**raw) if isinstance(raw, dict) else raw
        try:
            result = await _run_step(manager, step)
        except ValueError as e:
            result = ActionResult(
                success=False, error_type=ErrorCode.INVALID_REQUEST.value, message=str(e)
            )
        except Exception as e:
            result = ActionResult(
                success=False, error_type=ErrorCode.UNKNOWN.value, message=str(e)
            )

        report.append(
            {
                "step": number,
                "action": step.action.lower(),
                "success": result.success,
                "message": result.message,
                "error_type": result.error_type,
            }
        )
        if not result.success:
            return await _halt(manager, result, number, step.action.lower(), report, len(steps))

    return ActionResult(
        success=True,
        message=f"Successfully executed all {len(steps)} steps.",
        data={
            "completed_steps": len(steps),
            "total_steps": len(steps),
            "step_results": report,
        },
    )


async def _run_step(manager: BrowserManager, step: ExecuteStep) -> ActionResult:
    """Dispatches one sequence step to the matching manager operation."""
    action = step.action.lower()

    for field in _REQUIRED_FIELDS.get(action, ()):
        if not getattr(step, field):
            hint = _REQUIREMENT_HINTS.get(action, "")
            raise ValueError(f"Action '{action}' requires '{field}'{hint}")

    match action:
        case "navigate":
            return await manager.navigate(url=step.url)
        case "click":
            return await manager.click(selector=step.selector)
        case "fill":
            return await manager.fill(selector=step.selector, value=step.value)
        case "type":
            return await manager.type_text(selector=step.selector, text=step.value)
        case "press":
            return await manager.press(key=step.value, selector=step.selector)
        case "select":
            return await manager.select_option(selector=step.selector, value=step.value)
        case "check":
            return await manager.check(selector=step.selector)
        case "uncheck":
            return await manager.uncheck(selector=step.selector)
        case "hover":
            return await manager.hover(selector=step.selector)
        case "scroll":
            return await manager.scroll(
                direction=step.options.get("direction", "down"),
                amount=_scroll_amount(step.options),
            )
        case "wait":
            return await _wait(manager, step)
        case _:
            return ActionResult(
                success=False,
                error_type=ErrorCode.INVALID_REQUEST.value,
                message=f"Unsupported action in execute sequence: {action}",
            )


def _scroll_amount(options: Optional[dict[str, Any]]) -> int:
    raw = (options or {}).get("amount", 500)
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError("Scroll 'amount' must be an integer") from None


async def _wait(manager: BrowserManager, step: ExecuteStep) -> ActionResult:
    options = step.options or {}
    state = options.get("state", "visible")
    if state not in _WAIT_STATES:
        raise ValueError(f"Unsupported wait state: {state}")
    return await manager.wait(
        seconds=options.get("seconds", 1.0), selector=step.selector, state=state
    )


async def _halt(
    manager: BrowserManager,
    failure: ActionResult,
    number: int,
    action: str,
    report: list[dict[str, Any]],
    total: int,
) -> ActionResult:
    """Builds the halt result for a failed step, capturing evidence."""
    try:
        screenshot = (await manager.screenshot(full_page=False)).screenshot
    except Exception:
        screenshot = None

    return ActionResult(
        success=False,
        error_type=failure.error_type or ErrorCode.UNKNOWN.value,
        message=f"Execution halted at step {number} ({action}): {failure.message}",
        screenshot=screenshot,
        data={
            "step": number,
            "action": action,
            "error": failure.message,
            "screenshot_available": screenshot is not None,
            "completed_steps": number - 1,
            "total_steps": total,
            "step_results": report,
        },
    )

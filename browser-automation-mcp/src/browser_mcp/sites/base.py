"""Abstract base class and contract for site-specific adapters."""

from abc import ABC, abstractmethod
from typing import Any

from playwright.async_api import Page

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.utils.logging import get_logger

logger = get_logger("sites.base")


class SiteAdapter(ABC):
    """Base site adapter interface for orchestrating domain-specific workflows."""

    name: str = "generic"
    base_url: str = ""
    allowed_domains: list[str] = []

    @abstractmethod
    async def detect(self, page: Page) -> bool:
        """Determines if the active page belongs to this site adapter."""
        ...

    @abstractmethod
    async def open(self, manager: BrowserManager) -> ActionResult:
        """Navigates to the service's primary dashboard or home."""
        ...

    @abstractmethod
    async def execute(self, manager: BrowserManager, action: str, **kwargs: Any) -> ActionResult:
        """Executes a named site action."""
        ...


async def abort_with_screenshot(
    manager: BrowserManager,
    page: Page,
    message: str,
    error_type: ErrorCode = ErrorCode.ELEMENT_NOT_FOUND,
) -> ActionResult:
    """Returns a failure result with a screenshot attached as diagnostic evidence.

    Site automation fails far more often because markup shifted than because
    the operation was wrong, so a screenshot is what lets a human or agent see
    what the page actually looked like.
    """
    try:
        screenshot = (await manager.screenshot()).screenshot
    except Exception as e:
        logger.debug(f"Could not capture failure screenshot: {e}")
        screenshot = None
    return ActionResult(
        success=False,
        error_type=error_type.value,
        message=message,
        screenshot=screenshot,
        url=page.url,
    )


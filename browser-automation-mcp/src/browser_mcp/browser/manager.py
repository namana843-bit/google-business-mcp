"""Core BrowserManager lifecycle and operational controller."""

import base64
import os
from collections.abc import Awaitable, Callable
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Locator, Page, Playwright, async_playwright

from browser_mcp.browser.context import connect_cdp_context, create_persistent_context
from browser_mcp.browser.pages import (
    detect_page_challenges,
    inspect_element,
    parse_selector,
    resolve_locator,
)
from browser_mcp.browser.profiles import ProfileManager
from browser_mcp.models.schemas import (
    ActionResult,
    BrowserStatusResponse,
    PageInfo,
    SelectorInput,
)
from browser_mcp.storage.database import DatabaseManager
from browser_mcp.utils.errors import (
    BrowserNotRunningError,
    ErrorCode,
    NavigationError,
    PermissionDeniedError,
)
from browser_mcp.utils.logging import get_logger

logger = get_logger("manager")

# Schemes that never reach the network, so domain policy does not apply.
_UNRESTRICTED_URL_PREFIXES = ("about:", "data:", "file:")

_WAIT_UNTIL_CHOICES = ("load", "domcontentloaded", "networkidle", "commit")

# Challenges that must halt automation until a human intervenes.
_CHALLENGE_MESSAGES = {
    ErrorCode.LOGIN_REQUIRED: (
        "User authentication is required. Please complete login in the browser."
    ),
    ErrorCode.CAPTCHA_DETECTED: (
        "Security challenge or CAPTCHA detected. Human intervention required."
    ),
}

# Playwright's failure text is the only signal distinguishing a slow element
# from a rejected interaction.
_TIMEOUT_HINTS = ("timeout", "exceeded")

# Failure text Playwright produces when the browser died mid-action.
_CLOSED_BROWSER_HINTS = ("closed", "processsingleton", "target page")

_PROFILE_LOCK_HINT = (
    "Hint: if Google Chrome is already running on your desktop, either close it "
    "completely or start it with '--remote-debugging-port=9222' and set "
    "BROWSER_MCP_CDP_URL=http://127.0.0.1:9222"
)


def _csv_env(name: str) -> list[str]:
    """Reads a comma-separated environment variable into a clean list."""
    return [part.strip().lower() for part in os.getenv(name, "").split(",") if part.strip()]


def _failure(code: ErrorCode, message: str, url: Optional[str] = None) -> ActionResult:
    """Builds a failed ActionResult with a predictable error code."""
    return ActionResult(success=False, error_type=code.value, message=message, url=url)


def _classify(exc: Exception) -> ErrorCode:
    """Classifies a Playwright exception into an ErrorCode."""
    text = str(exc).lower()
    return ErrorCode.TIMEOUT if any(h in text for h in _TIMEOUT_HINTS) else ErrorCode.UNKNOWN


def _truncate(value: str, max_length: int) -> tuple[str, int, bool]:
    """Returns (clipped value, original length, whether clipping occurred)."""
    clipped = len(value) > max_length
    return (value[:max_length] if clipped else value, len(value), clipped)


class _MissingElement(Exception):
    """Internal control-flow signal carrying a built ActionResult to its caller."""

    def __init__(self, result: ActionResult):
        super().__init__(result.message or "")
        self.result = result


class BrowserManager:
    """Controls the persistent Playwright Chromium browser and page interactions."""

    def __init__(
        self,
        profile_manager: Optional[ProfileManager] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.profile_manager = profile_manager or ProfileManager()
        self.db = db_manager or DatabaseManager()
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._active_page_index = 0
        self._active_profile: Optional[str] = None
        self._headless = os.getenv("BROWSER_MCP_HEADLESS", "false").lower() == "true"
        self._default_timeout = int(os.getenv("BROWSER_MCP_DEFAULT_TIMEOUT", "30000"))
        self._executable_path: Optional[str] = os.getenv("BROWSER_MCP_EXECUTABLE_PATH")
        self.allowed_domains = _csv_env("BROWSER_MCP_ALLOWED_DOMAINS")
        self.blocked_domains = _csv_env("BROWSER_MCP_BLOCKED_DOMAINS")

    @property
    def is_running(self) -> bool:
        """True while a browser context is held.

        Liveness is the context, not the tab count. A persistent context
        outlives all of its pages being closed and still owns the profile lock,
        so judging liveness by tab count would make navigate()/new_page()
        relaunch against an already-locked user_data_dir.
        """
        return self._context is not None

    @property
    def active_profile(self) -> Optional[str]:
        """Profile backing the current context, or None when not running."""
        return self._active_profile

    async def get_active_page(self) -> Page:
        """Returns the focused page. Raises when the browser is not running."""
        if not self._context or not self._context.pages:
            raise BrowserNotRunningError()
        if self._active_page_index >= len(self._context.pages):
            self._active_page_index = len(self._context.pages) - 1
        return self._context.pages[self._active_page_index]

    # --- Policy ---

    def _verify_domain_allowed(self, url: str) -> None:
        """Raises PermissionDeniedError if the URL violates the domain policy."""

        def matches(domains: list[str]) -> bool:
            return any(
                hostname == domain or hostname.endswith(f".{domain}") for domain in domains
            )

        if url.startswith(_UNRESTRICTED_URL_PREFIXES):
            return

        hostname = (urlparse(url).hostname or "").lower()

        if self.blocked_domains and matches(self.blocked_domains):
            raise PermissionDeniedError(
                message=f"Access to domain '{hostname}' is blocked by security policy.",
                url=url,
                reason="BLOCKED_DOMAIN",
            )
        if self.allowed_domains and not matches(self.allowed_domains):
            raise PermissionDeniedError(
                message=(
                    f"Domain '{hostname}' is not in the allowed domains list: "
                    f"{self.allowed_domains}"
                ),
                url=url,
                reason="DISALLOWED_DOMAIN",
            )

    # --- Lifecycle ---

    async def launch(
        self,
        profile: Optional[str] = None,
        headless: Optional[bool] = None,
        slow_mo: Optional[int] = None,
        executable_path: Optional[str] = None,
        cdp_url: Optional[str] = None,
    ) -> ActionResult:
        """Launches a persistent browser context, or reuses the running one."""
        target_profile = profile or os.getenv("BROWSER_MCP_DEFAULT_PROFILE", "default")

        if executable_path:
            self._executable_path = executable_path

        if self._context is not None:
            if self._active_profile == target_profile:
                return await self._reuse_running(target_profile)
            logger.info(
                f"Switching active profile from '{self._active_profile}' to '{target_profile}'."
            )
            await self.close()

        if headless is not None:
            self._headless = headless

        if not self._playwright:
            self._playwright = await async_playwright().start()

        effective_cdp = cdp_url or os.getenv("BROWSER_MCP_CDP_URL")
        try:
            self._context = (
                await self._connect_over_cdp(effective_cdp)
                if effective_cdp
                else await self._launch_persistent(target_profile, slow_mo, self._executable_path)
            )
        except Exception:
            # A half-initialised driver must not outlive a failed launch.
            await self._discard_driver()
            raise

        if not self._context.pages:
            await self._context.new_page()
        self._active_page_index = 0
        self._active_profile = target_profile
        self.db.touch_profile(target_profile)

        page = self._context.pages[0]
        page.set_default_timeout(self._default_timeout)
        logger.info(
            f"Browser launched with profile '{target_profile}' (headless={self._headless})"
        )
        self.db.log_action("browser_launch", profile=target_profile, status="SUCCESS")
        return ActionResult(
            success=True,
            message=f"Browser launched with profile '{target_profile}'.",
            url=page.url,
            title=await page.title(),
            data={"profile": target_profile, "headless": self._headless},
        )

    async def _reuse_running(self, profile: str) -> ActionResult:
        """Reports an already-running context, opening a tab if it has none."""
        logger.info(f"Browser already running with profile '{profile}'. Reusing session.")
        # A live context can legitimately hold zero tabs, which get_active_page
        # treats as not-running, so open one directly.
        if not self._context.pages:
            page = await self._context.new_page()
            page.set_default_timeout(self._default_timeout)
            self._active_page_index = 0
        else:
            page = await self.get_active_page()
        return ActionResult(
            success=True,
            message=f"Browser already running with profile '{profile}'.",
            url=page.url,
            title=await page.title(),
            data={"profile": profile, "running": True},
        )

    async def _connect_over_cdp(self, cdp_url: str) -> BrowserContext:
        logger.info(f"Connecting to browser via CDP: {cdp_url}")
        try:
            return await connect_cdp_context(self._playwright, endpoint_url=cdp_url)
        except Exception as e:
            raise NavigationError(
                message=f"Failed to connect to Chrome via CDP at {cdp_url}: {e}",
                url=None,
                details={"cdp_url": cdp_url, "cause": str(e)},
            ) from e

    async def _launch_persistent(
        self,
        profile: str,
        slow_mo: Optional[int],
        executable_path: Optional[str],
    ) -> BrowserContext:
        # Check the lock before touching the filesystem.
        self.profile_manager.check_or_throw_locked(profile)
        user_data_dir, profile_dir = self.profile_manager.resolve_target(profile)
        try:
            return await create_persistent_context(
                playwright=self._playwright,
                user_data_dir=user_data_dir,
                headless=self._headless,
                slow_mo=slow_mo,
                executable_path=executable_path or self._executable_path,
                profile_directory=profile_dir,
            )
        except Exception as e:
            message = str(e)
            if any(hint in message.lower() for hint in _CLOSED_BROWSER_HINTS):
                message += f" {_PROFILE_LOCK_HINT}"
            logger.error(f"Failed to launch browser for profile '{profile}': {message}")
            raise NavigationError(
                message=f"Failed to launch browser: {message}",
                url=None,
                details={"profile": profile, "cause": str(e)},
            ) from e

    async def _discard_driver(self) -> None:
        """Tears down a half-initialised driver so a failed launch leaks nothing."""
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning(f"Error stopping playwright after failed launch: {e}")
        self._playwright = None
        self._context = None

    async def close(self) -> ActionResult:
        """Closes the context and the driver, releasing all resources."""
        # The driver and the context are separate resources; guarding on the
        # context alone leaks the driver process when the context is already gone.
        if not self._context and not self._playwright:
            return ActionResult(success=True, message="Browser was not running.")

        profile = self._active_profile
        if self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.warning(f"Error during context close: {e}")
            finally:
                self._context = None
                self._active_profile = None
                self._active_page_index = 0

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning(f"Error during playwright stop: {e}")
            finally:
                self._playwright = None

        self.db.log_action("browser_close", profile=profile, status="SUCCESS")
        return ActionResult(success=True, message="Browser closed cleanly.")

    async def status(self) -> BrowserStatusResponse:
        """Reports the operational state of the browser."""
        if not self._context:
            return BrowserStatusResponse(running=False, headless=self._headless)

        state = {
            "running": True,
            "profile": self._active_profile,
            "headless": self._headless,
            "page_count": len(self._context.pages),
            "current_page_index": self._active_page_index,
        }
        # A live context may hold zero tabs; report that honestly rather than
        # failing as though the browser were down.
        if not self._context.pages:
            return BrowserStatusResponse(**state, current_url=None, current_title=None)

        page = await self.get_active_page()
        return BrowserStatusResponse(
            **state, current_url=page.url, current_title=await page.title()
        )

    # --- Tab Management ---

    async def list_pages(self) -> list[PageInfo]:
        """Lists all open tabs."""
        if not self._context:
            return []

        pages = []
        for index, page in enumerate(self._context.pages):
            try:
                url, title = page.url, await page.title()
            except Exception:
                url = title = "Unknown"
            pages.append(
                PageInfo(
                    index=index,
                    url=url,
                    title=title,
                    is_active=(index == self._active_page_index),
                )
            )
        return pages

    async def new_page(self, url: Optional[str] = None) -> ActionResult:
        """Opens a new tab and optionally navigates it to a URL."""
        if not self.is_running:
            await self.launch()
        if not self._context:
            raise BrowserNotRunningError()

        page = await self._context.new_page()
        page.set_default_timeout(self._default_timeout)
        self._active_page_index = len(self._context.pages) - 1

        if url:
            return await self.navigate(url)
        return ActionResult(
            success=True,
            message="New page opened.",
            url=page.url,
            title=await page.title(),
            data={"page_index": self._active_page_index},
        )

    async def switch_page(self, index: int) -> ActionResult:
        """Focuses the tab at the given index."""
        if not self._context:
            raise BrowserNotRunningError()
        if not 0 <= index < len(self._context.pages):
            return _failure(
                ErrorCode.INVALID_REQUEST,
                f"Page index {index} out of range (0-{len(self._context.pages) - 1})",
            )

        self._active_page_index = index
        page = self._context.pages[index]
        await page.bring_to_front()
        return ActionResult(
            success=True,
            message=f"Switched to page index {index}.",
            url=page.url,
            title=await page.title(),
            data={"page_index": index},
        )

    async def close_page(self, index: Optional[int] = None) -> ActionResult:
        """Closes a tab, defaulting to the active one."""
        if not self._context:
            raise BrowserNotRunningError()

        target = self._active_page_index if index is None else index
        if not 0 <= target < len(self._context.pages):
            return _failure(ErrorCode.INVALID_REQUEST, f"Page index {target} out of range.")

        await self._context.pages[target].close()
        if not self._context.pages:
            return await self.close()

        # Closing a tab below the active one shifts every later tab down, so the
        # active index has to follow the same tab rather than just be clamped.
        if target < self._active_page_index:
            self._active_page_index -= 1
        self._active_page_index = min(self._active_page_index, len(self._context.pages) - 1)
        active = await self.get_active_page()
        return ActionResult(
            success=True,
            message=f"Closed page index {target}.",
            url=active.url,
            title=await active.title(),
            data={"remaining_pages": len(self._context.pages)},
        )

    # --- Navigation ---

    async def navigate(self, url: str, wait_until: str = "load") -> ActionResult:
        """Navigates the active page to a URL."""
        if not self.is_running:
            await self.launch()

        self._verify_domain_allowed(url)
        page = await self.get_active_page()
        if wait_until not in _WAIT_UNTIL_CHOICES:
            wait_until = "load"

        try:
            response = await page.goto(
                url, wait_until=wait_until, timeout=self._default_timeout
            )
        except Exception as e:
            logger.error(f"Navigation failed for {url}: {e}")
            self.db.log_action(
                "browser_navigate",
                target_url=url,
                profile=self._active_profile,
                status="FAILED",
                details={"error": str(e)},
            )
            return _failure(
                ErrorCode.NAVIGATION_ERROR, f"Failed to navigate to {url}: {e}", page.url
            )

        challenge = await detect_page_challenges(page)
        if challenge in _CHALLENGE_MESSAGES:
            return ActionResult(
                success=False,
                error_type=challenge.value,
                message=_CHALLENGE_MESSAGES[challenge],
                url=page.url,
                title=await page.title(),
            )

        self.db.log_action(
            "browser_navigate", target_url=url, profile=self._active_profile, status="SUCCESS"
        )
        return ActionResult(
            success=True,
            message=f"Navigated to {url}",
            url=page.url,
            title=await page.title(),
            data={"status_code": response.status if response else None},
        )

    async def back(self) -> ActionResult:
        return await self._history_step("go_back")

    async def forward(self) -> ActionResult:
        return await self._history_step("go_forward")

    async def reload(self) -> ActionResult:
        return await self._history_step("reload")

    async def _history_step(self, method: str) -> ActionResult:
        page = await self.get_active_page()
        await getattr(page, method)()
        return ActionResult(success=True, url=page.url, title=await page.title())

    async def wait(
        self,
        seconds: Optional[float] = None,
        selector: Optional[SelectorInput] = None,
        state: str = "visible",
    ) -> ActionResult:
        """Waits for an element state, a duration, or DOM readiness.

        Exactly one condition applies. An explicit `seconds=0` is honoured
        rather than treated as absent, so callers can rely on what they passed.
        """
        page = await self.get_active_page()

        if selector:
            locator = resolve_locator(page, selector)
            await locator.wait_for(state=state, timeout=self._default_timeout)
            return ActionResult(
                success=True, message=f"Waited for element {selector} to be {state}."
            )
        if seconds is not None:
            await page.wait_for_timeout(seconds * 1000)
            return ActionResult(success=True, message=f"Waited for {seconds} seconds.")

        await page.wait_for_load_state("domcontentloaded")
        return ActionResult(success=True, message="Waited for DOM content loaded.")

    # --- Inspection ---

    async def get_url(self) -> ActionResult:
        page = await self.get_active_page()
        return ActionResult(success=True, url=page.url, title=await page.title())

    async def get_title(self) -> ActionResult:
        page = await self.get_active_page()
        return ActionResult(success=True, title=await page.title(), url=page.url)

    async def get_text(
        self, selector: Optional[SelectorInput] = None, max_length: int = 5000
    ) -> ActionResult:
        page = await self.get_active_page()
        if selector:
            target = await self._require_locator(page, selector, "read text from")
            text = await target.inner_text()
        else:
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return await self._extraction_result(page, "text", text, max_length)

    async def get_html(
        self, selector: Optional[SelectorInput] = None, max_length: int = 10000
    ) -> ActionResult:
        page = await self.get_active_page()
        if selector:
            target = await self._require_locator(page, selector, "read HTML from")
            html = await target.inner_html()
        else:
            html = await page.content()
        return await self._extraction_result(page, "html", html, max_length)

    async def _extraction_result(
        self, page: Page, key: str, value: str, max_length: int
    ) -> ActionResult:
        """Wraps an extracted string with truncation metadata."""
        clipped, length, truncated = _truncate(value, max_length)
        return ActionResult(
            success=True,
            url=page.url,
            title=await page.title(),
            data={key: clipped, "length": length, "is_truncated": truncated},
        )

    async def get_links(self, limit: int = 50) -> ActionResult:
        page = await self.get_active_page()
        found = await page.evaluate(
            """limit => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return {
                    links: anchors.slice(0, limit).map(a => ({
                        text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
                        href: a.href,
                    })),
                    // Report the true total, not the capped slice length.
                    total: anchors.length,
                };
            }""",
            limit,
        )
        return ActionResult(
            success=True,
            url=page.url,
            title=await page.title(),
            data={
                "links": found["links"],
                "returned": len(found["links"]),
                "total_found": found["total"],
            },
        )

    async def find(
        self,
        selector: Optional[SelectorInput] = None,
        selector_type: str = "css",
        name: Optional[str] = None,
        exact: bool = False,
    ) -> ActionResult:
        """Inspects an element without modifying page state."""
        page = await self.get_active_page()
        if selector is None or selector == "":
            return _failure(
                ErrorCode.ELEMENT_NOT_FOUND, "No selector supplied to browser_find", page.url
            )

        parsed = parse_selector(selector, selector_type, name, exact)
        info = await inspect_element(resolve_locator(page, parsed))
        return ActionResult(
            success=info.found,
            error_type=None if info.found else ErrorCode.ELEMENT_NOT_FOUND.value,
            message=f"Element inspection for selector={selector!r}",
            url=page.url,
            title=await page.title(),
            data=info.model_dump(),
        )

    # --- Interaction ---

    async def click(
        self,
        selector: SelectorInput,
        timeout: Optional[int] = None,
        force: bool = False,
    ) -> ActionResult:
        async def run(target: Locator) -> str:
            await target.click(timeout=timeout or self._default_timeout, force=force)
            return f"Clicked element: {selector}"

        return await self._interact(selector, "click", run)

    async def fill(
        self,
        selector: SelectorInput,
        value: str,
        timeout: Optional[int] = None,
    ) -> ActionResult:
        async def run(target: Locator) -> str:
            await target.fill(value, timeout=timeout or self._default_timeout)
            return f"Filled element with value: {value}"

        return await self._interact(selector, "fill", run)

    async def type_text(
        self, selector: SelectorInput, text: str, delay: int = 50
    ) -> ActionResult:
        async def run(target: Locator) -> str:
            await target.press_sequentially(text, delay=delay)
            return "Typed text into element"

        return await self._interact(selector, "type in", run)

    async def select_option(self, selector: SelectorInput, value: str) -> ActionResult:
        async def run(target: Locator) -> str:
            await target.select_option(value=value)
            return f"Selected option: {value}"

        return await self._interact(selector, "select an option in", run)

    async def check(self, selector: SelectorInput) -> ActionResult:
        return await self._interact(selector, "check", self._simple("check", "checkbox/radio"))

    async def uncheck(self, selector: SelectorInput) -> ActionResult:
        return await self._interact(selector, "uncheck", self._simple("uncheck", "checkbox"))

    async def hover(self, selector: SelectorInput) -> ActionResult:
        return await self._interact(selector, "hover", self._simple("hover", "element"))

    def _simple(self, verb: str, noun: str) -> Callable[[Locator], Awaitable[str]]:
        """Builds an operation for verbs that take no arguments."""

        async def run(target: Locator) -> str:
            await getattr(target, verb)()
            return f"{verb.capitalize()}ed {noun}"

        return run

    async def press(
        self, key: str, selector: Optional[SelectorInput] = None
    ) -> ActionResult:
        """Presses a key, optionally scoped to an element."""
        try:
            if selector:
                await resolve_locator(await self.get_active_page(), selector).first.press(key)
            else:
                page = await self.get_active_page()
                await page.keyboard.press(key)
        except Exception as e:
            return _failure(ErrorCode.UNKNOWN, f"Failed to press key: {e}")
        return ActionResult(success=True, message=f"Pressed key: {key}")

    async def scroll(self, direction: str = "down", amount: int = 500) -> ActionResult:
        page = await self.get_active_page()
        delta = amount if direction == "down" else -amount
        await page.mouse.wheel(0, delta)
        await page.wait_for_timeout(300)
        return ActionResult(
            success=True, message=f"Scrolled {direction} by {amount}px", url=page.url
        )

    async def _interact(
        self,
        selector: SelectorInput,
        action: str,
        operation: Callable[[Locator], Awaitable[str]],
    ) -> ActionResult:
        """Runs one Playwright verb against the first match for `selector`.

        All interaction tools share this shape: resolve the selector, require at
        least one match, run the verb, and translate any failure into a typed
        ActionResult rather than propagating an exception. `action` is a
        human-readable verb phrase used to build failure messages.
        """
        page = await self.get_active_page()
        try:
            target = await self._require_locator(page, selector, action)
            message = await operation(target)
        except _MissingElement as missing:
            return missing.result
        except Exception as e:
            return _failure(_classify(e), f"Failed to {action} element: {e}", page.url)
        return ActionResult(success=True, message=message, url=page.url)

    async def _require_locator(
        self, page: Page, selector: SelectorInput, action: str
    ) -> Locator:
        """Returns the first match for `selector`, or raises _MissingElement."""
        locator = resolve_locator(page, selector)
        if await locator.count() == 0:
            raise _MissingElement(
                _failure(
                    ErrorCode.ELEMENT_NOT_FOUND,
                    f"Could not find element to {action}: {selector}",
                    page.url,
                )
            )
        return locator.first

    # --- Screenshots ---

    async def screenshot(
        self,
        full_page: bool = False,
        selector: Optional[SelectorInput] = None,
        path: Optional[str] = None,
    ) -> ActionResult:
        """Captures a page or element screenshot as base64, optionally to disk."""
        page = await self.get_active_page()
        try:
            if selector:
                target = await self._require_locator(page, selector, "screenshot")
                image = await target.screenshot(path=path)
            else:
                image = await page.screenshot(full_page=full_page, path=path)
        except _MissingElement as missing:
            return missing.result
        except Exception as e:
            return _failure(ErrorCode.UNKNOWN, f"Screenshot failed: {e}", page.url)

        return ActionResult(
            success=True,
            message="Screenshot captured.",
            url=page.url,
            title=await page.title(),
            screenshot=base64.b64encode(image).decode("utf-8"),
            data={
                "path": path,
                "full_page": full_page,
                "size_bytes": len(image),
                "base64_available": True,
            },
        )

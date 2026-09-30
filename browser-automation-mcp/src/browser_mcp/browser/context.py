"""Chromium context configuration and persistent context creation."""

import os
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Playwright

from browser_mcp.utils.logging import get_logger

logger = get_logger("context")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-features=Translate,OptimizationHints",
    "--disable-infobars",
    "--window-size=1280,800",
]

DEFAULT_VIEWPORT = {"width": 1280, "height": 800}

# Hides automation flags cleanly without breaking prototype chain or setting suspicious own properties.
WEBDRIVER_EVASION = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


def _resolve_executable(executable_path: Optional[str]) -> Optional[str]:
    """Normalises a configured browser path, or None to use bundled Chromium.

    A blank env var is common ("BROWSER_MCP_EXECUTABLE_PATH=" in .env), and
    passing that empty string straight to Playwright makes it spawn a process
    named "" and fail with the unhelpful "spawn . ENOENT".

    Raises FileNotFoundError when a path is explicitly configured but does not
    exist, so misconfigurations are caught immediately instead of silently
    falling back to bundled Chromium.
    """
    candidate = executable_path or os.getenv("BROWSER_MCP_EXECUTABLE_PATH")
    if isinstance(candidate, str):
        candidate = candidate.strip().strip('"').strip("'").strip() or None
    if not candidate:
        return None
    if not Path(candidate).exists():
        raise FileNotFoundError(
            f"Configured BROWSER_MCP_EXECUTABLE_PATH does not exist: {candidate}"
        )
    return candidate


async def create_persistent_context(
    playwright: Playwright,
    user_data_dir: Path,
    headless: bool = False,
    slow_mo: Optional[int] = None,
    extra_args: Optional[list[str]] = None,
    executable_path: Optional[str] = None,
    profile_directory: Optional[str] = None,
    ignore_default_args: Optional[list[str]] = None,
) -> BrowserContext:
    """Launches a persistent Chromium context under `user_data_dir`.

    Session state, cookies, and localStorage all live in `user_data_dir`, so
    manual logins survive across restarts.
    """
    args = list(DEFAULT_CHROMIUM_ARGS)
    if profile_directory:
        args.append(f"--profile-directory={profile_directory}")
    args.extend(extra_args or [])

    resolved_executable = _resolve_executable(executable_path)
    ignored = (
        list(ignore_default_args)
        if ignore_default_args is not None
        else ["--enable-automation"]
    )

    logger.info(
        f"Launching persistent Chromium context at {user_data_dir} "
        f"(profile={profile_directory}, headless={headless}, slow_mo={slow_mo}, "
        f"executable={resolved_executable})"
    )

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        executable_path=resolved_executable,
        headless=headless,
        slow_mo=slow_mo or 0,
        args=args,
        ignore_default_args=ignored,
        user_agent=DEFAULT_USER_AGENT,
        viewport=DEFAULT_VIEWPORT,
        device_scale_factor=1,
        accept_downloads=True,
        locale="en-US",
        timezone_id="UTC",
    )
    await context.add_init_script(WEBDRIVER_EVASION)
    return context


async def connect_cdp_context(
    playwright: Playwright,
    endpoint_url: str = "http://127.0.0.1:9222",
) -> BrowserContext:
    """Connects to an already-running Chrome instance over the DevTools Protocol."""
    logger.info(f"Connecting to Chrome via CDP at {endpoint_url}")
    browser = await playwright.chromium.connect_over_cdp(endpoint_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    await context.add_init_script(WEBDRIVER_EVASION)
    return context


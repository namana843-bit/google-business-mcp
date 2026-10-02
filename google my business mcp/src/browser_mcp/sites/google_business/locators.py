"""Shared locator-discovery helpers for the Google Business Profile adapter.

Google ships unversioned, frequently-restructured markup, so every lookup here
works from an ordered list of candidate selectors and takes the first hit. That
keeps the resilience strategy in one place instead of repeating a bespoke loop
in each module.
"""

from collections.abc import Iterable
from typing import Optional

from playwright.async_api import Locator, Page

from browser_mcp.utils.logging import get_logger

logger = get_logger("google_business.locators")


async def first_visible(candidates: Iterable[Locator]) -> Optional[Locator]:
    """Returns the first candidate that both exists and is visible.

    A broken or stale selector in the list must not abort the search, so each
    candidate is probed defensively and a failure simply moves to the next.
    """
    for candidate in candidates:
        try:
            if await candidate.count() > 0 and await candidate.first.is_visible():
                return candidate.first
        except Exception as e:
            logger.debug(f"Locator probe failed, trying next candidate: {e}")
    return None


async def first_visible_text(page: Page, selectors: Iterable[str]) -> Optional[str]:
    """Returns the stripped text of the first visible element matching a selector."""
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() > 0 and await locator.first.is_visible():
                return (await locator.first.text_content() or "").strip() or None
        except Exception as e:
            logger.debug(f"Text probe failed for {selector!r}: {e}")
    return None


async def text_or_default(page: Page, selectors: Iterable[str], default: str) -> str:
    """Like first_visible_text, but substitutes `default` when nothing matches."""
    return await first_visible_text(page, selectors) or default

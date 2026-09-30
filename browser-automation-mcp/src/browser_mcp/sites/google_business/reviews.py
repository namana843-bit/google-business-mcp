"""Google Business review discovery and public reply automation."""

from typing import Any, Optional

from playwright.async_api import Locator, Page

from browser_mcp.approvals import get_approval_controller
from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult, GoogleBusinessReview
from browser_mcp.sites.base import abort_with_screenshot
from browser_mcp.sites.google_business.locators import first_visible
from browser_mcp.utils.logging import get_logger

logger = get_logger("google_business.reviews")

# Review containers differ between the Google Search merchant view and the
# Business Manager dashboard.
_REVIEW_CONTAINER_SELECTORS = (
    "div[data-review-id]",
    "div[jscontroller][data-id*='review']",
    "div.gws-localreviews__google-review",
    "div[aria-label*='Review by']",
    "div.jftiEf",
)

_AUTHOR_SELECTORS = (".d4r55", ".TSUbDb", "[class*='author']", "div[role='heading']")
_CONTENT_SELECTORS = (".wiI7pd", ".review-full-text", "span[data-expandable]")
_DATE_SELECTORS = (".rsqaWe", "span[class*='date']")
_REPLIED_SELECTORS = ("div.CDe7pd", "div:has-text('Response from the owner')")

_REPLY_TEXTAREA_SELECTORS = (
    "textarea[aria-label*='reply' i]",
    "textarea[placeholder*='reply' i]",
    "div[role='dialog'] textarea",
    "textarea",
)
_REPLY_SUBMIT_SELECTORS = (
    "button:has-text('Post')",
    "button:has-text('Send')",
    "button:has-text('Submit')",
    "div[role='dialog'] button[type='submit']",
)


async def find_reviews(page: Page) -> list[Locator]:
    """Finds review containers across Google Search and Business Manager views."""
    for selector in _REVIEW_CONTAINER_SELECTORS:
        found = page.locator(selector)
        count = await found.count()
        if count > 0:
            return [found.nth(i) for i in range(count)]
    return []


async def find_review_reply_button(review_container: Locator) -> Optional[Locator]:
    """Finds the 'Reply' control within a review, across naming variations."""
    return await first_visible(
        (
            review_container.get_by_role("button", name="Reply", exact=True),
            review_container.get_by_role("button", name="Reply to review"),
            review_container.locator("button:has-text('Reply')"),
            review_container.locator("button[aria-label*='Reply']"),
            review_container.locator("span:has-text('Reply')"),
        )
    )


async def _open_reviews_tab(page: Page) -> None:
    """Clicks through to the reviews view when the page is not already there."""
    tab = await first_visible(
        (
            page.get_by_role("tab", name="Reviews"),
            page.get_by_role("button", name="Read reviews"),
            page.locator("button:has-text('Reviews')"),
            page.locator("a[href*='reviews']"),
        )
    )
    if tab is not None:
        await tab.click()
        await page.wait_for_timeout(1000)


async def _parse_review(element: Locator) -> GoogleBusinessReview:
    """Extracts a single review from its DOM container.

    `review_id` is only populated when the DOM actually carries a
    data-review-id. Minting a synthetic id here would produce a value that
    reply_to_google_business_review cannot resolve, and a loose text fallback
    could attach a public reply to the wrong customer's review.
    """
    author = await _first_text(element, _AUTHOR_SELECTORS) or "Customer"
    content = await _first_text(element, _CONTENT_SELECTORS) or ""
    date = await _first_text(element, _DATE_SELECTORS)
    review_id = await element.get_attribute("data-review-id")

    return GoogleBusinessReview(
        review_id=review_id,
        author=author,
        content=content,
        date=date,
        has_replied=await _any_present(element, _REPLIED_SELECTORS),
    )


async def _any_present(element: Locator, selectors: tuple[str, ...]) -> bool:
    """True if any of the selectors matches inside the container."""
    for selector in selectors:
        if await element.locator(selector).count() > 0:
            return True
    return False


async def _first_text(element: Locator, selectors: tuple[str, ...]) -> Optional[str]:
    """Returns the stripped text of the first matching descendant."""
    for selector in selectors:
        located = element.locator(selector)
        if await located.count() > 0:
            return (await located.first.text_content() or "").strip() or None
    return None


async def get_google_business_reviews(manager: BrowserManager, limit: int = 10) -> ActionResult:
    """Extracts recent customer reviews and their reply status."""
    page = await manager.get_active_page()
    await _open_reviews_tab(page)

    results: list[dict[str, Any]] = []
    for element in (await find_reviews(page))[:limit]:
        try:
            review = await _parse_review(element)
        except Exception as e:
            logger.debug(f"Skipping unreadable review container: {e}")
            continue
        dumped = review.model_dump()
        dumped["addressable"] = review.review_id is not None
        results.append(dumped)

    return ActionResult(
        success=True,
        message=f"Discovered {len(results)} review(s).",
        url=page.url,
        title=await page.title(),
        data={"reviews": results, "total_found": len(results)},
    )


async def reply_to_google_business_review(
    manager: BrowserManager,
    review_id: str,
    reply_text: str,
    approval_id: Optional[str] = None,
) -> ActionResult:
    """Replies publicly to a review, gated on human authorization.

    Both the target review and the submit control are resolved by exact
    identity. Degrading either to a fuzzy text search could publish a public
    reply to the wrong customer, which is irreversible.
    """
    get_approval_controller(manager.db).require_approval_if_needed(
        action_type="review_reply",
        description=f"Post public reply to Google Business review '{review_id}'",
        details={"review_id": review_id, "reply_text": reply_text},
        approval_id=approval_id,
    )

    page = await manager.get_active_page()
    container = page.locator(f"div[data-review-id='{review_id}']").first
    if await container.count() == 0:
        return await abort_with_screenshot(
            manager,
            page,
            f"Review with identifier '{review_id}' could not be found. Only ids "
            "returned by get_google_business_reviews can be replied to.",
        )

    reply_button = await find_review_reply_button(container)
    if not reply_button:
        return await abort_with_screenshot(
            manager,
            page,
            "Reply button not found for this review (it may already be replied to "
            "or disabled).",
        )

    await reply_button.click()
    await page.wait_for_timeout(500)

    textarea = await first_visible(page.locator(s) for s in _REPLY_TEXTAREA_SELECTORS)
    if not textarea:
        return await abort_with_screenshot(
            manager, page, "Reply input textarea did not appear after clicking Reply."
        )

    await textarea.fill(reply_text)
    await page.wait_for_timeout(300)

    submit = await first_visible(page.locator(s) for s in _REPLY_SUBMIT_SELECTORS)
    if not submit:
        return await abort_with_screenshot(manager, page, "Post/Submit button for review reply not found.")

    await submit.click()
    await page.wait_for_timeout(1000)

    manager.db.log_action(
        "google_business_reply_review",
        target_url=page.url,
        profile=manager.active_profile,
        status="SUCCESS",
        details={"review_id": review_id, "reply_length": len(reply_text)},
    )
    return ActionResult(
        success=True,
        message=f"Successfully submitted reply to review '{review_id}'.",
        url=page.url,
        title=await page.title(),
        data={"review_id": review_id, "reply_text": reply_text},
    )


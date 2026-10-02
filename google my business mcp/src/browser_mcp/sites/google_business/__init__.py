"""Google Business Profile site adapter."""

from collections.abc import Awaitable, Callable
from typing import Any

from playwright.async_api import Page

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult
from browser_mcp.sites.base import SiteAdapter
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.sites.google_business.accounts import (
    list_google_business_accounts,
    list_google_business_locations,
)
from browser_mcp.sites.google_business.media import (
    get_google_business_media,
    upload_google_business_media,
)
from browser_mcp.sites.google_business.posts import (
    create_google_business_post,
    create_google_business_post_with_media,
    delete_google_business_post,
)
from browser_mcp.sites.google_business.profile import (
    get_google_business_profile,
    open_google_business,
)
from browser_mcp.sites.google_business.reviews import (
    get_google_business_reviews,
    reply_to_google_business_review,
)

Handler = Callable[[BrowserManager, dict[str, Any]], Awaitable[ActionResult]]


async def _open(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await open_google_business(
        manager,
        business_name=args.get("business_name"),
        profile=args.get("profile"),
    )


async def _get_profile(manager: BrowserManager, _args: dict[str, Any]) -> ActionResult:
    return await get_google_business_profile(manager)


async def _list_accounts(manager: BrowserManager, _args: dict[str, Any]) -> ActionResult:
    return await list_google_business_accounts(manager)


async def _list_locations(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await list_google_business_locations(
        manager, account_name=args.get("account_name", "accounts/me")
    )


async def _get_reviews(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await get_google_business_reviews(manager, limit=args.get("limit", 10))


async def _reply_review(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await reply_to_google_business_review(
        manager,
        review_id=args["review_id"],
        reply_text=args["reply_text"],
        approval_id=args.get("approval_id"),
    )


async def _create_post(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await create_google_business_post(
        manager,
        content=args["content"],
        media_path=args.get("media_path") or args.get("image_path"),
        cta_type=args.get("cta_type"),
        cta_url=args.get("cta_url"),
        approval_id=args.get("approval_id"),
    )


async def _create_post_with_media(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await create_google_business_post_with_media(
        manager,
        content=args["content"],
        media_path=args["media_path"],
        cta_type=args.get("cta_type"),
        cta_url=args.get("cta_url"),
        approval_id=args.get("approval_id"),
    )


async def _delete_post(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await delete_google_business_post(
        manager, post_id=args["post_id"], approval_id=args.get("approval_id")
    )


async def _get_media(manager: BrowserManager, _args: dict[str, Any]) -> ActionResult:
    return await get_google_business_media(manager)


async def _upload_media(manager: BrowserManager, args: dict[str, Any]) -> ActionResult:
    return await upload_google_business_media(
        manager,
        file_path=args["file_path"],
        category=args.get("category"),
        approval_id=args.get("approval_id"),
    )


# Every accepted spelling of an action name maps to the same handler.
_ACTIONS: dict[str, Handler] = {
    "open": _open,
    "open_dashboard": _open,
    "get_profile": _get_profile,
    "profile": _get_profile,
    "list_accounts": _list_accounts,
    "accounts": _list_accounts,
    "list_locations": _list_locations,
    "locations": _list_locations,
    "get_reviews": _get_reviews,
    "reviews": _get_reviews,
    "reply_review": _reply_review,
    "reply_to_review": _reply_review,
    "create_post": _create_post,
    "post": _create_post,
    "create_post_with_media": _create_post_with_media,
    "post_with_media": _create_post_with_media,
    "delete_post": _delete_post,
    "get_media": _get_media,
    "media": _get_media,
    "upload_media": _upload_media,
}


class GoogleBusinessAdapter(SiteAdapter):
    """Site adapter for Google Business Profile automation."""

    name = "google_business"
    base_url = "https://business.google.com/"
    allowed_domains = ["google.com", "business.google.com", "accounts.google.com"]

    async def detect(self, page: Page) -> bool:
        url = page.url.lower()
        return "business.google.com" in url or "google.com/business" in url

    async def open(self, manager: BrowserManager, **kwargs: Any) -> ActionResult:
        return await _open(manager, kwargs)

    async def execute(
        self, manager: BrowserManager, action: str, **kwargs: Any
    ) -> ActionResult:
        handler = _ACTIONS.get(action.lower().replace("-", "_"))
        if handler is None:
            return ActionResult(
                success=False,
                error_type=ErrorCode.INVALID_REQUEST.value,
                message=f"Unknown Google Business action: {action}",
            )
        return await handler(manager, kwargs)


__all__ = [
    "GoogleBusinessAdapter",
    "create_google_business_post",
    "create_google_business_post_with_media",
    "delete_google_business_post",
    "get_google_business_media",
    "get_google_business_profile",
    "get_google_business_reviews",
    "list_google_business_accounts",
    "list_google_business_locations",
    "open_google_business",
    "reply_to_google_business_review",
    "upload_google_business_media",
]

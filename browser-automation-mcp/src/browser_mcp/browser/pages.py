"""Selector parsing, locator resolution, element inspection, and challenge detection."""

from typing import Any, Optional

from playwright.async_api import Locator, Page

from browser_mcp.models.schemas import ElementInfo, ElementSelector, SelectorType
from browser_mcp.utils.errors import ErrorCode
from browser_mcp.utils.logging import get_logger

logger = get_logger("pages")

# Shorthand prefixes accepted in a plain selector string, longest first so that
# "placeholder=" is not shadowed by a shorter key.
_PREFIXES: tuple[tuple[str, SelectorType], ...] = (
    ("placeholder=", SelectorType.PLACEHOLDER),
    ("role=", SelectorType.ROLE),
    ("label=", SelectorType.LABEL),
    ("text=", SelectorType.TEXT),
)

# Visible, interactive challenge widgets. Every one of these is injected as a
# hidden background badge on ordinary pages by most large sites, so presence
# alone must never halt automation - only a rendered, sized element counts.
_CAPTCHA_SELECTORS = (
    "iframe[src*='recaptcha']",
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[src*='hcaptcha.com']",
    "#cf-turnstile",
    ".g-recaptcha",
)

# Below this rendered size a "challenge" is a background badge, not a puzzle.
_MIN_CHALLENGE_PX = 20

# Page titles that interstitial bot-walls use while they solve a challenge.
_CHALLENGE_TITLES = ("just a moment...", "attention required")

_MFA_URL_MARKERS = ("challenge/pwd", "challenge/totp", "two-step-verification", "2step")
_LOGIN_PATH_MARKERS = ("/login", "/signin", "/auth")


def parse_selector(
    selector: Any,
    selector_type: str = "css",
    name: Optional[str] = None,
    exact: bool = False,
) -> Optional[ElementSelector]:
    """Normalises any accepted selector shape into an ElementSelector.

    Agents call these tools using three different conventions, and a strict
    ``selector: str`` annotation rejects the richer forms with a raw pydantic
    validation error. Accepting all of them means a selector mistake is never a
    hard schema failure:

      * ``"text=Submit"``                    -> prefix detected automatically
      * ``"Submit"`` + ``selector_type``    -> explicit type
      * ``"role=button,Save"``              -> role plus accessible name
      * ``{"type": "text", "value": "Sub"}``-> object form

    Returns None for an absent selector so callers can distinguish "no
    selector" from "malformed selector".
    """
    if selector is None or selector == "":
        return None

    if isinstance(selector, ElementSelector):
        return selector

    if isinstance(selector, dict):
        payload = dict(selector)
        payload.setdefault("type", selector_type)
        payload.setdefault("name", name)
        payload.setdefault("exact", exact)
        try:
            return ElementSelector(**payload)
        except Exception as e:
            raise ValueError(f"Invalid selector object {selector!r}: {e}") from e

    value = str(selector).strip()

    for prefix, stype in _PREFIXES:
        if not value.startswith(prefix):
            continue
        body = value[len(prefix):].strip()
        if stype is SelectorType.ROLE and "," in body:
            role, accessible = body.split(",", 1)
            return ElementSelector(
                type=stype,
                value=role.strip(),
                name=accessible.strip() or name,
                exact=exact,
            )
        return ElementSelector(type=stype, value=body, name=name, exact=exact)

    if value.startswith(("//", "(//")):
        return ElementSelector(type=SelectorType.XPATH, value=value, name=name, exact=exact)

    return ElementSelector(type=selector_type, value=value, name=name, exact=exact)


def resolve_locator(page: Page, selector: Any) -> Locator:
    """Resolves a selector of any accepted shape into a Playwright Locator.

    Semantic locators (role/text/label/placeholder) are preferred over raw CSS so
    that markup changes do not break a running automation.
    """
    parsed = parse_selector(selector)
    if parsed is None:
        raise ValueError("A selector is required to resolve a locator")

    match parsed.type:
        case SelectorType.ROLE:
            return page.get_by_role(parsed.value, name=parsed.name, exact=bool(parsed.exact))
        case SelectorType.TEXT:
            return page.get_by_text(parsed.value, exact=bool(parsed.exact))
        case SelectorType.LABEL:
            return page.get_by_label(parsed.value, exact=bool(parsed.exact))
        case SelectorType.PLACEHOLDER:
            return page.get_by_placeholder(parsed.value, exact=bool(parsed.exact))
        case SelectorType.XPATH:
            body = parsed.value.removeprefix("xpath=")
            return page.locator(f"xpath={body}")
        case _:
            return page.locator(parsed.value)


async def inspect_element(locator: Locator) -> ElementInfo:
    """Extracts structured DOM and accessibility information from a locator."""
    count = await locator.count()
    if count == 0:
        return ElementInfo(found=False)

    target = locator.first
    try:
        raw_text = await target.text_content()
        return ElementInfo(
            found=True,
            tag=await target.evaluate("el => el.tagName ? el.tagName.toLowerCase() : null"),
            text=raw_text.strip() if raw_text else None,
            visible=await target.is_visible(),
            enabled=await target.is_enabled(),
            attributes=await target.evaluate(
                """el => Object.fromEntries(
                    Array.from(el.attributes || [], a => [a.name, a.value])
                )"""
            ),
            bounding_box=await target.bounding_box(),
        )
    except Exception as e:
        # The element exists but something about reading it failed (detached
        # mid-inspection, cross-origin node). Report it as present but inert
        # rather than claiming it was never found.
        logger.debug(f"Element inspection partial failure: {e}")
        return ElementInfo(found=True, visible=False, enabled=False)


async def _has_visible_challenge(page: Page) -> bool:
    """True if the page shows a challenge the user must actually solve."""
    for selector in _CAPTCHA_SELECTORS:
        try:
            candidates = page.locator(selector)
            total = await candidates.count()
        except Exception:
            continue
        for i in range(total):
            try:
                element = candidates.nth(i)
                if not await element.is_visible():
                    continue
                box = await element.bounding_box()
                if not box:
                    continue
                if box.get("width", 0) >= _MIN_CHALLENGE_PX and box.get("height", 0) >= _MIN_CHALLENGE_PX:
                    return True
            except Exception:
                continue
    return False


async def _needs_login(page: Page, url: str) -> bool:
    """True if the page is an authentication wall rather than a login link."""
    if "accounts.google.com/signin" in url or "accounts.google.com/v3/signin" in url:
        return True

    if not any(marker in url for marker in ("login", "signin")):
        return False
    if not any(marker in url for marker in _LOGIN_PATH_MARKERS):
        return False

    sign_in_control = page.locator(
        "button:has-text('Sign in'), button:has-text('Log in'), input[type='submit']"
    )
    try:
        return await sign_in_control.count() > 0 and await sign_in_control.first.is_visible()
    except Exception:
        return False


async def detect_page_challenges(page: Page) -> Optional[ErrorCode]:
    """Inspects the page for CAPTCHAs, bot blocks, or login gates.

    Returns the ErrorCode describing the first blocking challenge found, or None
    when the page is safe to keep automating.
    """
    url = page.url.lower()

    if await _needs_login(page, url):
        return ErrorCode.LOGIN_REQUIRED

    if any(marker in url for marker in _MFA_URL_MARKERS):
        return ErrorCode.MFA_REQUIRED

    if await _has_visible_challenge(page):
        return ErrorCode.CAPTCHA_DETECTED

    try:
        title = (await page.title()).lower()
        if any(marker in title for marker in _CHALLENGE_TITLES):
            return ErrorCode.CAPTCHA_DETECTED
    except Exception:
        logger.debug("Could not read page title during challenge detection")

    return None

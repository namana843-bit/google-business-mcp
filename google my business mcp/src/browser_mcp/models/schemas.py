"""Pydantic schemas and data contracts for Browser MCP."""

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class SelectorType(str, Enum):
    """Supported selector flavours, ordered from most to least semantic."""

    ROLE = "role"
    TEXT = "text"
    LABEL = "label"
    PLACEHOLDER = "placeholder"
    CSS = "css"
    XPATH = "xpath"


class ElementSelector(BaseModel):
    """Semantic or query selector specification."""

    type: SelectorType = SelectorType.CSS
    value: str = Field(
        description="The primary selector string (e.g. role name, text pattern, CSS selector, or xpath)"
    )
    name: Optional[str] = Field(
        default=None,
        description="Accessible name filter when using role selectors (e.g., button name 'Reply')",
    )
    exact: Optional[bool] = Field(
        default=False, description="Require an exact match for text/label/placeholder"
    )


# Every public entry point accepts the same three selector shapes: a fully
# built ElementSelector, a raw mapping, or a shorthand string such as
# "text=Submit". Naming the union once keeps that contract in a single place
# instead of repeating it in ~25 signatures.
SelectorInput = Union[ElementSelector, dict[str, Any], str]


class PageInfo(BaseModel):
    """Information about an open browser tab/page."""

    index: int
    url: str
    title: str
    is_active: bool = False


class BrowserStatusResponse(BaseModel):
    """Browser engine status response."""

    running: bool
    profile: Optional[str] = None
    headless: bool = False
    page_count: int = 0
    current_page_index: int = 0
    current_url: Optional[str] = None
    current_title: Optional[str] = None


class ElementInfo(BaseModel):
    """Structured inspection of a discovered DOM element."""

    found: bool
    tag: Optional[str] = None
    text: Optional[str] = None
    visible: bool = False
    enabled: bool = False
    selector: Optional[str] = None
    attributes: Optional[dict[str, str]] = None
    bounding_box: Optional[dict[str, float]] = None


class ActionResult(BaseModel):
    """Standardized response returned by browser actions and MCP tools."""

    success: bool
    error_type: Optional[str] = None
    message: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    screenshot: Optional[str] = None


class ExecuteStep(BaseModel):
    """A single step in an automated browser sequence."""

    action: str = Field(
        description=(
            "Action to perform: navigate, click, fill, type, press, select, "
            "check, uncheck, hover, scroll, wait"
        )
    )
    selector: Optional[SelectorInput] = None
    value: Optional[str] = None
    url: Optional[str] = None
    options: Optional[dict[str, Any]] = None


class ApprovalPolicy(BaseModel):
    """Policy configuring which action categories require human approval."""

    public_posts: bool = True
    review_replies: bool = True
    delete_actions: bool = True
    form_submission: bool = False
    navigation_unrestricted: bool = True


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    # An approval is a single-use capability: once it authorises one action it
    # transitions to CONSUMED so it cannot be replayed.
    CONSUMED = "CONSUMED"


class ApprovalRequest(BaseModel):
    """Record of an action queued for human approval."""

    id: str
    action_type: str
    description: str
    details: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str
    resolved_at: Optional[str] = None


# --- Google Business Profile domain models ---


class GoogleBusinessProfile(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    url: Optional[str] = None


class GoogleBusinessReview(BaseModel):
    review_id: Optional[str] = None
    author: Optional[str] = None
    rating: Optional[int] = None
    date: Optional[str] = None
    content: Optional[str] = None
    reply: Optional[str] = None
    reply_date: Optional[str] = None
    has_replied: bool = False


class GoogleBusinessPost(BaseModel):
    post_id: Optional[str] = None
    content: str
    cta_type: Optional[str] = None
    cta_url: Optional[str] = None
    created_at: Optional[str] = None

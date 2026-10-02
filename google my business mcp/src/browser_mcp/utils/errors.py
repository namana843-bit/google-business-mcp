"""
Custom exception hierarchy and predictable error codes for Browser MCP.
"""

from enum import Enum
from typing import Any, Optional


class ErrorCode(str, Enum):
    """Stable, machine-readable failure identifiers returned to MCP clients."""

    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    NAVIGATION_ERROR = "NAVIGATION_ERROR"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    MFA_REQUIRED = "MFA_REQUIRED"
    BROWSER_NOT_RUNNING = "BROWSER_NOT_RUNNING"
    PROFILE_LOCKED = "PROFILE_LOCKED"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN = "UNKNOWN"


class BrowserMCPError(Exception):
    """Base exception for all Browser MCP errors.

    Each subclass fixes the ErrorCode, so a caller can branch on the failure
    type without parsing the message.
    """

    def __init__(
        self,
        message: str,
        error_type: ErrorCode = ErrorCode.UNKNOWN,
        url: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        screenshot: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.url = url
        self.details = details or {}
        self.screenshot = screenshot

    def to_dict(self) -> dict[str, Any]:
        """Serialises the error into the standard MCP failure payload."""
        result: dict[str, Any] = {
            "success": False,
            "error_type": self.error_type.value,
            "message": self.message,
        }
        if self.url:
            result["url"] = self.url
        if self.details:
            result["details"] = self.details
        if self.screenshot:
            result["screenshot"] = self.screenshot
        return result


class ElementNotFoundError(BrowserMCPError):
    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        selector: Optional[str] = None,
        screenshot: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            error_type=ErrorCode.ELEMENT_NOT_FOUND,
            url=url,
            # `is not None` rather than truthiness: an empty-string selector is
            # a real (if degenerate) value worth reporting.
            details={"selector": selector} if selector is not None else {},
            screenshot=screenshot,
        )


class BrowserTimeoutError(BrowserMCPError):
    def __init__(
        self, message: str, url: Optional[str] = None, timeout_ms: Optional[int] = None
    ):
        super().__init__(
            message=message,
            error_type=ErrorCode.TIMEOUT,
            url=url,
            # timeout_ms=0 means "no wait budget" and must not be erased.
            details={"timeout_ms": timeout_ms} if timeout_ms is not None else {},
        )


class NavigationError(BrowserMCPError):
    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_type=ErrorCode.NAVIGATION_ERROR,
            url=url,
            details=details,
        )


class LoginRequiredError(BrowserMCPError):
    def __init__(
        self,
        message: str = "User authentication is required. Please complete login in the browser.",
        url: Optional[str] = None,
    ):
        super().__init__(message=message, error_type=ErrorCode.LOGIN_REQUIRED, url=url)


class PermissionDeniedError(BrowserMCPError):
    def __init__(
        self, message: str, url: Optional[str] = None, reason: Optional[str] = None
    ):
        super().__init__(
            message=message,
            error_type=ErrorCode.PERMISSION_DENIED,
            url=url,
            details={"reason": reason} if reason else {},
        )


class ApprovalRequiredError(BrowserMCPError):
    def __init__(
        self,
        message: str,
        approval_id: str,
        action: str,
        details: Optional[dict[str, Any]] = None,
    ):
        merged = {"approval_id": approval_id, "action": action}
        if details:
            merged.update(details)
        super().__init__(
            message=message,
            error_type=ErrorCode.APPROVAL_REQUIRED,
            details=merged,
        )


class CaptchaDetectedError(BrowserMCPError):
    def __init__(
        self,
        message: str = "Security challenge or CAPTCHA detected. Human intervention required.",
        url: Optional[str] = None,
    ):
        super().__init__(message=message, error_type=ErrorCode.CAPTCHA_DETECTED, url=url)


class MfaRequiredError(BrowserMCPError):
    def __init__(
        self,
        message: str = (
            "Multi-Factor Authentication (MFA) requested. Complete verification in browser."
        ),
        url: Optional[str] = None,
    ):
        super().__init__(message=message, error_type=ErrorCode.MFA_REQUIRED, url=url)


class BrowserNotRunningError(BrowserMCPError):
    def __init__(
        self,
        message: str = "Browser instance is not running. Please launch the browser first.",
    ):
        super().__init__(message=message, error_type=ErrorCode.BROWSER_NOT_RUNNING)


class ProfileLockedError(BrowserMCPError):
    def __init__(self, profile_name: str, message: Optional[str] = None):
        super().__init__(
            message=message
            or f"Profile '{profile_name}' is locked by another running browser process.",
            error_type=ErrorCode.PROFILE_LOCKED,
            details={"profile": profile_name},
        )


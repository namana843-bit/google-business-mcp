"""Profile sessions and the human-approval MCP tool handlers.

The approval policy itself lives in `browser_mcp.approvals`; it is re-exported
here so existing imports of `browser_mcp.tools.sessions` keep working.
"""

from browser_mcp.approvals import ApprovalController, get_approval_controller
from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult
from browser_mcp.utils.errors import ErrorCode

__all__ = [
    "ApprovalController",
    "browser_approve_action",
    "browser_list_profiles",
    "browser_pending_approvals",
    "get_approval_controller",
]


async def browser_list_profiles(manager: BrowserManager) -> ActionResult:
    """Lists all available persistent browser profile folders."""
    profiles = manager.profile_manager.list_profiles()
    return ActionResult(
        success=True,
        message=f"Found {len(profiles)} profile(s).",
        data={"profiles": profiles},
    )


async def browser_pending_approvals(manager: BrowserManager) -> ActionResult:
    """Lists all approval requests awaiting human authorization."""
    approvals = manager.db.list_pending_approvals()
    return ActionResult(
        success=True,
        message=f"{len(approvals)} action(s) pending human approval.",
        data={"approvals": [a.model_dump() for a in approvals]},
    )


async def browser_approve_action(
    manager: BrowserManager, approval_id: str, approved: bool = True
) -> ActionResult:
    """Resolves an approval request, approving or rejecting the pending action."""
    resolved = manager.db.resolve_approval_request(approval_id, approved)
    if not resolved:
        return ActionResult(
            success=False,
            error_type=ErrorCode.INVALID_REQUEST.value,
            message=f"Approval request '{approval_id}' was not found.",
        )

    decision = "APPROVED" if approved else "REJECTED"
    manager.db.log_action(
        action=f"approval_{decision.lower()}",
        status=decision,
        details={"approval_id": approval_id, "action_type": resolved.action_type},
    )
    return ActionResult(
        success=True,
        message=f"Approval request '{approval_id}' marked as {decision}.",
        data=resolved.model_dump(),
    )

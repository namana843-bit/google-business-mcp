"""Human-in-the-loop approval policy for public, irreversible actions.

This module deliberately sits at the package root rather than under `tools/`:
site adapters (see `browser_mcp.sites`) need to gate their write operations,
and a domain policy should not depend on the tool-transport layer.
"""

import os
from typing import Any, Optional

from browser_mcp.models.schemas import ApprovalPolicy, ApprovalRequest, ApprovalStatus
from browser_mcp.storage.database import DatabaseManager
from browser_mcp.utils.errors import ApprovalRequiredError
from browser_mcp.utils.logging import get_logger

logger = get_logger("approvals")

# Each entry pairs the substrings that identify an action category with the
# policy flag that governs it. Evaluated in order, so a broader term placed
# first wins. Read-only verbs such as "get_media" match nothing here and are
# therefore never gated.
_RISKY_CATEGORIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("post", "publish"), "public_posts"),
    (("upload",), "public_posts"),
    (("reply",), "review_replies"),
    (("delete",), "delete_actions"),
    (("submit",), "form_submission"),
)


class ApprovalController:
    """Decides which actions require human approval, and enforces that approval."""

    def __init__(self, db_manager: DatabaseManager, policy: Optional[ApprovalPolicy] = None):
        self.db = db_manager
        # 'auto' disables gating; 'strict' and 'prompt' gate the same actions.
        self.mode = os.getenv("BROWSER_MCP_APPROVAL_MODE", "strict").lower()
        self.policy = policy or ApprovalPolicy()

    def is_action_risky(self, action_type: str) -> bool:
        """True if the action publishes customer-visible content or destroys data."""
        if self.mode == "auto":
            return False

        action = action_type.lower()
        for keywords, flag in _RISKY_CATEGORIES:
            if any(keyword in action for keyword in keywords):
                return bool(getattr(self.policy, flag))
        return False

    def require_approval_if_needed(
        self,
        action_type: str,
        description: str,
        details: dict[str, Any],
        approval_id: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """Authorises an action, or raises to halt it.

        Without an `approval_id` a PENDING request is recorded and
        ApprovalRequiredError is raised. With one, the request must be APPROVED
        and must match this exact action type and payload; it is then consumed
        so the same id cannot authorise a second action.
        """
        if not self.is_action_risky(action_type):
            return None

        if approval_id is None:
            request = self.db.create_approval_request(action_type, description, details)
            logger.warning(
                f"Action '{action_type}' blocked pending approval. ID: {request.id}"
            )
            raise ApprovalRequiredError(
                message=(
                    f"APPROVAL REQUIRED: Action '{action_type}' requires explicit human "
                    f"authorization. Call 'browser_approve_action(approval_id=\"{request.id}\", "
                    "approved=True)' once approved."
                ),
                approval_id=request.id,
                action=action_type,
                details={"description": description, "parameters": details},
            )

        request = self.db.get_approval_request(approval_id)
        if request is None:
            raise ApprovalRequiredError(
                message=f"Approval request '{approval_id}' not found.",
                approval_id=approval_id,
                action=action_type,
                details=details,
            )
        if request.status == ApprovalStatus.REJECTED:
            raise ApprovalRequiredError(
                message=f"Action '{action_type}' was REJECTED by human operator.",
                approval_id=approval_id,
                action=action_type,
                details={"status": "REJECTED"},
            )
        if request.status != ApprovalStatus.APPROVED:
            raise ApprovalRequiredError(
                message=f"Action '{action_type}' is still PENDING human approval.",
                approval_id=approval_id,
                action=action_type,
                details={"status": request.status.value},
            )
        # An approval is a capability for one action and one payload, not a
        # general-purpose token, so both are re-checked here.
        if request.action_type != action_type:
            raise ApprovalRequiredError(
                message=(
                    f"Approval '{approval_id}' was granted for action "
                    f"'{request.action_type}', not '{action_type}'. Request a new approval."
                ),
                approval_id=approval_id,
                action=action_type,
                details={
                    "approved_for": request.action_type,
                    "status": "ACTION_MISMATCH",
                },
            )
        if request.details != details:
            raise ApprovalRequiredError(
                message=(
                    f"Approval '{approval_id}' was granted for a different payload. "
                    "Request a new approval for these exact parameters."
                ),
                approval_id=approval_id,
                action=action_type,
                details={"status": "PAYLOAD_MISMATCH"},
            )
        # Consume atomically: a second caller that raced us already flipped the
        # row out of APPROVED and now loses.
        if not self.db.consume_approval_request(approval_id):
            raise ApprovalRequiredError(
                message=f"Approval '{approval_id}' has already been used.",
                approval_id=approval_id,
                action=action_type,
                details={"status": "ALREADY_USED"},
            )

        logger.info(f"Action '{action_type}' pre-approved under {approval_id}.")
        return request


_approval_controller: Optional[ApprovalController] = None


def get_approval_controller(db: Optional[DatabaseManager] = None) -> ApprovalController:
    """Returns the process-wide approval controller.

    The cache is keyed on the DatabaseManager instance so a controller is never
    left bound to a different store than the one a caller passed in, which
    would write approvals to and read them from different databases.
    """
    global _approval_controller
    if db is None:
        if _approval_controller is None:
            _approval_controller = ApprovalController(DatabaseManager())
        return _approval_controller

    if _approval_controller is None or _approval_controller.db is not db:
        _approval_controller = ApprovalController(db)
    return _approval_controller

"""
Tests for Human-in-the-Loop approval system and SQLite tracking.
"""

import pytest
from browser_mcp.models.schemas import ApprovalStatus
from browser_mcp.tools.sessions import (
    ApprovalController,
    browser_approve_action,
    browser_pending_approvals,
)
from browser_mcp.utils.errors import ApprovalRequiredError


@pytest.mark.asyncio
async def test_approval_workflow_lifecycle(temp_env):
    db = temp_env["db"]
    manager = temp_env["manager"]
    controller = ApprovalController(db)
    controller.mode = "strict"

    # 1. Trigger risky action without pre-approval
    with pytest.raises(ApprovalRequiredError) as exc_info:
        controller.require_approval_if_needed(
            action_type="review_reply",
            description="Reply to Customer Review #101",
            details={"review_id": "rev-101", "reply_text": "Thank you for visiting!"},
        )

    approval_id = exc_info.value.details["approval_id"]
    assert approval_id.startswith("appr_")

    # 2. Check pending approvals list via tool
    pending_res = await browser_pending_approvals(manager)
    assert pending_res.success is True
    assert len(pending_res.data["approvals"]) == 1
    assert pending_res.data["approvals"][0]["id"] == approval_id
    assert pending_res.data["approvals"][0]["status"] == ApprovalStatus.PENDING.value

    # 3. Approve action
    approve_res = await browser_approve_action(manager, approval_id=approval_id, approved=True)
    assert approve_res.success is True
    assert approve_res.data["status"] == ApprovalStatus.APPROVED.value

    # 4. Re-invoking the SAME action with the SAME payload passes.
    #    The details must match the approved payload exactly; an approval is
    #    bound to one action_type + payload pair.
    approved_req = controller.require_approval_if_needed(
        action_type="review_reply",
        description="Reply to Customer Review #101",
        details={"review_id": "rev-101", "reply_text": "Thank you for visiting!"},
        approval_id=approval_id,
    )
    assert approved_req is not None

    # 5. Approvals are single-use: the request is now CONSUMED, so replaying
    #    the same id is refused even with an identical payload.
    with pytest.raises(ApprovalRequiredError) as replay_info:
        controller.require_approval_if_needed(
            action_type="review_reply",
            description="Reply to Customer Review #101",
            details={"review_id": "rev-101", "reply_text": "Thank you for visiting!"},
            approval_id=approval_id,
        )
    assert replay_info.value.details.get("status") == "CONSUMED"
    # The atomic DB-level guard also refuses a second consumption.
    assert db.consume_approval_request(approval_id) is False


@pytest.mark.asyncio
async def test_consume_is_atomic_single_winner(temp_env):
    """Only one caller can ever consume a given approval id."""
    db = temp_env["db"]
    req = db.create_approval_request("public_post_delete", "delete", {"post_id": "p1"})
    db.resolve_approval_request(req.id, approved=True)

    results = [db.consume_approval_request(req.id) for _ in range(5)]
    assert results.count(True) == 1
    assert results.count(False) == 4
    assert db.get_approval_request(req.id).status.value == "CONSUMED"


@pytest.mark.asyncio
async def test_pending_approval_cannot_be_consumed(temp_env):
    """Consuming a still-PENDING approval must not succeed."""
    db = temp_env["db"]
    req = db.create_approval_request("public_post_delete", "delete", {"post_id": "p1"})
    assert db.consume_approval_request(req.id) is False


# --- BUG: BrowserMCPError dropped falsy-but-meaningful context values ---

def test_error_details_preserve_zero_and_empty_values():
    from browser_mcp.utils.errors import BrowserTimeoutError, ElementNotFoundError

    # timeout_ms=0 is a legitimate budget, not "missing".
    assert BrowserTimeoutError("t", timeout_ms=0).details == {"timeout_ms": 0}
    assert BrowserTimeoutError("t", timeout_ms=None).details == {}
    assert ElementNotFoundError("e", selector="").details == {"selector": ""}
    assert ElementNotFoundError("e", selector=None).details == {}


@pytest.mark.asyncio
async def test_approval_cannot_be_reused_for_a_different_action(temp_env):
    """An approval granted for one action must not authorise another."""
    db = temp_env["db"]
    controller = ApprovalController(db)
    controller.mode = "strict"

    with pytest.raises(ApprovalRequiredError) as exc_info:
        controller.require_approval_if_needed(
            action_type="media_upload",
            description="Upload cat.jpg",
            details={"file_path": "cat.jpg"},
        )
    approval_id = exc_info.value.details["approval_id"]
    db.resolve_approval_request(approval_id, approved=True)

    # Same id, completely different destructive action.
    with pytest.raises(ApprovalRequiredError) as mismatch:
        controller.require_approval_if_needed(
            action_type="public_post_delete",
            description="Delete all posts",
            details={"post_id": "p1"},
            approval_id=approval_id,
        )
    assert mismatch.value.details.get("status") == "ACTION_MISMATCH"

    # Even the same action with a different payload is refused.
    with pytest.raises(ApprovalRequiredError) as payload_mismatch:
        controller.require_approval_if_needed(
            action_type="media_upload",
            description="Upload a different file",
            details={"file_path": "exfiltrate.env"},
            approval_id=approval_id,
        )
    assert payload_mismatch.value.details.get("status") == "PAYLOAD_MISMATCH"


@pytest.mark.asyncio
async def test_resolved_approval_cannot_be_flipped(temp_env):
    """A decided approval must not be re-resolved in the opposite direction."""
    db = temp_env["db"]
    req = db.create_approval_request("public_post_delete", "delete", {"post_id": "p1"})

    assert db.resolve_approval_request(req.id, approved=True) is not None
    # Rejecting afterwards must be refused.
    assert db.resolve_approval_request(req.id, approved=False) is None
    assert db.get_approval_request(req.id).status.value == "APPROVED"

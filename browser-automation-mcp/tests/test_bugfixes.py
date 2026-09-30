"""Regression tests covering the bugs found during the code review."""

import asyncio
import logging
import os
from pathlib import Path

import pytest

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.browser.profiles import ProfileManager
from browser_mcp.storage.database import DatabaseManager
from browser_mcp.tools.sessions import ApprovalController, get_approval_controller
from browser_mcp.utils.errors import ApprovalRequiredError, ProfileLockedError
from browser_mcp.utils.logging import get_logger, setup_logging


# --- BUG: is_running keyed off the tab count, so a live context with zero
# --- tabs looked dead and navigate()/new_page() launched a SECOND context
# --- on the same user_data_dir (double profile lock / orphan context).

class _FakePage:
    def __init__(self, name, context):
        self.name = name
        self.url = f"https://example.com/{name}"
        self._context = context

    async def title(self):
        return self.name

    async def bring_to_front(self):
        pass

    async def close(self):
        # Real Playwright removes the page from context.pages on close.
        if self in self._context.pages:
            self._context.pages.remove(self)


class _FakeContext:
    def __init__(self, n=3):
        self.pages = []
        self.closed = False
        for i in range(n):
            self.pages.append(_FakePage(chr(65 + i), self))

    async def close(self):
        self.closed = True


def _manager(tmp_path):
    return BrowserManager(
        ProfileManager(str(tmp_path / "profiles")),
        DatabaseManager(str(tmp_path / "m.db")),
    )


def test_is_running_true_for_live_context_with_zero_tabs(tmp_path):
    m = _manager(tmp_path)
    m._context = _FakeContext(1)
    m._context.pages = []
    assert m.is_running is True


def test_is_running_false_when_closed(tmp_path):
    m = _manager(tmp_path)
    assert m.is_running is False


def test_close_page_decrements_index_when_closing_below_active(tmp_path):
    m = _manager(tmp_path)
    m._context = _FakeContext(3)  # [A, B, C]
    m._active_page_index = 2  # active is C
    asyncio.run(m.close_page(0))  # close A
    # B and C shift down; active must follow C -> now index 1.
    assert m._active_page_index == 1


def test_close_page_clamps_when_closing_active_tab(tmp_path):
    m = _manager(tmp_path)
    m._context = _FakeContext(3)
    m._active_page_index = 2
    asyncio.run(m.close_page(2))  # close C itself
    assert m._active_page_index == 1


def test_close_stops_playwright_even_without_context(tmp_path):
    """The driver is a separate resource; close() must not leak it."""

    class _FakePW:
        def __init__(self):
            self.stopped = False

        async def stop(self):
            self.stopped = True

    m = _manager(tmp_path)
    m._context = None
    fake_pw = _FakePW()
    m._playwright = fake_pw
    res = asyncio.run(m.close())
    assert res.success is True
    assert fake_pw.stopped is True
    assert m._playwright is None


# --- BUG: get_google_business_reviews() minted synthetic "rev_N" ids that
# --- exist nowhere in the DOM, so replying to them could only fail or, via
# --- a loose :has-text fallback, target the WRONG customer's review.

def test_synthetic_review_ids_are_never_minted():
    import inspect

    from browser_mcp.sites.google_business import reviews as reviews_mod

    src = inspect.getsource(reviews_mod.get_google_business_reviews)
    # No positional fallback id may be generated any more.
    assert 'f"rev_' not in src
    assert "rev_{" not in src


def test_reply_lookup_fails_closed_without_text_fallback():
    import inspect

    from browser_mcp.sites.google_business import reviews as reviews_mod

    src = inspect.getsource(reviews_mod.reply_to_google_business_review)
    # Targeting a public reply must not degrade to a fuzzy text search.
    assert "div:has-text('{review_id}')" not in src


def test_post_delete_fails_closed_without_text_fallback():
    import inspect

    from browser_mcp.sites.google_business import posts as posts_mod

    src = inspect.getsource(posts_mod.delete_google_business_post)
    assert "div:has-text('{post_id}')" not in src




# --- BUG: get_profile_path() created dirs on every call, so read-only queries
# --- and deletes materialised profiles on disk and reported bogus results.

def test_delete_nonexistent_profile_returns_false(tmp_path):
    pm = ProfileManager(str(tmp_path))
    assert pm.delete_profile("never_created") is False
    # Must not have created anything on disk.
    assert os.listdir(tmp_path) == []


def test_delete_default_via_traversal_name_is_refused(tmp_path):
    pm = ProfileManager(str(tmp_path))
    pm.get_profile_path("default")  # materialise the real default profile
    assert (tmp_path / "default").exists()

    # ".." sanitises to "" which used to fall back to "default" and delete it.
    assert pm.delete_profile("..") is False
    assert (tmp_path / "default").exists()


def test_get_profile_path_readonly_does_not_create(tmp_path):
    pm = ProfileManager(str(tmp_path))
    pm.get_profile_path("ghost", create=False)
    assert not (tmp_path / "ghost").exists()


def test_is_profile_locked_does_not_create(tmp_path):
    pm = ProfileManager(str(tmp_path))
    assert pm.is_profile_locked("ghost") is False
    assert not (tmp_path / "ghost").exists()


def test_delete_existing_profile(tmp_path):
    pm = ProfileManager(str(tmp_path))
    pm.get_profile_path("work")
    assert pm.delete_profile("work") is True
    assert not (tmp_path / "work").exists()


def test_profile_path_cannot_escape_base_dir(tmp_path):
    pm = ProfileManager(str(tmp_path))
    resolved = pm.get_profile_path("../../etc", create=False)
    assert str(resolved).startswith(str(tmp_path))


# --- BUG: a relative BROWSER_MCP_PROFILE_DIR (e.g. "./profiles") was resolved
# --- against the process CWD. MCP clients start the server from many different
# --- directories, so each run silently created a brand-new empty profile and
# --- threw away every saved Google login. Relative paths must anchor to the
# --- project root so one profile is always reused.

def test_relative_profile_dir_is_anchored_to_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # simulate a client launching from elsewhere
    monkeypatch.setenv("BROWSER_MCP_PROFILE_DIR", "./profiles")
    monkeypatch.delenv("BROWSER_MCP_PROFILE_PATH", raising=False)

    pm = ProfileManager()
    assert pm.base_dir.is_absolute()
    # Not under the (changed) CWD, and always the same project-local location.
    assert tmp_path not in pm.base_dir.parents
    assert pm.base_dir.name == "profiles"
    assert pm.base_dir == ProfileManager().base_dir


def test_absolute_profile_dir_is_respected(monkeypatch, tmp_path):
    target = tmp_path / "my_profiles"
    monkeypatch.setenv("BROWSER_MCP_PROFILE_DIR", str(target))
    monkeypatch.delenv("BROWSER_MCP_PROFILE_PATH", raising=False)

    pm = ProfileManager()
    assert pm.base_dir == target.resolve()
    assert target.exists()


def test_profile_dir_env_ignores_surrounding_quotes_and_spaces(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROWSER_MCP_PROFILE_DIR", '  "./profiles"  ')
    monkeypatch.delenv("BROWSER_MCP_PROFILE_PATH", raising=False)

    assert ProfileManager().base_dir.name == "profiles"


def test_db_path_relative_is_anchored_to_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROWSER_MCP_DB_PATH", "./state.db")

    db = DatabaseManager()
    assert Path(db.db_path).is_absolute()
    assert Path(db.db_path).name == "state.db"
    assert Path(db.db_path).exists()


# --- BUG: check_or_throw_locked() was a no-op `pass`, so PROFILE_LOCKED was
# --- never raised and concurrent launches silently corrupted the profile.

def test_check_or_throw_locked_raises_when_locked(tmp_path):
    pm = ProfileManager(str(tmp_path))
    (tmp_path / "busy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "busy" / "lockfile").write_text("locked")

    assert pm.is_profile_locked("busy") is True
    with pytest.raises(ProfileLockedError):
        pm.check_or_throw_locked("busy")


def test_check_or_throw_locked_passes_when_unlocked(tmp_path):
    pm = ProfileManager(str(tmp_path))
    pm.get_profile_path("free")
    pm.check_or_throw_locked("free")  # must not raise


def test_resolve_target_with_chrome_subprofile(tmp_path, monkeypatch):
    user_data = tmp_path / "User Data"
    user_data.mkdir()
    (user_data / "Local State").write_text("{}")
    p8 = user_data / "Profile 8"
    p8.mkdir()

    monkeypatch.setenv("BROWSER_MCP_PROFILE_PATH", str(p8))
    pm = ProfileManager(str(tmp_path))
    root, prof = pm.resolve_target("Profile 8")
    assert root == user_data.resolve()
    assert prof == "Profile 8"


def test_resolve_target_with_chrome_root(tmp_path, monkeypatch):
    user_data = tmp_path / "User Data"
    user_data.mkdir()
    (user_data / "Local State").write_text("{}")

    monkeypatch.setenv("BROWSER_MCP_PROFILE_DIR", str(user_data))
    monkeypatch.setenv("BROWSER_MCP_DEFAULT_PROFILE", "Profile 8")
    monkeypatch.delenv("BROWSER_MCP_PROFILE_PATH", raising=False)
    pm = ProfileManager(str(user_data))
    root, prof = pm.resolve_target("Profile 8")
    assert root == user_data.resolve()
    assert prof == "Profile 8"


# --- BUG: `with sqlite3.connect(...)` never closes the handle, leaking file
# --- descriptors until the DB reported "database is locked".

def test_database_operations_do_not_leak_connections(tmp_path):
    db = DatabaseManager(str(tmp_path / "t.db"))
    for i in range(300):
        db.log_action("act", f"https://example.com/{i}")
    # If handles leaked, an exclusive lock would be starved; with proper
    # closing this must succeed.
    with db._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")


def test_approval_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "a.db"))
    req = db.create_approval_request("public_post_create", "publish", {"x": 1})
    assert db.get_approval_request(req.id) is not None
    assert len(db.list_pending_approvals()) == 1
    resolved = db.resolve_approval_request(req.id, approved=True)
    assert resolved is not None and resolved.status.value == "APPROVED"
    assert db.list_pending_approvals() == []


# --- BUG: setup_logging() returned early before applying the requested level,
# --- so setup_logging("DEBUG") after any get_logger() call was a silent no-op.

def test_setup_logging_level_applies_after_initialisation():
    get_logger("force-init")  # initialises the package logger at import time
    assert setup_logging("DEBUG").level == logging.DEBUG
    assert setup_logging("WARNING").level == logging.WARNING


def test_setup_logging_rejects_non_numeric_level():
    assert setup_logging("NOT_A_LEVEL").level == logging.INFO


# --- BUG: is_action_risky required "post" AND "create", and media uploads
# --- matched nothing at all, so public content went out without approval.

@pytest.mark.parametrize(
    "action",
    [
        "public_post_create",
        "public_post_delete",
        "create_post",
        "review_reply",
        "media_upload",
        "delete_google_business_post",
    ],
)
def test_risky_actions_require_approval(tmp_path, action):
    ctrl = ApprovalController(DatabaseManager(str(tmp_path / "p.db")))
    assert ctrl.is_action_risky(action) is True


@pytest.mark.parametrize("action", ["get_reviews", "get_profile", "navigate", "get_media"])
def test_read_only_actions_are_not_risky(tmp_path, action):
    ctrl = ApprovalController(DatabaseManager(str(tmp_path / "p.db")))
    assert ctrl.is_action_risky(action) is False


def test_auto_mode_disables_gating(tmp_path):
    os.environ["BROWSER_MCP_APPROVAL_MODE"] = "auto"
    try:
        ctrl = ApprovalController(DatabaseManager(str(tmp_path / "p.db")))
        assert ctrl.is_action_risky("public_post_create") is False
    finally:
        os.environ.pop("BROWSER_MCP_APPROVAL_MODE", None)


def test_risky_action_raises_and_records_pending(tmp_path):
    db = DatabaseManager(str(tmp_path / "ap.db"))
    ctrl = ApprovalController(db)

    with pytest.raises(ApprovalRequiredError):
        ctrl.require_approval_if_needed("public_post_create", "publish", {"content_preview": "hi"})

    pending = db.list_pending_approvals()
    assert len(pending) == 1
    db.resolve_approval_request(pending[0].id, approved=True)
    # Must re-supply the exact payload that was approved.
    assert ctrl.require_approval_if_needed(
        "public_post_create", "publish", {"content_preview": "hi"}, approval_id=pending[0].id
    ) is not None


# --- BUG: the global approval controller ignored the db argument after the
# --- first call, binding approvals to the wrong database.

def test_approval_controller_respects_db_argument(tmp_path):
    import browser_mcp.tools.sessions as sessions

    sessions._approval_controller = None
    db_a = DatabaseManager(str(tmp_path / "a.db"))
    db_b = DatabaseManager(str(tmp_path / "b.db"))
    try:
        assert get_approval_controller(db_a).db is db_a
        assert get_approval_controller(db_b).db is db_b
    finally:
        sessions._approval_controller = None

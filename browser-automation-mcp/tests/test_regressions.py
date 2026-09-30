"""Regression tests for the correctness fixes applied during the cleanup.

Each test here pins a behaviour that was previously wrong, so the defect cannot
silently return.
"""

import pytest

from browser_mcp.browser.pages import parse_selector, resolve_locator
from browser_mcp.models.schemas import SelectorType
from browser_mcp.utils.errors import BrowserMCPError, ErrorCode

# ---------------------------------------------------------------------------
# BUG: wait() used `elif seconds:`, so an explicit seconds=0 was treated as
# "no wait requested" and silently fell through to waiting on DOM load. Callers
# that compute a delay could not express "do not wait at all".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_honours_explicit_zero_seconds(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    result = await manager.wait(seconds=0)

    assert result.success is True
    assert result.message == "Waited for 0 seconds."


@pytest.mark.asyncio
async def test_wait_without_arguments_still_waits_for_dom(temp_env, test_site_url):
    manager = temp_env["manager"]
    await manager.launch(headless=True)
    await manager.navigate(test_site_url)

    result = await manager.wait()

    assert result.success is True
    assert result.message == "Waited for DOM content loaded."


# ---------------------------------------------------------------------------
# BUG: every MCP tool wrapper invented its own error code for an unhandled
# exception, so the same failure reported TIMEOUT from browser_wait,
# NAVIGATION_ERROR from browser_navigate, and UNKNOWN from the other two dozen
# tools. A client could not branch on error_type.
# ---------------------------------------------------------------------------


class _Boom(BrowserMCPError):
    """A typed failure used to prove the code is taken from the exception."""

    def __init__(self):
        super().__init__(message="boom", error_type=ErrorCode.PERMISSION_DENIED)


@pytest.mark.asyncio
async def test_typed_error_keeps_its_own_code_through_the_tool_guard(monkeypatch):
    from browser_mcp import server

    async def failing(*_args, **_kwargs):
        raise _Boom()

    monkeypatch.setattr(server, "get_manager", lambda: object())

    result = await server._call(failing)

    assert result["success"] is False
    assert result["error_type"] == ErrorCode.PERMISSION_DENIED.value
    assert result["message"] == "boom"


@pytest.mark.asyncio
async def test_untyped_error_falls_back_to_unknown(monkeypatch):
    from browser_mcp import server

    async def failing(*_args, **_kwargs):
        raise RuntimeError("untyped failure")

    monkeypatch.setattr(server, "get_manager", lambda: object())

    result = await server._call(failing)

    assert result["success"] is False
    assert result["error_type"] == ErrorCode.UNKNOWN.value
    assert result["message"] == "untyped failure"


@pytest.mark.asyncio
async def test_malformed_selector_is_a_tool_error_not_a_crash(monkeypatch):
    """Selector parsing happens inside the guard, so a bad object is reported
    rather than raised out of the tool and breaking the MCP response."""
    from browser_mcp import server

    monkeypatch.setattr(server, "get_manager", lambda: object())

    async def should_not_run(*_args, **_kwargs):
        raise AssertionError("operation must not be reached")

    result = await server._call(should_not_run, selector={"type": "not-a-real-type"})

    assert result["success"] is False
    assert "Invalid selector object" in result["message"]


@pytest.mark.asyncio
async def test_tool_guard_normalises_model_and_list_results(monkeypatch):
    from browser_mcp import server
    from browser_mcp.models.schemas import ActionResult, PageInfo

    monkeypatch.setattr(server, "get_manager", lambda: object())

    async def returns_model(*_args, **_kwargs):
        return ActionResult(success=True, message="ok")

    async def returns_list(*_args, **_kwargs):
        return [PageInfo(index=0, url="https://example.com", title="Example")]

    assert (await server._call(returns_model)) == {
        "success": True,
        "error_type": None,
        "message": "ok",
        "url": None,
        "title": None,
        "data": None,
        "screenshot": None,
    }

    listed = await server._call(returns_list)
    assert listed["count"] == 1
    assert listed["pages"][0]["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# BUG: the site adapters imported the approval controller from
# browser_mcp.tools.sessions, inverting the dependency direction so the domain
# layer depended on the MCP transport layer. The policy now lives at the
# package root; the old import path must keep working for existing callers.
# ---------------------------------------------------------------------------


def test_approval_controller_lives_above_the_tool_layer():
    import browser_mcp.approvals as approvals
    import browser_mcp.tools.sessions as sessions

    assert sessions.ApprovalController is approvals.ApprovalController
    assert sessions.get_approval_controller is approvals.get_approval_controller


def test_site_adapters_do_not_import_from_the_tool_layer():
    from pathlib import Path

    import browser_mcp.sites.google_business as pkg

    offenders = [
        path.name
        for path in Path(pkg.__file__).parent.glob("*.py")
        if "browser_mcp.tools" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"site adapters must not depend on tools/: {offenders}"


# ---------------------------------------------------------------------------
# Selector parsing is the single source of truth for every accepted shorthand
# form; the MCP layer and the browser layer must agree on all of them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_type", "expected_value"),
    [
        ("text=Submit", SelectorType.TEXT, "Submit"),
        ("label=Email", SelectorType.LABEL, "Email"),
        ("placeholder=Type here", SelectorType.PLACEHOLDER, "Type here"),
        ("//div[@id='x']", SelectorType.XPATH, "//div[@id='x']"),
        ("(//button)[1]", SelectorType.XPATH, "(//button)[1]"),
        ("#submit-btn", SelectorType.CSS, "#submit-btn"),
    ],
)
def test_parse_selector_prefix_forms(raw, expected_type, expected_value):
    parsed = parse_selector(raw)
    assert parsed is not None
    assert parsed.type == expected_type
    assert parsed.value == expected_value


def test_parse_selector_splits_role_and_accessible_name():
    parsed = parse_selector("role=button,Save changes")
    assert parsed.type == SelectorType.ROLE
    assert parsed.value == "button"
    assert parsed.name == "Save changes"


def test_parse_selector_placeholder_is_not_shadowed_by_a_shorter_prefix():
    parsed = parse_selector("placeholder=Search")
    assert parsed.type == SelectorType.PLACEHOLDER
    assert parsed.value == "Search"


def test_parse_selector_distinguishes_absent_from_malformed():
    assert parse_selector(None) is None
    assert parse_selector("") is None
    with pytest.raises(ValueError):
        parse_selector({"type": "nonsense", "value": "x"})


def test_parse_selector_object_form_inherits_defaults():
    parsed = parse_selector({"value": "Save"}, selector_type="text", exact=True)
    assert parsed.type == SelectorType.TEXT
    assert parsed.value == "Save"
    assert parsed.exact is True


def test_resolve_locator_accepts_every_documented_form():
    class _Recorder:
        def __init__(self):
            self.calls = []

        def locator(self, value):
            self.calls.append(("locator", value))
            return value

        def get_by_role(self, role, name=None, exact=False):
            self.calls.append(("role", role, name, exact))
            return role

        def get_by_text(self, value, exact=False):
            self.calls.append(("text", value, exact))
            return value

        def get_by_label(self, value, exact=False):
            self.calls.append(("label", value, exact))
            return value

        def get_by_placeholder(self, value, exact=False):
            self.calls.append(("placeholder", value, exact))
            return value

    for raw, expected in [
        ("text=Save", ("text", "Save", False)),
        ("role=button,Save", ("role", "button", "Save", False)),
        ("label=Email", ("label", "Email", False)),
        ("placeholder=Find", ("placeholder", "Find", False)),
        ("//div", ("locator", "xpath=//div")),
        ("xpath=//div", ("locator", "xpath=//div")),
        ("#id", ("locator", "#id")),
    ]:
        recorder = _Recorder()
        resolve_locator(recorder, raw)
        assert recorder.calls == [expected], f"{raw!r} resolved unexpectedly"

    with pytest.raises(ValueError):
        resolve_locator(_Recorder(), None)


def test_split_user_data_and_profile_handles_subprofile(tmp_path):
    from browser_mcp.browser.profiles import split_user_data_and_profile

    user_data = tmp_path / "User Data"
    user_data.mkdir()
    (user_data / "Local State").write_text("{}")
    p8 = user_data / "Profile 8"
    p8.mkdir()

    root, prof = split_user_data_and_profile(p8)
    assert root == user_data
    assert prof == "Profile 8"


def test_split_user_data_and_profile_handles_root(tmp_path):
    from browser_mcp.browser.profiles import split_user_data_and_profile

    user_data = tmp_path / "User Data"
    user_data.mkdir()
    (user_data / "Local State").write_text("{}")

    root, prof = split_user_data_and_profile(user_data, default_subprofile="Profile 2")
    assert root == user_data
    assert prof == "Profile 2"


def test_resolve_target_honours_direct_absolute_path(tmp_path):
    from browser_mcp.browser.profiles import ProfileManager

    pm = ProfileManager(str(tmp_path / "profiles"))
    custom_dir = tmp_path / "custom_user_dir"

    root, prof = pm.resolve_target(str(custom_dir), create=True)
    assert root == custom_dir.resolve()
    assert prof is None
    assert custom_dir.exists()


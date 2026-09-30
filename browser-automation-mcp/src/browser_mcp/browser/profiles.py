"""
Profile management for persistent Chromium contexts.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from browser_mcp.utils.errors import ProfileLockedError
from browser_mcp.utils.logging import get_logger

logger = get_logger("profiles")

# A name that sanitises to nothing (e.g. "..", "/", "  ") resolves to the
# default profile; callers use this to refuse ambiguous or destructive requests.
_DEFAULT_NAME = "default"

# src/browser_mcp/browser/profiles.py sits three levels below the project root.
# Relative profile paths anchor here rather than to the process CWD, so the
# same profile is reused no matter which directory the MCP client starts from.
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]

# Directory names that identify a real Chrome/Chromium user-data root rather
# than an isolated profile this tool created.
_USER_DATA_ROOT_NAMES = ("user data", "google-chrome", "chromium")

# Chromium leaves a lock marker behind on abnormal exit, so a marker file alone
# does not prove a browser is *currently* using the profile. Matched
# case-insensitively so Windows "LOCK" and POSIX "lockfile" both count.
_LOCK_MARKERS = ("lockfile", "lock", "singletonlock", "singletoncookie", "singletonsocket")

# Characters allowed to survive in a profile name. This also neutralises
# traversal sequences such as "..", "../etc" and embedded slashes.
_NAME_SAFE_CHARS = ("-", "_", " ")

_BROWSER_PROCESS_NAMES = ("chrome", "chromium", "msedge", "headless_shell")


def _resolve_profile_dir(raw: str) -> Path:
    """Turns a configured profile dir into an absolute, stable path."""
    path = Path(raw.strip().strip('"').strip("'")).expanduser()
    return path if path.is_absolute() else (_PACKAGE_ROOT / path).resolve()


def _clean_path(raw: str) -> Path:
    """Parses a path value, tolerating stray quotes and whitespace."""
    return Path(raw.strip().strip('"').strip("'"))


def _is_user_data_root(path: Path) -> bool:
    """True if the path looks like a real Chrome/Chromium user-data root."""
    return (path / "Local State").exists() or path.name.lower() in _USER_DATA_ROOT_NAMES



def split_user_data_and_profile(
    path: Path, default_subprofile: Optional[str] = None
) -> tuple[Path, Optional[str]]:
    """Splits an arbitrary profile path into (user_data_dir, profile_directory)."""
    is_named_subprofile = path.name.startswith("Profile ") or (
        path.name.lower() == _DEFAULT_NAME
    )
    parent = path.parent
    inside_user_data = _is_user_data_root(parent)

    if is_named_subprofile and inside_user_data:
        return parent, path.name

    if _is_user_data_root(path):
        sub = default_subprofile if (default_subprofile and default_subprofile != _DEFAULT_NAME) else None
        return path, sub

    return path, None


class ProfileManager:
    """Manages persistent browser profiles and user data directories."""

    def __init__(self, base_dir: Optional[str] = None):
        direct = os.getenv("BROWSER_MCP_PROFILE_PATH")
        self.direct_profile_path: Optional[Path] = (
            _clean_path(direct).resolve() if direct else None
        )
        self.default_profile = os.getenv("BROWSER_MCP_DEFAULT_PROFILE", _DEFAULT_NAME)
        self.base_dir = _resolve_profile_dir(
            base_dir or os.getenv("BROWSER_MCP_PROFILE_DIR", "./profiles")
        )
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(
            f"ProfileManager base dir: {self.base_dir}, "
            f"direct profile: {self.direct_profile_path}"
        )

    def _sanitize(self, profile_name: str) -> str:
        """Normalises a profile name to a safe directory name.

        Returns "" when the input contains nothing usable, so callers can decide
        whether to fall back to the default or reject the request.
        """
        return "".join(
            c for c in profile_name.strip() if c.isalnum() or c in _NAME_SAFE_CHARS
        )

    def _names_the_direct_path(self, profile_name: str) -> bool:
        """True if this request should resolve to the configured direct path."""
        if not self.direct_profile_path:
            return False
        return profile_name in (
            _DEFAULT_NAME,
            self.default_profile,
            self.direct_profile_path.name,
        )

    def get_profile_path(
        self, profile_name: str = _DEFAULT_NAME, create: bool = True
    ) -> Path:
        """Returns the sanitized filesystem path for a named profile.

        Pass ``create=False`` for read-only operations (listing, inspecting,
        checking locks) so that querying a profile never materialises it on
        disk. The returned path is always guaranteed to be inside base_dir.
        """
        if self._names_the_direct_path(profile_name):
            if create and self.direct_profile_path:
                self.direct_profile_path.mkdir(parents=True, exist_ok=True)
            return self.direct_profile_path

        # An absolute path to a profile directory is honoured as-is, but must
        # still be inside the managed profile root or a declared direct path
        # to prevent pointing Chrome at arbitrary system directories.
        candidate = _clean_path(profile_name)
        if candidate.is_absolute():
            if create:
                candidate.mkdir(parents=True, exist_ok=True)
            resolved = candidate.resolve()
            if self.direct_profile_path and resolved == self.direct_profile_path.resolve():
                return resolved
            if self.base_dir.resolve() in resolved.parents or resolved == self.base_dir.resolve():
                return resolved
            raise ValueError(f"Invalid profile path: {profile_name!r}")

        profile_path = (self.base_dir / (self._sanitize(profile_name) or _DEFAULT_NAME)).resolve()

        # Defence in depth: never escape the managed profile root.
        if self.base_dir not in profile_path.parents and profile_path != self.base_dir:
            raise ValueError(f"Invalid profile name: {profile_name!r}")

        if create:
            profile_path.mkdir(parents=True, exist_ok=True)
        return profile_path

    def resolve_target(
        self, profile_name: Optional[str] = None, create: bool = False
    ) -> tuple[Path, Optional[str]]:
        """Resolves the user_data_dir and optional profile_directory for Chrome.

        Points a real Chrome installation at the shared user-data root plus the
        matching ``--profile-directory``, and everything else at a self-contained
        directory owned entirely by this tool.
        """
        target = profile_name or self.default_profile or _DEFAULT_NAME

        # If profile_name is an explicit absolute path, honor it directly
        candidate = _clean_path(target)
        if candidate.is_absolute():
            if create:
                candidate.mkdir(parents=True, exist_ok=True)
            return split_user_data_and_profile(candidate.resolve(), self.default_profile)

        if self.direct_profile_path and (
            profile_name is None or self._names_the_direct_path(profile_name)
        ):
            return self._resolve_direct_path()

        if _is_user_data_root(self.base_dir):
            return self.base_dir, self._sanitize(target) or None

        profile_path = self.get_profile_path(target, create=create)
        return split_user_data_and_profile(profile_path, self.default_profile)

    def _resolve_direct_path(self) -> tuple[Path, Optional[str]]:
        """Splits a configured direct path into (user_data_dir, profile_directory)."""
        if not self.direct_profile_path:
            return self.base_dir, None
        return split_user_data_and_profile(self.direct_profile_path, self.default_profile)

    def _has_lock_marker(self, directory: Path) -> bool:
        """True if this exact directory holds any Chromium lock marker."""
        if not directory.is_dir():
            return False
        try:
            entries = {e.name.lower() for e in directory.iterdir()}
        except OSError:
            return False
        return any(marker in entries for marker in _LOCK_MARKERS)

    def _is_browser_running(self) -> bool:
        """Best-effort check for a live Chromium/Chrome process.

        Distinguishes a real lock (a browser running right now that would fight
        us for the profile) from a stale marker left by a previous crash.
        Returns True when we cannot tell, so a genuine lock is never dismissed.
        """
        try:
            if os.name == "nt":
                listing = subprocess.run(
                    ["tasklist", "/fo", "csv", "/nh"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.lower()
                running_images = {
                    line.split(",")[0].replace('"', '').strip().lower()
                    for line in listing.splitlines()
                    if line.strip()
                }
                return any(
                    proc in running_images
                    for proc in ("chrome.exe", "chromium.exe", "headless_shell.exe")
                )
            else:
                listing = subprocess.run(
                    ["ps", "-eo", "comm="],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.lower()
                running_procs = {
                    line.strip().lower() for line in listing.splitlines() if line.strip()
                }
                return any(
                    proc in running_procs
                    for proc in ("chrome", "chromium", "headless_shell")
                )
        except Exception:
            return True

    def is_profile_locked(self, profile_name: str) -> bool:
        """True if a running browser process currently holds the profile.

        A marker file that survived an unclean shutdown is *not* treated as an
        active lock; without this, every profile reports PROFILE_LOCKED forever
        after the first crash, making every browser tool unusable.
        """
        user_data_dir, profile_dir = self.resolve_target(profile_name, create=False)
        if not user_data_dir.exists():
            return False

        # A sub-profile inherits the lock state of the user-data root that owns
        # it, so check the sub-profile first and fall back to the root.
        candidates = ([user_data_dir / profile_dir] if profile_dir else []) + [user_data_dir]
        if not any(self._has_lock_marker(d) for d in candidates):
            return False

        # If a lock marker is found, verify if Chrome/Chromium is actually running
        if not self._is_browser_running():
            return False

        # If Chrome is running on Windows, verify if the lock file is genuinely locked by OS handle
        if os.name == "nt":
            for d in candidates:
                for marker in _LOCK_MARKERS:
                    lf = d / marker
                    if lf.exists():
                        try:
                            with open(lf, "r+b"):
                                pass
                        except PermissionError:
                            return True
                        except OSError:
                            pass
            return False

        return True

    def check_or_throw_locked(self, profile_name: str) -> None:
        """Raises ProfileLockedError if the profile is locked by another process."""
        if self.is_profile_locked(profile_name):
            raise ProfileLockedError(profile_name)

    def list_profiles(self) -> list[str]:
        """Lists all existing profile directories."""
        if not self.base_dir.exists():
            return []
        return sorted(
            p.name
            for p in self.base_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def delete_profile(self, profile_name: str) -> bool:
        """Deletes a profile directory and its database metadata.

        Returns False when the profile does not exist or the name is invalid.
        Refuses a name that sanitises to nothing (e.g. ".."), which would
        otherwise resolve to - and delete - the default profile.
        """
        if not self._sanitize(profile_name):
            logger.warning(f"Refusing to delete profile with invalid name: {profile_name!r}")
            return False

        profile_path = self.get_profile_path(profile_name, create=False)
        if not profile_path.exists():
            return False

        shutil.rmtree(profile_path, ignore_errors=True)
        logger.info(f"Deleted profile directory: {profile_path}")

        try:
            from browser_mcp.storage.database import DatabaseManager
            db = DatabaseManager()
            with db._connection() as conn:
                conn.execute("DELETE FROM profiles WHERE name = ?", (profile_name,))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to delete profile metadata for '{profile_name}': {e}")

        return True

"""
Pytest configuration and shared fixtures for Browser MCP test suite.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure local source tree is imported
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import pytest_asyncio

from browser_mcp.browser.manager import BrowserManager
from browser_mcp.browser.profiles import ProfileManager
from browser_mcp.storage.database import DatabaseManager


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "test_site"


@pytest.fixture(scope="session")
def test_site_url(fixtures_dir: Path) -> str:
    index_file = (fixtures_dir / "index.html").resolve()
    return index_file.as_uri()


@pytest.fixture(scope="session")
def login_site_url(fixtures_dir: Path) -> str:
    login_file = (fixtures_dir / "login.html").resolve()
    return login_file.as_uri()


@pytest_asyncio.fixture
async def temp_env():
    """Provides isolated temporary directories for database and profiles."""
    temp_dir = tempfile.mkdtemp(prefix="browser_mcp_test_")
    db_path = os.path.join(temp_dir, "test.db")
    profiles_dir = os.path.join(temp_dir, "profiles")

    db = DatabaseManager(db_path=db_path)
    pm = ProfileManager(base_dir=profiles_dir)
    manager = BrowserManager(profile_manager=pm, db_manager=db)

    # Enforce headless mode for automated testing
    manager._headless = True

    try:
        yield {
            "temp_dir": temp_dir,
            "db": db,
            "pm": pm,
            "manager": manager,
        }
    finally:
        if manager.is_running:
            await manager.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent
load_dotenv(project_root / ".env")
load_dotenv()

# Requires the package to be installed in editable mode:
#   pip install -e .
from browser_mcp.server import get_manager
from browser_mcp.tools.browser import browser_launch
from browser_mcp.sites.google_business import open_google_business
from browser_mcp.tools.screenshot import browser_screenshot

async def main():
    manager = get_manager()
    profile = sys.argv[2] if len(sys.argv) > 2 else "default"
    screenshot_path = sys.argv[1] if len(sys.argv) > 1 else str(project_root / "login.png")

    await browser_launch(manager, profile=profile, headless=True)
    await open_google_business(manager)
    
    # Wait a few seconds for the page to load
    await asyncio.sleep(5)
    
    await browser_screenshot(manager, full_page=True, path=screenshot_path)
    print(f"Screenshot saved to {screenshot_path}")
    
    await manager.close()

if __name__ == "__main__":
    asyncio.run(main())

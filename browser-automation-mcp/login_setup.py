import asyncio
import os
import sys
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


async def main():
    profile = sys.argv[1] if len(sys.argv) > 1 else os.getenv("BROWSER_MCP_DEFAULT_PROFILE", "default")
    print(f"Connecting to Browser Manager (Target Profile: '{profile}')...")
    manager = get_manager()

    try:
        print(f"Launching visible Chrome browser using profile '{profile}'...")
        res = await browser_launch(manager, profile=profile, headless=False)
        if not res.success:
            print(f"Browser launch failed: {res.message}")
            return

        print("Navigating to Google Business Profile...")
        nav_res = await open_google_business(manager)
        print(f"Navigation status: {nav_res.message}")

        print("\n" + "=" * 60)
        print("🔔 CHROME IS NOW OPEN! PLEASE LOG IN TO GOOGLE 🔔")
        print(f"Profile: {profile}")
        print("The browser will remain open for up to 10 minutes.")
        print("Once login is completed, your session is saved permanently.")
        print("=" * 60 + "\n")

        # Smart wait loop: checks every 2 seconds for successful login or browser window close
        login_success = False
        for step in range(300):  # 10 minutes total
            await asyncio.sleep(2)
            try:
                if not manager.is_running or not manager.status().current_url:
                    print("Browser window closed or context lost.")
                    break
                url = manager.status().current_url.lower()
                # If redirected to Google Business dashboard or Google dashboard away from signin
                if ("business.google.com" in url or "google.com/business" in url) and "accounts.google.com" not in url and "signin" not in url:
                    print("\n🎉 Detected successful login to Google Business!")
                    print("Giving 5 seconds for auth tokens and cookies to save...")
                    await asyncio.sleep(5)
                    login_success = True
                    break
            except Exception:
                print("Browser session ended.")
                break

        if login_success:
            print("\n✅ Login successful! Session saved.")
        else:
            print("\n⚠️ Login was not completed or browser was closed early.")
    except Exception as e:
        print(f"Error during login setup: {e}")
    finally:
        if manager.is_running:
            print("Closing browser and flushing session state to disk...")
            await manager.close()
            print("Session saved cleanly!")


if __name__ == "__main__":
    asyncio.run(main())

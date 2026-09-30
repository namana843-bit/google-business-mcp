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
from browser_mcp.sites.google_business import get_google_business_profile, list_google_business_accounts
from browser_mcp.utils.errors import ProfileLockedError

async def main():
    profile = sys.argv[1] if len(sys.argv) > 1 else "default"
    manager = get_manager()
    try:
        # Launch using the correct tool function
        await browser_launch(manager, profile=profile, headless=True)
        print(f"Successfully connected to the profile '{profile}'!")
        
        print("\nFetching your Google Business Profile data...")
        profile_data = await get_google_business_profile(manager)
        logger.info("Fetched Google Business profile data")
        
    except ProfileLockedError:
        print("ERROR: PROFILE_LOCKED")
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        if manager.is_running:
            await manager.close()

if __name__ == "__main__":
    asyncio.run(main())

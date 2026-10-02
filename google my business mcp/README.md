# Universal Browser Automation MCP Server

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Standard%20Protocol-green.svg)](https://modelcontextprotocol.io/)
[![Playwright](https://img.shields.io/badge/Playwright-Chromium-orange.svg)](https://playwright.dev/python/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-quality **Universal Browser Automation MCP Server** that allows any Model Context Protocol (MCP) compatible AI agent or CLI to control a real, persistent Chromium browser.

Engineered with a **generic browser engine first**, persistent session profiles, a **human-in-the-loop approval layer**, semantic and accessible selector resolution, and extensible domain adapters—starting with **Google Business Profile**.

---

## 🏛️ Architecture

```
AI CLI / Agent (Claude Code / OpenCode / Antigravity / Custom)
                          ↓
                 MCP Protocol (stdio / SSE)
                          ↓
               Browser Automation MCP
                          ↓
              Playwright Persistent Context
                          ↓
                 Persistent Chromium
                          ↓
  ┌──────────────────────────────────────────────────┐
  │ Any Website                                      │
  │ • Generic Automation (Forms, Clicks, Scrapes)   │
  │ • Site Adapters (Google Business Profile, etc.) │
  └──────────────────────────────────────────────────┘
```

### Key Principles
1. **Generic Engine**: The core browser lifecycle, navigation, semantic selector resolution, and screenshot mechanisms are completely website-agnostic.
2. **Persistent Profiles & Manual Login**: AI agents never request or touch user passwords. Users log in interactively once in the browser window; cookies, tokens, and storage persist on disk across sessions.
3. **Human Approval Layer**: Risky operations (public posts, customer review replies, content deletion) are gated behind an approval workflow tracked in SQLite.
4. **Resilient UI Discovery**: Instead of brittle CSS classes, tools leverage accessible ARIA roles, visible text, labels, and hierarchical relationships.

---

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/namana843-bit/browser-automation-mcp.git
cd browser-automation-mcp

# Install in editable mode
pip install -e .

# Install Playwright browser binaries
playwright install chromium
```

### 2. Run the MCP Server

Default interactive mode (visible browser window, stdio transport):
```bash
browser-mcp
```
or via Python module:
```bash
python -m browser_mcp
```

For remote clients using Server-Sent Events (SSE):
```bash
browser-mcp --transport sse --host 127.0.0.1 --port 8000
```

---

## 🔐 Authentication & Persistent Profiles

**Never provide passwords to AI agents.** Authentication occurs natively within the browser window.

### First-Time Google Business Login
1. Launch the browser with the `google-business` profile:
   ```json
   {
     "tool": "browser_launch",
     "arguments": { "profile": "google-business", "headless": false }
   }
   ```
2. Chromium will open on your desktop.
3. Navigate to `https://accounts.google.com` and log into your Google account.
4. Complete any 2FA/MFA prompts.
5. Close the browser with `browser_close`.
6. Subsequent calls to `browser_launch(profile="google-business")` or `google_business_open()` will automatically restore your authenticated session.

Profiles are saved under `./profiles/` (or customized via `BROWSER_MCP_PROFILE_DIR`).

#### Log in ONCE — why you should never be asked again

A relative `BROWSER_MCP_PROFILE_DIR` (e.g. `./profiles`) is resolved against the
**project root**, *not* the working directory. This matters: MCP clients launch the
server from many different directories (your home folder, the IDE folder, `C:\Windows`),
and resolving against the working directory silently produced a **brand-new empty
profile on every run**, which is what made it look like you had to sign in again and
again. The same applies to `BROWSER_MCP_DB_PATH`, so pending approvals survive too.

To make a session truly sticky:

1. **Always launch with the same profile name** (e.g. `google-business`) — the login is
   stored inside that profile folder, not globally.
2. **Do not delete** the `profiles/<name>/` folder between runs.
3. **Keep `BROWSER_MCP_PROFILE_PATH` empty** so you stay on the isolated profile.
4. **Verify it worked** with `browser_list_profiles` — your profile should be listed,
   and `google_business_open` should return your business instead of a sign-in page.

You only need to re-authenticate when Google itself expires the session (typically
after a password change, a long idle period, or if you sign the account out elsewhere).

---

## 🛡️ Human Approval Layer

To prevent autonomous AI agents from performing destructive or unintended public actions, sensitive actions are gated by human verification.

Configurable in `.env` or environment variables:
```bash
BROWSER_MCP_APPROVAL_MODE=strict # 'strict' (default), 'auto', or 'prompt'
```

### Default Risk Policies
- **Public Posts (`google_business_create_post`)**: Approval required.
- **Review Replies (`google_business_reply_review`)**: Approval required.
- **Delete Operations (`google_business_delete_post`)**: Approval required.
- **Media Uploads (`google_business_upload_media`)**: Approval required.

### How the Flow Works:
1. Agent attempts to reply to a review:
   ```json
   {
     "success": false,
     "error_type": "APPROVAL_REQUIRED",
     "message": "APPROVAL REQUIRED: Action 'review_reply' requires explicit human authorization. Call 'browser_approve_action(approval_id=\"appr_abc123\", approved=True)' once approved.",
     "details": {
       "approval_id": "appr_abc123",
       "action": "review_reply",
       "parameters": {
         "review_id": "rev-101",
         "reply_text": "Thank you for visiting!"
       }
     }
   }
   ```
2. The user or operator approves via tool:
   ```json
   {
     "tool": "browser_approve_action",
     "arguments": { "approval_id": "appr_abc123", "approved": true }
   }
   ```
3. The agent re-invokes the reply tool with the `approval_id`, and the action executes in the browser.

---

## 🛠️ Complete MCP Tool Catalog

### 1. Browser Lifecycle
| Tool | Description |
| :--- | :--- |
| `browser_launch` | Launch or connect to a persistent Chromium profile (`profile`, `headless`, `slow_mo`). |
| `browser_close` | Close active browser session and commit state to disk. |
| `browser_status` | Retrieve running status, active profile, open tab count, active URL, and title. |
| `browser_list_pages` | List all open tabs/pages. |
| `browser_new_page` | Open a new tab and optionally navigate to a URL. |
| `browser_switch_page` | Switch active focus to a specific tab index (0-based). |
| `browser_close_page` | Close a specific tab index or active tab. |

### 2. Navigation
| Tool | Description |
| :--- | :--- |
| `browser_navigate` | Navigate active page to URL (`url`, `wait_until`). |
| `browser_back` | Navigate to previous page in browser history. |
| `browser_forward` | Navigate forward in browser history. |
| `browser_reload` | Reload the current page. |
| `browser_wait` | Wait for seconds or wait for an element state (`visible`, `hidden`, `attached`). |

### 3. Page Inspection & DOM Extraction
| Tool | Description |
| :--- | :--- |
| `browser_get_url` | Get the URL of the active browser page. |
| `browser_get_title` | Get the title of the active browser page. |
| `browser_get_text` | Extract visible text from page or element (with length capping). |
| `browser_get_html` | Extract HTML source code from page or element. |
| `browser_get_links` | Extract anchor links (`text` and `href`) on the page. |
| `browser_find` | Inspect an element without clicking. Returns `tag`, `text`, `visible`, `enabled`, `attributes`, `bounding_box`. Supports `role`, `text`, `label`, `placeholder`, `css`, `xpath`. |

### 4. Interaction
| Tool | Description |
| :--- | :--- |
| `browser_click` | Click an element using semantic or CSS/XPath selectors. |
| `browser_type` | Type text sequentially with realistic keyboard delays. |
| `browser_fill` | Fill an input or textarea immediately. |
| `browser_press` | Press a keyboard key (`Enter`, `Tab`, `Escape`, `ArrowDown`). |
| `browser_select` | Select an option in a `<select>` dropdown by value. |
| `browser_check` | Check a checkbox or radio button. |
| `browser_uncheck` | Uncheck a checkbox. |
| `browser_hover` | Hover mouse cursor over an element. |
| `browser_scroll` | Scroll page up or down by pixel amount. |

#### Selector Formats

Every tool that takes a `selector` (`browser_click`, `browser_type`, `browser_fill`,
`browser_press`, `browser_select`, `browser_check`, `browser_uncheck`, `browser_hover`,
`browser_find`, `browser_get_text`, `browser_get_html`, `browser_wait`,
`browser_screenshot`) accepts **all three** of these forms:

| Form | Example | Notes |
| :--- | :--- | :--- |
| Bare string | `"#submit"`, `"div.card"` | Treated as CSS unless `selector_type` says otherwise. |
| Prefix string | `"text=Save"`, `"label=Email"`, `"placeholder=Search"`, `"role=button,Save"`, `"//div[@id='x']"` | Type is auto-detected from the prefix. |
| Object | `{"type": "text", "value": "Save", "exact": false}` | Explicit control; `type` is one of `role`, `text`, `label`, `placeholder`, `css`, `xpath`. |

You can also pass the type separately: `{"selector": "Save", "selector_type": "text"}`.

### 5. Screenshots
| Tool | Description |
| :--- | :--- |
| `browser_screenshot` | Capture full-page or element screenshot. Returns base64 string for direct AI vision inspection. |

### 6. Human Approval & Sessions
| Tool | Description |
| :--- | :--- |
| `browser_list_profiles` | List all available persistent profile folders. |
| `browser_pending_approvals` | List all actions awaiting human review. |
| `browser_approve_action` | Approve (`approved=true`) or reject (`approved=false`) an action by `approval_id`. |

### 7. High-Level Sequence Execution
| Tool | Description |
| :--- | :--- |
| `browser_execute` | Execute a multi-step sequence (`navigate`, `click`, `fill`, etc.). Returns per-step results; halts on failure with automatic screenshot. |

### 8. Google Business Profile Module
| Tool | Description |
| :--- | :--- |
| `google_business_open` | Open Google Business Profile dashboard using `google-business` profile. |
| `google_business_get_profile` | Extract business name, category, address, phone, rating, and review count. |
| `google_business_get_reviews` | Extract customer reviews, star ratings, and reply status. |
| `google_business_reply_review` | Post a public response to a customer review (requires human approval). |
| `google_business_create_post` | Publish an update post on the business profile (requires human approval). |
| `google_business_delete_post` | Delete a post by `post_id` (requires human approval). |
| `google_business_get_media` | Extract photos and images displayed on the profile. |
| `google_business_upload_media` | Upload a local photo to Google Business Profile (requires human approval). |

---

## 🤖 CLI Client Configuration Examples

### Claude Code CLI & Claude Desktop
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "browser": {
      "command": "python",
      "args": ["-m", "browser_mcp"],
      "env": {
        "BROWSER_MCP_HEADLESS": "false",
        "BROWSER_MCP_APPROVAL_MODE": "strict"
      }
    }
  }
}
```

### OpenCode CLI
Add to `.opencode/config.json`:
```json
{
  "mcp": {
    "servers": {
      "browser": {
        "command": "python",
        "args": ["-m", "browser_mcp"],
        "env": {
          "BROWSER_MCP_HEADLESS": "false",
          "BROWSER_MCP_APPROVAL_MODE": "strict"
        }
      }
    }
  }
}
```

### Antigravity CLI / IDE
Add to `.agents/mcp_config.json`:
```json
{
  "mcpServers": {
    "browser-automation": {
      "command": "python",
      "args": ["-m", "browser_mcp"],
      "env": {
        "BROWSER_MCP_HEADLESS": "false",
        "BROWSER_MCP_APPROVAL_MODE": "strict"
      }
    }
  }
}
```

---

## 🔌 Adding a New Website Adapter

Adding support for any new platform (e.g. LinkedIn, Instagram, Shopify) is straightforward and does not touch core browser logic.

1. Create a directory: `src/browser_mcp/sites/your_site/`
2. Implement the `SiteAdapter` interface from `src/browser_mcp/sites/base.py`:
```python
from browser_mcp.sites.base import SiteAdapter
from browser_mcp.browser.manager import BrowserManager
from browser_mcp.models.schemas import ActionResult

class YourSiteAdapter(SiteAdapter):
    name = "yoursite"
    base_url = "https://example.com/dashboard"
    allowed_domains = ["example.com"]

    async def detect(self, page) -> bool:
        return "example.com" in page.url

    async def open(self, manager: BrowserManager) -> ActionResult:
        return await manager.navigate(self.base_url)

    async def execute(self, manager: BrowserManager, action: str, **kwargs) -> ActionResult:
        if action == "do_something":
            # Use manager.click(), manager.fill(), etc.
            return ActionResult(success=True)
        return ActionResult(success=False, message="Unknown action")
```
3. Expose specific MCP tools in `server.py` using `@mcp.tool(name="yoursite_action")`.

---

## 🔒 Security Best Practices

- **Zero Credential Handling**: The server contains no facilities for storing or transmitting user passwords.
- **Domain Guardrails**: Configure `BROWSER_MCP_ALLOWED_DOMAINS` and `BROWSER_MCP_BLOCKED_DOMAINS` in `.env` to restrict browser navigation.
- **Local Isolation**: Browser execution occurs strictly on the local machine with no external telemetry.
- **Audit Logging**: All browser navigation and actions are logged to SQLite (`browser_mcp.db`).
- **Challenge Safety**: If a CAPTCHA, Cloudflare challenge, or Google 2-Step Verification prompt is detected, the MCP halts and returns `CAPTCHA_DETECTED` or `MFA_REQUIRED` rather than crashing.

---

## 🧪 Testing

Run the complete test suite against local fixture web pages and mocked adapters:
```bash
pytest -v
```

All 45+ integration and unit tests run in headless mode without hitting live external websites.

---

## 🩺 Troubleshooting

### Every browser tool returns `PROFILE_LOCKED`

This almost always means `BROWSER_MCP_PROFILE_DIR` or `BROWSER_MCP_PROFILE_PATH` points
at your **live Chrome `User Data` directory**. Chrome will not share that directory with
a second process, so every launch is refused.

The default config keeps profiles isolated inside this project:

```env
BROWSER_MCP_PROFILE_PATH=
BROWSER_MCP_PROFILE_DIR=./profiles
BROWSER_MCP_DEFAULT_PROFILE=default
```

If you deliberately want to reuse your everyday Chrome login, close **all** Chrome
windows first, then point `BROWSER_MCP_PROFILE_PATH` at the specific profile folder
(e.g. `C:\Users\<you>\AppData\Local\Google\Chrome\User Data\Profile 1`). Note that
Chrome and the MCP will then fight over the same folder, so close Chrome between runs.

### `browser_launch` fails with `spawn . ENOENT`

`BROWSER_MCP_EXECUTABLE_PATH` is set to a blank value. Either give it a real path
(e.g. `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`) or leave it empty
to use Playwright's bundled Chromium — run `playwright install chromium` once if needed.

### Every Google Business tool returns `CAPTCHA_DETECTED`

Fixed in this version, but if you see it, Google is genuinely challenging the session.
Usually it means the profile is not signed in yet, or Google is rate-limiting repeated
automated hits. Open the browser with `browser_launch {"headless": false}` and complete
the challenge or sign-in by hand once — the profile then persists.

Note that a hidden reCAPTCHA badge iframe is present on nearly every Google page and is
deliberately **not** treated as a challenge; only a visible, interactive widget halts
automation.

### A tool call fails with "Input should be a valid string"

Older clients passed selectors as an object such as `{"type": "text", "value": "Save"}`.
This is supported — see [Selector Formats](#4-interaction). If you are on an old copy,
reinstall with `pip install -e .`.

---

## 📄 License
MIT License.

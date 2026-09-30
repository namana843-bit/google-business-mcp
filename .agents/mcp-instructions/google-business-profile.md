# Google Business Profile MCP — Instructions

## Overview

This MCP provides high-level Google Business Profile tools. It runs via **browser
automation** (Playwright + a persistent Chromium profile) — **not** the Google
Business API. This means:

- ✅ No OAuth / API keys needed
- ✅ Reuses the user's existing Google login in the browser
- ✅ Works for any account the user has access to
- ❌ Requires the browser to be running and signed in first

---

## Correct Tool Names

The schema files use logical names. The actual tool names registered in the MCP
server (browser-automation-mcp) are:

| Schema Name                       | Real Tool Name                        |
|-----------------------------------|---------------------------------------|
| `list_google_business_accounts`   | `google_business_list_accounts`       |
| `list_google_business_locations`  | `google_business_list_locations`      |
| `get_google_business_reviews`     | `google_business_get_reviews`         |
| `reply_to_google_business_review` | `google_business_reply_review`        |

**Always call the Real Tool Name** when invoking these tools.

---

## Required Workflow (Follow This Order!)

```
Step 1: google_business_open
        → Launches the browser and navigates to business.google.com
        → REQUIRED before any other tool

Step 2: google_business_list_accounts
        → Returns [{account_name: "accounts/123...", display_name: "..."}]
        → Use account_name in the next step

Step 3: google_business_list_locations(account_name="accounts/123...")
        → Returns [{location_name: "accounts/123/locations/456", display_name: "..."}]

Step 4: google_business_get_reviews(limit=10)
        → Scrapes reviews from the CURRENTLY ACTIVE browser page
        → Returns [{review_id, author, content, date, has_replied, addressable}]
        → Only use review_id values where addressable=true for replies

Step 5 (optional): google_business_reply_review(review_name=<review_id>, reply_text="...")
        → Posts a public owner reply
        → REQUIRES HUMAN APPROVAL — check browser_pending_approvals first
        → ONLY use review_id values returned by get_reviews, NEVER invent IDs
```

---

## Critical Rules

1. **Never invent review IDs.** Only use `review_id` values from `google_business_get_reviews`.
   Reviews where `addressable=false` cannot be replied to — skip them.

2. **Approval is mandatory for replies.** After calling `google_business_reply_review`,
   check `browser_pending_approvals` and call `browser_approve_action` to authorize.

3. **The browser must be open and logged in.** If any tool returns `LOGIN_REQUIRED`,
   call `google_business_open` and wait for the user to sign in manually.

4. **account_name format:** Always `accounts/<numeric_id>` or `accounts/me`.
   Never use a display name as an account_name.

---

## Companion Tools (in browser-automation-mcp)

- `google_business_open` — open/navigate to GBP dashboard
- `google_business_get_profile` — extract business name, rating, address, phone
- `google_business_create_post` — publish an update post (requires approval)
- `google_business_get_media` — list photos
- `browser_screenshot` — take a screenshot to verify current state
- `browser_pending_approvals` — list actions waiting for your approval
- `browser_approve_action(approval_id, approved=True)` — approve a pending action

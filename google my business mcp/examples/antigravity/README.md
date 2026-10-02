# Antigravity CLI & IDE Integration

To connect Antigravity to the Browser Automation MCP:

### 1. Configuration Location
Place `mcp_config.json` inside your Antigravity project customization directory:
`.agents/mcp_config.json` or your global config root `~/.gemini/antigravity-ide/mcp/`.

### 2. Configuration (stdio Transport)

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

### 3. Usage with Antigravity
The Antigravity agent will automatically discover tools such as `browser_launch`, `browser_navigate`, `google_business_reply_review`, and `browser_approve_action`.
When sensitive actions like public review replies are invoked, the agent receives an `APPROVAL_REQUIRED` status with the approval token, allowing human verification before publication.

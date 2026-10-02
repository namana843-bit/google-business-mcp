# OpenCode CLI Integration

To use the Browser Automation MCP server with OpenCode CLI:

### 1. Project Configuration
Add the configuration to `.opencode/config.json` or your global OpenCode settings:

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

### 2. Verify Connection
Run OpenCode in your project workspace:
```bash
opencode mcp list
```
You should see all generic browser tools and Google Business tools listed.

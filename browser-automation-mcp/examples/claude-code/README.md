# Claude Code CLI / Claude Desktop Integration

To connect Claude Code CLI or Claude Desktop to the Browser Automation MCP:

### 1. Configuration File Location
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### 2. Configuration (stdio Transport - Recommended)

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

### 3. Alternative: SSE / Remote Transport

Start the server in background:
```bash
python -m browser_mcp --transport sse --port 8000
```

Configure Claude:
```json
{
  "mcpServers": {
    "browser": {
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

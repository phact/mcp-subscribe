# mcp-subscribe
This MCP server allows you to subscribe to changes in tools of another MCP server.

To use it configure your client to use this mcp server with the base mcp server as an argument.

```
{
  "server": {
    "type": "stdio",
    "command": "mcp_subscribe",
    "args": ["uvx", "mcp-server-fetch", "--poll-interval", "5"],
    "env": {}
  }
}
```

**Note:** your MCP client must support [resource subscriptions](https://modelcontextprotocol.io/docs/concepts/resources#content-changes)

A sample MCP Server is provided in the [examples](examples) directory.

> uv run examples/example_client.py

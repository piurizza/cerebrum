# Agents (MCP)

Cerebrum has a built-in [MCP](https://modelcontextprotocol.io) server, so AI
assistants that speak MCP, such as Claude, can read, search and write your
notes. It lives at `/api/mcp/` on the same address as the web app; there is no
separate port.

Every request needs a personal API token, which you create and revoke in
**Settings**. An assistant sees exactly what your account sees.

- [Connect an assistant](mcp-setup.md): create a token and add Cerebrum to
  Claude Code, Claude Desktop, VS Code and others.
- [Tools](mcp-tools.md): the ten tools, what each does, and which ones a
  read-only vault hides.

Use HTTPS whenever an assistant reaches Cerebrum over a network, so the token
isn't sent in plain text; see [HTTPS](../running/https.md).

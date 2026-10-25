# Connect an assistant

## 1. Create a token

In Cerebrum, open **Settings**, then under **Personal API tokens** give the
token a name, such as the assistant's, and choose **Generate new token**.
Copy it now: it's shown only once. It starts with `cbm_pat_`.

Create one token per assistant, so you can revoke one without the others.

## 2. Add Cerebrum to your assistant

The server address is your Cerebrum address followed by `/api/mcp/`, for
example `https://<machine>.<tailnet>.ts.net/api/mcp/`. It uses MCP's
streamable HTTP transport, and the token goes in an `Authorization` header as
`Bearer <token>`.

=== "Claude Code"

    ```sh
    claude mcp add --transport http cerebrum https://<your-address>/api/mcp/ \
      --header "Authorization: Bearer cbm_pat_..."
    ```

=== "VS Code"

    In `.vscode/mcp.json`, or your user MCP configuration:

    ```json
    {
      "servers": {
        "cerebrum": {
          "type": "http",
          "url": "https://<your-address>/api/mcp/",
          "headers": { "Authorization": "Bearer cbm_pat_..." }
        }
      }
    }
    ```

=== "Claude Desktop"

    Claude Desktop starts local MCP servers from its configuration file. Use
    the `mcp-remote` bridge, which needs Node.js, to reach Cerebrum. In
    `claude_desktop_config.json`:

    ```json
    {
      "mcpServers": {
        "cerebrum": {
          "command": "npx",
          "args": [
            "mcp-remote",
            "https://<your-address>/api/mcp/",
            "--header",
            "Authorization: Bearer ${CEREBRUM_TOKEN}"
          ],
          "env": { "CEREBRUM_TOKEN": "cbm_pat_..." }
        }
      }
    }
    ```

=== "Other clients"

    Any client that supports MCP over streamable HTTP with a custom header
    works. Give it the address and the `Authorization: Bearer <token>`
    header; see the client's own documentation for where they go.

Configuration formats change between client versions; if one of these doesn't
match yours, check the client's documentation.

## 3. Try it

Ask the assistant something like "list my notes about the garden" or "add
'buy compost' to today's daily note". It should find Cerebrum's tools and use
them.

## Which link style assistants write

The tools that write notes tell the assistant which link style your vault
uses: standard markdown links, or `[[wikilinks]]` when
`CEREBRUM_LINK_FORMAT=wikilink`. See [Links](../features/links.md).

## Revoking access

Revoke a token in **Settings** and it stops working at once. Deactivating an
account revokes all its tokens.

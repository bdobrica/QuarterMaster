# Optional read-only lookups

Collection and AI extraction work without any connector. Under a collection's **Advanced → Optional read-only lookups**, you can enable individually named tools and explicitly send arguments. Output stays in the local lookup history; copy useful observations into a record or knowledge instruction yourself. No page or model can initiate a call, and calls cannot edit examples, files or knowledge. Logs are local, not included in publications.

Muster supports MCP **2025-11-25 Streamable HTTP with JSON responses**, including initialization and session headers. SSE responses, stdio, server-initiated requests, sampling, roots, OAuth and write tools are outside this small integration. Services must be trusted: a server's `readOnlyHint` is not proof of its behavior. The operator configures the named read-only allowlist and argument schemas; changing configuration requires re-enabling the connector per collection. Redirects are refused, requests time out after 20 seconds, responses are limited to 256 KB and arguments to 16 KB. An interrupted lookup is failed on restart and never resent automatically.

Protocol references: [transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [tool annotations](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations).

## Try a useful lookup without an external service

Run `python scripts/muster/example_connector.py` in another terminal. This standalone standard-library service converts square feet to square metres without visiting a listing or sending data off your computer.

Create `connectors.json` **inside your data directory** (`data/muster/connectors.json` by default in QuarterMaster):

```json
{
  "area": {
    "url": "http://127.0.0.1:8766/mcp",
    "tools": {
      "square_feet_to_square_metres": {
        "read_only": true,
        "input_schema": {
          "type": "object",
          "properties": {"square_feet": {"type": "number", "minimum": 0}},
          "required": ["square_feet"],
          "additionalProperties": false
        }
      }
    }
  }
}
```

Open the collection's optional lookups, enable **area**, enter `{"square_feet": 1000}`, check consent and run. The result is **92.90304 square metres**. Review it and copy it to a suitable field with a note about the conversion. Disable the connector to revoke future calls; saved logs remain.

Remote services require HTTPS. Optional `"token_env": "MY_SERVICE_TOKEN"` reads a bearer token from the process environment; never put tokens in the configuration URL or arguments. Headers and exception details are not logged. Run only tools you have verified to be read-only. Explicit arguments are retained in local logs, so do not enter credentials there.

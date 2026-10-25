"""Run a local, read-only MCP area conversion example: python scripts/example_connector.py."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

SCHEMA = {
    "type": "object",
    "properties": {"square_feet": {"type": "number", "minimum": 0}},
    "required": ["square_feet"],
    "additionalProperties": False,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/mcp" or self.headers.get("Origin") not in (None, "http://127.0.0.1:8766"):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16000:
                raise ValueError()
            request = json.loads(self.rfile.read(length))
            method = request["method"]
            if method == "notifications/initialized":
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Area conversion example", "version": "1.0"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "square_feet_to_square_metres",
                            "description": "Convert an area to square metres.",
                            "inputSchema": SCHEMA,
                            "annotations": {"readOnlyHint": True},
                        }
                    ]
                }
            elif (
                method == "tools/call"
                and request["params"]["name"] == "square_feet_to_square_metres"
            ):
                args = request["params"]["arguments"]
                value = args["square_feet"]
                if (
                    set(args) != {"square_feet"}
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or value < 0
                ):
                    raise ValueError()
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "square_metres": round(value * 0.09290304, 6),
                                    "conversion": "1 ft² = 0.09290304 m²",
                                }
                            ),
                        }
                    ]
                }
            else:
                raise ValueError()
            body = json.dumps(
                {"jsonrpc": "2.0", "id": request["id"], "result": result}, allow_nan=False
            ).encode()
        except (ValueError, KeyError, TypeError):
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Read-only area lookup: http://127.0.0.1:8766/mcp (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", 8766), Handler).serve_forever()

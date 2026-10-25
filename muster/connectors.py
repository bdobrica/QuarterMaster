"""Explicit user-initiated, read-only MCP calls. Never available to page/model content."""

import hashlib
import json
import os
import re
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2 as httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from jsonschema import Draft202012Validator

from muster.schema import now
from muster.storage import connect


def configuration(root):
    path = root / "connectors.json"
    if not path.exists():
        return {}
    if path.stat().st_size > 64000:
        raise ValueError("Connector configuration exceeds 64 KB.")
    configs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(configs, dict):
        raise ValueError("Connector configuration must be an object.")
    for name, item in configs.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name) or not isinstance(item, dict):
            raise ValueError("Invalid connector name or configuration.")
        url = urlsplit(item.get("url", ""))
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (url.scheme == "http" and url.hostname not in ("127.0.0.1", "localhost", "::1"))
        ):
            raise ValueError(
                "Use HTTPS or a loopback HTTP connector address without credentials or query parameters."
            )
        token_env = item.get("token_env", "")
        if not isinstance(token_env, str) or (
            token_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env)
        ):
            raise ValueError("Use an environment variable name for the optional bearer token.")
        tools = item.get("tools")
        if not isinstance(tools, dict) or not tools:
            raise ValueError("Each connector needs a named tool allowlist.")
        for tool, spec in tools.items():
            if (
                not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", tool)
                or not isinstance(spec, dict)
                or spec.get("read_only") is not True
            ):
                raise ValueError("Only explicitly trusted, named read-only tools are supported.")
            Draft202012Validator.check_schema(spec["input_schema"])
    return configs


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


async def invoke(config, tool, arguments, transport=None):
    """MCP 2025-11-25 Streamable HTTP, JSON responses only; no server-initiated actions."""
    token = os.environ.get(config.get("token_env", ""), "")
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, trust_env=False, transport=transport
    ) as client:

        async def rpc(method, params, request_id=None):
            body = {"jsonrpc": "2.0", "method": method, "params": params}
            if request_id is not None:
                body["id"] = request_id
            async with client.stream("POST", config["url"], headers=headers, json=body) as response:
                response.raise_for_status()
                session = response.headers.get("mcp-session-id")
                if session:
                    headers["Mcp-Session-Id"] = session
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 256000:
                        raise ValueError("Connector response exceeds 256 KB.")
                if request_id is None:
                    return None
                if "application/json" not in response.headers.get("content-type", ""):
                    raise ValueError(
                        "This connector needs JSON responses; streaming responses are not supported."
                    )
                result = json.loads(content)
                if (
                    result.get("id") != request_id
                    or result.get("jsonrpc") != "2.0"
                    or "error" in result
                    or "result" not in result
                ):
                    raise ValueError(
                        "Connector returned an invalid response or refused the request."
                    )
                return result["result"]

        init = await rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "Muster", "version": "0.1.0"},
            },
            1,
        )
        if init.get("protocolVersion") != "2025-11-25":
            raise ValueError("Connector must support MCP 2025-11-25.")
        headers["MCP-Protocol-Version"] = "2025-11-25"
        await rpc("notifications/initialized", {})
        result = await rpc("tools/call", {"name": tool, "arguments": arguments}, 2)
        if not isinstance(result, dict) or result.get("isError"):
            raise ValueError("The read-only tool could not complete the lookup.")
        return result


async def call(root, cid, name, tool, arguments, transport=None):
    configs = configuration(root)
    config = configs.get(name)
    if not config or tool not in config["tools"]:
        raise ValueError("This named tool is not allowed.")
    encoded_arguments = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    if len(encoded_arguments.encode("utf-8")) > 16000:
        raise ValueError("Keep lookup arguments within 16 KB.")
    Draft202012Validator(config["tools"][tool]["input_schema"]).validate(arguments)
    with connect(root) as db:
        enabled = db.execute(
            "SELECT config_hash FROM connector_permissions WHERE collection_id=? AND name=?",
            (cid, name),
        ).fetchone()
        if not enabled or enabled["config_hash"] != fingerprint(config):
            raise ValueError(
                "Enable this connector for this collection again after checking its configuration."
            )
        call_id = uuid4().hex
        db.execute(
            "INSERT INTO connector_calls(id,collection_id,name,tool,arguments,status,created_at) VALUES(?,?,?,?,?,'running',?)",
            (call_id, cid, name, tool, json.dumps(arguments), now()),
        )
    try:
        result = await invoke(config, tool, arguments, transport)
        # Connector output is untrusted data. Never executes or changes accepted records.
        encoded = json.dumps(result, ensure_ascii=False)
        token = os.environ.get(config.get("token_env", ""), "")
        if token:
            encoded = encoded.replace(token, "[redacted]")
        with connect(root) as db:
            db.execute(
                "UPDATE connector_calls SET status='complete',result=? WHERE id=?",
                (encoded, call_id),
            )
    except Exception:
        with connect(root) as db:
            db.execute(
                "UPDATE connector_calls SET status='failed',error='Lookup failed. Check the connector address, protocol, response size and service availability; retry explicitly.' WHERE id=?",
                (call_id,),
            )
    return call_id


def register_connector_routes(app, root, render):
    @app.get("/collections/{cid}/connectors")
    def view(request: Request, cid: int):
        try:
            configs = configuration(root)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        with connect(root) as db:
            collection = db.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
            if not collection:
                raise HTTPException(404, "Collection not found")
            permissions = {
                row["name"]: row["config_hash"]
                for row in db.execute(
                    "SELECT * FROM connector_permissions WHERE collection_id=?", (cid,)
                )
            }
            logs = db.execute(
                "SELECT * FROM connector_calls WHERE collection_id=? ORDER BY created_at DESC LIMIT 50",
                (cid,),
            ).fetchall()
        return render(
            request,
            "connectors.html",
            collection=collection,
            configs=configs,
            enabled={
                name: permissions.get(name) == fingerprint(config)
                for name, config in configs.items()
            },
            logs=logs,
        )

    @app.post("/collections/{cid}/connectors/{name}/{action}")
    async def change(request: Request, cid: int, name: str, action: str):
        form = await request.form()
        try:
            config = configuration(root).get(name)
            with connect(root) as db:
                if not db.execute("SELECT 1 FROM collections WHERE id=?", (cid,)).fetchone():
                    raise HTTPException(404, "Collection not found")
                if action == "disable":
                    db.execute(
                        "DELETE FROM connector_permissions WHERE collection_id=? AND name=?",
                        (cid, name),
                    )
                elif action == "enable" and config and form.get("consent") == "yes":
                    db.execute(
                        "INSERT INTO connector_permissions VALUES(?,?,?) ON CONFLICT(collection_id,name) DO UPDATE SET config_hash=excluded.config_hash",
                        (cid, name, fingerprint(config)),
                    )
                elif action != "call":
                    raise ValueError("Check consent before enabling a trusted read-only connector.")
            if action == "call":
                if form.get("consent") != "yes":
                    raise ValueError("Check the arguments and consent before sending.")
                raw = form.get("arguments", "")
                if len(raw.encode("utf-8")) > 16000:
                    raise ValueError("Keep lookup arguments within 16 KB.")
                await call(root, cid, name, form.get("tool", ""), json.loads(raw))
        except Exception as exc:
            from jsonschema import ValidationError

            if isinstance(exc, HTTPException):
                raise
            if isinstance(exc, (ValueError, KeyError, ValidationError)):
                raise HTTPException(
                    400, "Check the connector configuration, named tool, arguments and consent."
                ) from None
            raise
        return RedirectResponse(f"/collections/{cid}/connectors", 303)

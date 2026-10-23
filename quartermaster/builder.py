"""One bounded OpenAI-compatible structured-response adapter; no SDK or automatic retries."""

import asyncio
import json
import stat
from typing import Protocol

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from quartermaster.config import Settings
from quartermaster.errors import DomainError

MAX_RESPONSE_BYTES = 65536
MAX_REQUEST_BYTES = 65536


class BuilderLLM(Protocol):
    async def structured[T: BaseModel](
        self, *, system: str, context: str, schema: type[T]
    ) -> T: ...


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ok: bool


def provider_identity(settings: Settings) -> tuple[str, str]:
    if settings.builder_base_url is None or settings.builder_model is None:
        raise DomainError(
            "BUILDER_CONFIG: Set QM_BUILDER_BASE_URL and QM_BUILDER_MODEL, or use the manual draft."
        )
    return str(settings.builder_base_url).rstrip("/") + "/chat/completions", settings.builder_model


def credential(settings: Settings) -> str | None:
    if settings.builder_api_key and settings.builder_api_key_file:
        raise DomainError(
            "BUILDER_KEY: Configure either the key environment variable or secret file."
        )
    if settings.builder_api_key:
        value = settings.builder_api_key.get_secret_value()
    elif settings.builder_api_key_file:
        try:
            path = settings.builder_api_key_file
            if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > 4096:
                raise OSError
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise DomainError(
                "BUILDER_KEY: Check the readable UTF-8 secret file (at most 4 KiB)."
            ) from None
    else:
        return None  # Local compatible servers may not require authentication.
    if not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise DomainError("BUILDER_KEY: Check the API key environment variable or secret file.")
    return value


class OpenAICompatible:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def structured[T: BaseModel](self, *, system: str, context: str, schema: type[T]) -> T:
        endpoint, model = provider_identity(self.settings)
        key = credential(self.settings)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": context},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
            "max_completion_tokens": 2048,
            "n": 1,
            "stream": False,
            "store": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise DomainError("BUILDER_INPUT: Shorten the interview answers or omit excerpts.")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        try:
            async with asyncio.timeout(self.settings.builder_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self.settings.builder_timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client:
                    async with client.stream(
                        "POST", endpoint, content=body, headers=headers
                    ) as response:
                        if response.status_code in (401, 403):
                            raise DomainError(
                                "BUILDER_AUTH: Check the provider API key and access."
                            )
                        if response.status_code == 429:
                            raise DomainError("BUILDER_RATE_LIMIT: Wait, then explicitly retry.")
                        if response.status_code >= 300:
                            raise DomainError(
                                "BUILDER_HTTP: Check endpoint, model and schema support; retry."
                            )
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > MAX_RESPONSE_BYTES:
                                raise DomainError(
                                    "BUILDER_SIZE: Provider response exceeded 64 KiB; retry."
                                )
            envelope = json.loads(data)
            choices = envelope["choices"]
            if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
                raise ValueError
            message = choices[0]["message"]
            if not isinstance(message, dict):
                raise ValueError
            if message.get("refusal") or message.get("tool_calls"):
                raise ValueError
            content = message["content"]
            if not isinstance(content, str):
                raise ValueError
            return schema.model_validate_json(content)
        except (TimeoutError, httpx.TimeoutException):
            raise DomainError(
                "BUILDER_TIMEOUT: Provider timed out. Your answers are saved; retry explicitly."
            ) from None
        except httpx.HTTPError:
            raise DomainError(
                "BUILDER_CONNECTION: Check the provider connection; then retry."
            ) from None
        except (ValueError, KeyError, TypeError, IndexError, RecursionError, ValidationError):
            raise DomainError(
                "BUILDER_JSON: Invalid or incomplete provider JSON. Review manually or retry."
            ) from None


async def test_provider(builder: BuilderLLM) -> dict:
    result = await builder.structured(
        system="Return JSON matching the schema. Connection test with no business data.",
        context='Return {"ok": true}.',
        schema=Probe,
    )
    if result.ok is not True:
        raise DomainError("BUILDER_PROBE: Provider did not confirm the structured-response test.")
    return {"status": "ok", "detail": "Structured-response test passed. No business data was sent."}

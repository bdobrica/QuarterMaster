"""Bounded local llama.cpp inference, independent of the external builder provider."""

import asyncio
import json
from copy import deepcopy
from typing import Protocol

import httpx2 as httpx
from pydantic import ValidationError

from quartermaster.config import Settings
from quartermaster.contracts.advice import CompactAdvice
from quartermaster.contracts.teaching import GroundedAdvice
from quartermaster.errors import DomainError
from quartermaster.generation import PARAMETERS as PARAMETERS
from quartermaster.generation import checked_parameters, completed_choice
from quartermaster.spike.spec import MODEL_REVISION


def model_alias(sha256: str) -> str:
    return f"qm-base-{MODEL_REVISION}-{sha256}"


def identity(settings: Settings) -> str:
    if settings.local_base_url is None or settings.local_model_sha256 is None:
        raise DomainError(
            "LOCAL_CONFIG: Set up the pinned local base model using docs/milestone-4.md."
        )
    return model_alias(settings.local_model_sha256)


def response_schema(context: str) -> dict:
    """Constrain citations and align behavior/question fields during generation too."""
    schema = GroundedAdvice.model_json_schema()
    advice = schema["$defs"]["Advice"]
    refs = advice["properties"]["evidence_refs"]
    try:
        accessible = [
            item["citation_id"] for item in json.loads(context).get("retrieved_evidence", [])
        ]
    except (ValueError, KeyError, TypeError, RecursionError):
        raise DomainError("LOCAL_INPUT: Invalid assembled evidence context.") from None
    if accessible:
        refs["items"] = {"type": "string", "enum": accessible}
    else:
        refs["maxItems"] = 0
    branches = []
    for behavior in ("recommend", "clarify", "abstain"):
        branch = deepcopy(schema)
        branch.pop("$defs")
        props = branch["properties"]
        props["behavior"] = {"type": "string", "const": behavior}
        props["advice"] = deepcopy(advice)
        props["advice"]["properties"]["clarification_question"] = (
            {"type": "string", "minLength": 1, "maxLength": 4000}
            if behavior == "clarify"
            else {"type": "null"}
        )
        if behavior != "clarify":
            props["missing_information"]["maxItems"] = 0
        if behavior == "recommend":
            props["supporting_quotes"]["minItems"] = 1
        else:
            props["supporting_quotes"]["maxItems"] = 0
        branches.append(branch)
    return {"oneOf": branches}


def compact_response_schema(context: str) -> dict:
    """Version 2 only; keep the version 1 schema byte-for-byte replayable."""
    schema = CompactAdvice.model_json_schema()
    refs = schema["properties"]["evidence_refs"]
    accessible = [i["citation_id"] for i in json.loads(context)["retrieved_evidence"]]
    if accessible:
        refs["items"] = {"type": "string", "enum": accessible}
    else:
        refs["maxItems"] = 0
    schema["required"] = list(schema["properties"])
    branches = []
    for decision in ("answer", "clarify", "abstain"):
        branch = deepcopy(schema)
        branch["properties"]["decision"] = {"type": "string", "const": decision}
        branch["properties"]["question"] = (
            {"type": "string", "minLength": 1, "maxLength": 160}
            if decision == "clarify"
            else {"type": "null"}
        )
        branches.append(branch)
    return {"oneOf": branches}


class Inference(Protocol):
    async def advise(
        self, *, system: str, context: str, parameters: dict | None = None
    ) -> GroundedAdvice: ...


class CompletionError(DomainError):
    """Sanitized failure retaining token usage, never raw incomplete model text."""

    def __init__(self, message, status=422, *, completion_tokens=None):
        super().__init__(message, status)
        self.completion_tokens = completion_tokens


class LocalInference:
    def __init__(self, settings: Settings, *, transport=None, alias=None, base_url=None):
        self.settings = settings
        self.transport = transport
        self.lock = asyncio.Lock()
        self.alias = alias
        self.base_url = base_url

    async def advise(
        self, *, system: str, context: str, parameters: dict | None = None
    ) -> GroundedAdvice:
        draft, _ = await self.measured_advice(system=system, context=context, parameters=parameters)
        return draft

    async def measured_advice(self, *, system, context, parameters=None, compact=False):
        """Development comparison entry point; no mutable per-request usage state."""
        schema = compact_response_schema(context) if compact else response_schema(context)
        content, tokens = await self._completion(system, context, parameters, schema)
        try:
            model = CompactAdvice if compact else GroundedAdvice
            return model.model_validate_json(content), tokens
        except (ValueError, ValidationError):
            raise CompletionError(
                "LOCAL_JSON: Model returned invalid or incomplete advice; retry.",
                completion_tokens=tokens,
            ) from None

    async def _completion(self, system, context, parameters, schema):
        parameters = checked_parameters(parameters)
        alias = self.alias or identity(self.settings)
        if self.lock.locked():
            raise DomainError("LOCAL_BUSY: One local request is running; try again afterward.", 409)
        base = str(self.base_url or self.settings.local_base_url).rstrip("/")
        payload = {
            "model": alias,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": context},
            ],
            **parameters,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "grounded_advice",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode()
        if len(body) > 48000:
            raise DomainError("LOCAL_INPUT: Shorten the situation or mission.")
        try:
            async with self.lock, asyncio.timeout(self.settings.local_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self.settings.local_timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client:
                    # A trusted operator-controlled service verifies model bytes before startup.
                    # Reject an accidentally connected merged/other model before sending any case.
                    models = await self.read(client, "GET", base + "/models")
                    if [row["id"] for row in models["data"]] != [alias]:
                        raise DomainError(
                            "LOCAL_MODEL: Local server is not the configured base model."
                        )
                    response = await self.read(client, "POST", base + "/chat/completions", body)
            usage = response.get("usage")
            tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
            if type(tokens) is not int or tokens < 0:
                tokens = None
            try:
                content = completed_choice(response)
            except DomainError as exc:
                raise CompletionError(exc.message, exc.status, completion_tokens=tokens) from None
            return content, tokens
        except (TimeoutError, httpx.TimeoutException):
            raise DomainError("LOCAL_TIMEOUT: Local advice timed out; retry explicitly.") from None
        except httpx.HTTPError:
            raise DomainError(
                "LOCAL_CONNECTION: Start the local inference service and retry."
            ) from None
        except (ValueError, KeyError, TypeError, IndexError, RecursionError, ValidationError):
            raise DomainError(
                "LOCAL_JSON: Model returned invalid or incomplete advice; retry."
            ) from None

    @staticmethod
    async def read(client, method, url, body=None):
        async with client.stream(
            method, url, content=body, headers={"Content-Type": "application/json"}
        ) as response:
            if response.status_code != 200:
                raise DomainError(
                    "LOCAL_HTTP: Check the local model server and context size; retry."
                )
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 65536:
                    raise DomainError("LOCAL_SIZE: Local response exceeded 64 KiB; retry.")
        return json.loads(data)

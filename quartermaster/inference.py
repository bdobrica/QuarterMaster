"""Bounded local llama.cpp inference, independent of the external builder provider."""

import asyncio
import json
from copy import deepcopy
from typing import Protocol

import httpx2 as httpx
from pydantic import ValidationError

from quartermaster.config import Settings
from quartermaster.contracts.advice import CompactAdvice, DecisionOnly
from quartermaster.contracts.teaching import GroundedAdvice
from quartermaster.errors import DomainError
from quartermaster.generation import (
    ADVICE_PARAMETERS,
    checked_parameters,
    completed_choice,
    unambiguous_json,
)
from quartermaster.generation import PARAMETERS as PARAMETERS
from quartermaster.spike.spec import MODEL_REVISION


def model_alias(sha256: str, revision=MODEL_REVISION) -> str:
    return f"qm-base-{revision}-{sha256}"


def identity(settings: Settings) -> str:
    if settings.local_base_url is None or settings.local_model_sha256 is None:
        raise DomainError(
            "LOCAL_CONFIG: Set up the pinned local base model using docs/operator-guide.md."
        )
    return model_alias(settings.local_model_sha256, settings.local_model_revision)


def response_schema(context: str, *, bounded=False) -> dict:
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
    if bounded:
        # A flat schema leaves action selection to the model; application validation
        # still enforces behavior/question consistency. Historical schemas are unchanged.
        refs["maxItems"] = min(refs.get("maxItems", 3), 3)
        advice["properties"]["recommendation"]["maxLength"] = 400
        advice["properties"]["explanation"]["maxLength"] = 600
        advice["properties"]["limitations"]["maxItems"] = 3
        advice["properties"]["limitations"]["items"]["maxLength"] = 200
        advice["properties"]["clarification_question"] = {
            "anyOf": [{"type": "string", "minLength": 1, "maxLength": 240}, {"type": "null"}]
        }
        schema["properties"]["supporting_quotes"]["maxItems"] = 2
        schema["properties"]["supporting_quotes"]["items"]["maxLength"] = 240
        schema["properties"]["missing_information"]["maxItems"] = 1
        schema["properties"]["missing_information"]["items"]["maxLength"] = 160
        return schema
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

    async def predict(self, *, system, context, parameters=None):
        from quartermaster.prediction_context import parse_answer, schema_for

        content, _ = await self._completion(system, context, parameters, schema_for(context))
        try:
            return parse_answer(content, context)
        except (ValueError, TypeError, RecursionError):
            raise DomainError("PREDICTION_JSON: The model returned an invalid answer.") from None

    async def advise(
        self, *, system: str, context: str, parameters: dict | None = None
    ) -> GroundedAdvice:
        draft, _ = await self.measured_advice(system=system, context=context, parameters=parameters)
        return draft

    async def measured_advice(
        self,
        *,
        system,
        context,
        parameters=None,
        compact=False,
        schema_context=None,
        decision_only=False,
    ):
        """Development comparison entry point; no mutable per-request usage state."""
        if decision_only and (not compact or schema_context is not None):
            raise DomainError("LOCAL_INPUT: Decision-only decoding requires its own schema.")
        if schema_context is not None and not compact:
            raise DomainError("LOCAL_INPUT: A shared schema context requires compact advice.")
        # Context-selection experiments hold the full control's schema constant.
        # Only citation IDs enter the schema; the full context is not sent as a message.
        schema = (
            DecisionOnly.model_json_schema()
            if decision_only
            else compact_response_schema(schema_context if schema_context is not None else context)
            if compact
            else response_schema(context, bounded=parameters == ADVICE_PARAMETERS)
        )
        content, tokens = await self._completion(system, context, parameters, schema)
        try:
            if parameters == ADVICE_PARAMETERS:
                unambiguous_json(content)
            model = DecisionOnly if decision_only else CompactAdvice if compact else GroundedAdvice
            return model.model_validate_json(content), tokens
        except (ValueError, ValidationError, TypeError, RecursionError):
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
            if schema.get("title") == "Prediction" and response.get("model") != alias:
                raise DomainError("PREDICTION_IDENTITY: The model returned a different identity.")
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


HOSTED_SYSTEM_SUFFIX = """
Supporting quote contract (hosted/v1): for recommend, copy 1-2 short contiguous
substrings exactly from case.situation into supporting_quotes. Copy the characters
inside the JSON string only: do not add quotation marks, punctuation, escape-code
text, or normalize whitespace. Use case facts here; cite policy through evidence_refs.
"""

HOSTED_PARAMETERS = {"max_completion_tokens": 2048, "n": 1, "stream": False, "store": False}


def hosted_identity(settings):
    if settings.adviser_local_only:
        raise DomainError("ADVISER_LOCAL_ONLY: External advice is disabled on this installation.")
    if settings.adviser_base_url is None or settings.adviser_model is None:
        raise DomainError(
            "ADVISER_CONFIG: Configure an adviser endpoint and model, or use local advice."
        )
    return str(settings.adviser_base_url).rstrip("/"), settings.adviser_model


def hosted_parameters(settings):
    parameters = dict(HOSTED_PARAMETERS)
    if settings.adviser_reasoning_effort:
        parameters["reasoning_effort"] = settings.adviser_reasoning_effort
    return parameters


def hosted_schema(context):
    schema = response_schema(context, bounded=True)

    def required(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
            node.pop("default", None)
            for value in node.values():
                required(value)
        elif isinstance(node, list):
            for value in node:
                required(value)

    required(schema)
    return schema


class HostedInference(LocalInference):
    """One bounded, explicit hosted request; consent is enforced by the project harness.

    Separate credentials/configuration from builder drafting. No model-list probe,
    fallback, redirect, tool execution, or automatic billable retry.
    """

    async def advise(self, *, system, context, parameters=None):
        try:
            return await super().advise(system=system, context=context, parameters=parameters)
        except CompletionError:
            raise DomainError("ADVISER_JSON: Invalid or incomplete provider advice.") from None

    async def _completion(self, system, context, parameters, schema):
        from quartermaster.builder import credential

        checked_parameters(parameters)
        base, model = hosted_identity(self.settings)
        key_settings = Settings(
            _env_file=None,
            builder_api_key=self.settings.adviser_api_key,
            builder_api_key_file=self.settings.adviser_api_key_file,
        )
        try:
            key = credential(key_settings)
        except DomainError:
            raise DomainError("ADVISER_KEY: Check the adviser key or secret file.") from None
        body = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": context},
                ],
                **hosted_parameters(self.settings),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "grounded_advice",
                        "strict": True,
                        "schema": hosted_schema(context),
                    },
                },
            },
            ensure_ascii=False,
        ).encode()
        if len(body) > 48000:
            raise DomainError(
                "ADVISER_INPUT: Shorten the situation or mission (48 KB request limit)."
            )
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        try:
            async with asyncio.timeout(self.settings.adviser_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self.settings.adviser_timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        base + "/chat/completions",
                        content=body,
                        headers=headers,
                    ) as response:
                        if response.status_code != 200:
                            raise DomainError(
                                "ADVISER_HTTP: Check access, quota, model and schema support; "
                                "retry explicitly."
                            )
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 65536:
                                raise DomainError(
                                    "ADVISER_SIZE: Provider response exceeded 64 KiB."
                                )
            envelope = json.loads(data)
            content = completed_choice(envelope)
            unambiguous_json(content)
            usage = envelope.get("usage", {})
            tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
            return content, tokens if type(tokens) is int and tokens >= 0 else None
        except (TimeoutError, httpx.TimeoutException):
            raise DomainError("ADVISER_TIMEOUT: Provider timed out; retry explicitly.") from None
        except httpx.HTTPError:
            raise DomainError(
                "ADVISER_CONNECTION: Check provider connectivity; retry explicitly."
            ) from None
        except DomainError as exc:
            if exc.message.startswith("LOCAL_"):
                raise DomainError(
                    "ADVISER_COMPLETION: Provider did not finish a valid answer."
                ) from None
            raise
        except (ValueError, KeyError, TypeError, IndexError, RecursionError):
            raise DomainError(
                "ADVISER_JSON: Invalid or incomplete provider advice; retry explicitly."
            ) from None

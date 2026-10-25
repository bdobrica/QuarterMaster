import asyncio
import json

import httpx2 as httpx
import pytest

from muster.provider import ProviderSettings, SchemaProvider, SuggestionError
from tests.muster.test_schema import SETTINGS, completion


@pytest.mark.parametrize(
    "failure", ["timeout", "401", "redirect", "bad-json", "refusal", "truncated", "tool", "large"]
)
def test_provider_failures_are_bounded_and_do_not_disclose_response(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-test-key")
        if failure == "401":
            return httpx.Response(401, text="secret-test-key private provider detail")
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://another-provider.example/"})
        if failure == "bad-json":
            return httpx.Response(200, text="secret-test-key not JSON")
        if failure == "large":
            return httpx.Response(200, text="a" * (256 * 1024 + 1))
        response = completion().json()
        choice = response["choices"][0]
        if failure == "refusal":
            choice["message"]["refusal"] = "secret-test-key"
        elif failure == "tool":
            choice["message"]["tool_calls"] = [{"name": "read_secret_file"}]
        else:
            choice["finish_reason"] = "length"
        return httpx.Response(200, json=response)

    provider = SchemaProvider(SETTINGS, httpx.MockTransport(handler))
    with pytest.raises(SuggestionError) as exc:
        asyncio.run(provider.suggest({"guidance": "", "samples": []}))
    assert "secret-test-key" not in str(exc.value)
    assert len(calls) == 1  # No automatic retry or redirect sends sample content elsewhere.
    assert "secret-test-key" not in repr(SETTINGS)


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example/v1",
        "https://user:password@provider.example/v1",
        "https://provider.example/v1?api_key=secret",
        "file:///tmp/model",
    ],
)
def test_unsafe_provider_addresses_are_rejected(url):
    with pytest.raises(SuggestionError):
        ProviderSettings(url, "model", "secret").validate()


def test_local_provider_can_omit_key():
    ProviderSettings("http://127.0.0.1:1234/v1", "local-model").validate()


def test_reasoning_effort_is_sent_and_recorded_without_secrets():
    settings = ProviderSettings("https://provider.example/v1", "vision", "private-key", "high")
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return completion()

    asyncio.run(SchemaProvider(settings, httpx.MockTransport(handler)).suggest({"samples": []}))
    assert calls[0]["reasoning_effort"] == "high"
    assert settings.identity == {
        "base_url": settings.base_url,
        "model": "vision",
        "reasoning_effort": "high",
    }
    assert "private-key" not in json.dumps(settings.identity)
    with pytest.raises(SuggestionError):
        ProviderSettings(settings.base_url, "vision", "private-key", "invalid").validate()

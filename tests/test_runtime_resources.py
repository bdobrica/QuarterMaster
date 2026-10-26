"""Local serving may use available CPU capacity without changing frozen model contracts."""

import argparse
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from quartermaster import candidate_runtime, local_runtime
from quartermaster.model_pins import CAPABLE_REVISION


@pytest.mark.parametrize("value", ["0", "33", "2.5", "unlimited", "-1", True])
def test_serving_thread_limit_rejects_unbounded_or_invalid_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        local_runtime.thread_count(value)


@pytest.mark.parametrize(
    "args,environment,expected",
    [([], None, "4"), ([], "16", "16"), (["--threads", "8"], "16", "8")],
)
def test_base_runtime_uses_configured_cpu_limit_and_keeps_original_default(
    args, environment, expected, monkeypatch
):
    monkeypatch.delenv("QM_LOCAL_THREADS", raising=False)
    if environment is not None:
        monkeypatch.setenv("QM_LOCAL_THREADS", environment)
    monkeypatch.setattr("sys.argv", ["runtime", *args])
    monkeypatch.setattr(
        local_runtime, "verify", lambda root: {"revision": CAPABLE_REVISION, "sha256": "a" * 64}
    )
    calls = []
    monkeypatch.setattr(local_runtime.os, "execvp", lambda name, command: calls.append(command))
    local_runtime.main()
    command = calls[0]
    assert command[command.index("-t") + 1] == expected
    assert command[command.index("-c") + 1] == "8192"
    assert command[command.index("--chat-template-kwargs") + 1] == '{"enable_thinking":true}'


def test_candidate_gateway_uses_same_configured_threads_without_changing_profile(
    tmp_path, monkeypatch
):
    commands = []
    model = SimpleNamespace(stat=lambda: SimpleNamespace(st_size=1_000_001))
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(candidate_runtime, "verify", lambda *args: (model, "verified-alias"))
    monkeypatch.setattr(
        candidate_runtime.subprocess,
        "Popen",
        lambda command, **kwargs: commands.append(command) or process,
    )
    monkeypatch.setattr(candidate_runtime.urllib.request, "urlopen", lambda *a, **kw: nullcontext())
    gateway = candidate_runtime.Gateway(tmp_path, threads=16)
    assert gateway.select("candidate") == "verified-alias"
    command = commands[0]
    assert command[command.index("-t") + 1] == "16"
    assert command[command.index("--chat-template-kwargs") + 1] == '{"enable_thinking":false}'

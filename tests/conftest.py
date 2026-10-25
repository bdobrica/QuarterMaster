import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quartermaster.app import create_app
from quartermaster.config import Settings


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    for name in (
        "QM_DATA_DIR",
        "QM_MUSTER_DATA_DIR",
        "MUSTER_DATA_DIR",
        "MUSTER_AI_BASE_URL",
        "MUSTER_AI_MODEL",
        "MUSTER_AI_API_KEY",
        "MUSTER_AI_REASONING_EFFORT",
        "QM_BUILDER_BASE_URL",
        "QM_BUILDER_MODEL",
        "QM_BUILDER_API_KEY",
        "QM_BUILDER_API_KEY_FILE",
        "QM_BUILDER_TIMEOUT_SECONDS",
        "QM_BUILDER_MAX_INPUT_BYTES",
        "QM_ADVISER_BASE_URL",
        "QM_ADVISER_MODEL",
        "QM_ADVISER_API_KEY",
        "QM_ADVISER_API_KEY_FILE",
        "QM_ADVISER_TIMEOUT_SECONDS",
        "QM_ADVISER_LOCAL_ONLY",
        "QM_ADVISER_REASONING_EFFORT",
        "QM_LOCAL_BASE_URL",
        "QM_LOCAL_MODEL_SHA256",
        "QM_LOCAL_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    original = socket.socket.connect

    def local_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("CPU fixtures must not use the network")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", _env_file=None)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def project_fixture():
    path = Path(__file__).parent / "fixtures" / "project.json"
    return json.loads(path.read_text())

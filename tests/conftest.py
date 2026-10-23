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
        "QM_BUILDER_BASE_URL",
        "QM_BUILDER_MODEL",
        "QM_BUILDER_API_KEY",
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

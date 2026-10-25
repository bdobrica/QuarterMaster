from muster.__main__ import main
from muster.provider import ProviderSettings


def test_launch_loads_local_env_before_app_and_preserves_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        'MUSTER_AI_BASE_URL=https://provider.example/v1\nMUSTER_AI_MODEL="vision-model"\nMUSTER_AI_API_KEY=literal-${SECRET}-key\n'
    )
    for name in ("MUSTER_AI_BASE_URL", "MUSTER_AI_MODEL", "MUSTER_AI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SECRET", "must-not-expand")
    monkeypatch.setenv("MUSTER_AI_MODEL", "explicit-model")
    monkeypatch.setattr("sys.argv", ["muster", "--port", "8011"])
    calls = []
    monkeypatch.setattr(
        "muster.__main__.uvicorn.run",
        lambda *args, **kwargs: calls.append((args, kwargs, ProviderSettings.from_env())),
    )
    main()
    args, kwargs, settings = calls[0]
    assert args == ("muster.app:app",)
    assert kwargs == {"host": "127.0.0.1", "port": 8011}
    assert settings.base_url == "https://provider.example/v1"
    assert settings.model == "explicit-model"
    assert settings.api_key == "literal-${SECRET}-key"


def test_launch_without_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["muster"])
    calls = []
    monkeypatch.setattr("muster.__main__.uvicorn.run", lambda *args, **kwargs: calls.append(kwargs))
    main()
    assert calls == [{"host": "127.0.0.1", "port": 8000}]

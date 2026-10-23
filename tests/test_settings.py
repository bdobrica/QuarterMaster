from quartermaster.config import Settings


def test_safe_defaults_do_not_require_credentials_or_create_storage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert str(settings.data_dir) == "data"
    assert settings.builder_api_key is None
    assert settings.builder_base_url is None
    assert settings.builder_model is None
    assert not settings.data_dir.exists()


def test_dotenv_environment_precedence_and_secret_redaction(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("QM_DATA_DIR=from-file\nQM_BUILDER_API_KEY=sensitive-fixture\n")
    monkeypatch.setenv("QM_DATA_DIR", str(tmp_path / "from-environment"))
    settings = Settings(_env_file=dotenv)
    assert settings.data_dir == tmp_path / "from-environment"
    assert settings.builder_api_key.get_secret_value() == "sensitive-fixture"
    assert "sensitive-fixture" not in repr(settings)


def test_empty_compose_provider_settings_are_unconfigured(monkeypatch):
    monkeypatch.setenv("QM_BUILDER_BASE_URL", "")
    monkeypatch.setenv("QM_BUILDER_MODEL", "")
    monkeypatch.setenv("QM_BUILDER_API_KEY", "")
    settings = Settings(_env_file=None)
    assert settings.builder_base_url is None
    assert settings.builder_model is None
    assert settings.builder_api_key is None

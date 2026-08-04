import os
from pathlib import Path

import pytest

from mfit2keep import config
from mfit2keep.config import ConfigError, Settings, env_file, load_settings, state_dir


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MFIT_EMAIL",
        "MFIT_PASSWORD",
        "MFIT_TOKEN",
        "GOOGLE_EMAIL",
        "GOOGLE_MASTER_TOKEN",
        "MFIT2KEEP_STATE_DIR",
        "MFIT2KEEP_ENV_FILE",
        "XDG_STATE_HOME",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(name, raising=False)


def write_env(tmp_path: Path, body: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("MFIT2KEEP_ENV_FILE", str(path))
    return path


def test_reads_every_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_env(
        tmp_path,
        "MFIT_EMAIL=eu@exemplo.com\nMFIT_PASSWORD=senha\n"
        "GOOGLE_EMAIL=eu@gmail.com\nGOOGLE_MASTER_TOKEN=aas_et/abc\n",
        monkeypatch,
    )

    settings = load_settings()

    assert settings.email == "eu@exemplo.com"
    assert settings.password == "senha"
    assert settings.google_email == "eu@gmail.com"
    assert settings.google_master_token == "aas_et/abc"


def test_secrets_do_not_leak_into_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_env(tmp_path, "MFIT_PASSWORD=segredo\nGOOGLE_MASTER_TOKEN=aas_et/abc\n", monkeypatch)

    load_settings()

    # load_dotenv exportaria para os.environ, e qualquer subprocesso herdaria.
    assert "MFIT_PASSWORD" not in os.environ
    assert "GOOGLE_MASTER_TOKEN" not in os.environ


def test_surrounding_whitespace_is_trimmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_env(tmp_path, "MFIT_EMAIL=  eu@exemplo.com  \n", monkeypatch)

    assert load_settings().email == "eu@exemplo.com"


def test_empty_values_become_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_env(tmp_path, "MFIT_EMAIL=\nMFIT_TOKEN=\n", monkeypatch)

    settings = load_settings()

    assert settings.email is None
    assert settings.token is None


def test_environment_is_used_when_the_file_omits_a_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_env(tmp_path, "MFIT_EMAIL=eu@exemplo.com\n", monkeypatch)
    monkeypatch.setenv("MFIT_PASSWORD", "do-ambiente")

    assert load_settings().password == "do-ambiente"


def test_missing_env_file_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MFIT2KEEP_ENV_FILE", str(tmp_path / "nao-existe"))

    assert load_settings().email is None


def test_require_credentials_names_the_env_file() -> None:
    with pytest.raises(ConfigError, match="MFIT_EMAIL"):
        Settings(email=None, password=None, token=None).require_credentials()


def test_state_dir_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MFIT2KEEP_STATE_DIR", str(tmp_path / "estado"))

    assert state_dir() == tmp_path / "estado"


def test_state_dir_falls_back_to_xdg_outside_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Instalado como pacote, gravar segredo dentro do site-packages seria errado.
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setattr(config, "PACKAGE_ROOT", tmp_path / "site-packages")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))

    assert state_dir() == tmp_path / "xdg-state" / "mfit2keep"


def test_existing_legacy_state_dir_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tmp_path / "repo" / ".state"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setattr(config, "PACKAGE_ROOT", tmp_path / "repo")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))

    # Migrar sozinho quebraria o vínculo com as notas já criadas no Keep.
    assert state_dir() == legacy


def test_env_file_falls_back_to_xdg_outside_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))

    assert env_file() == tmp_path / "xdg-config" / "mfit2keep" / ".env"

import os
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

from mfit2keep import config, secure_io
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


def test_state_dir_lands_in_the_user_area_outside_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Instalado como pacote, gravar segredo dentro do site-packages seria errado.
    site_packages = tmp_path / "site-packages"
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setattr(config, "PACKAGE_ROOT", site_packages)

    destino = state_dir()

    assert destino.name == "mfit2keep"
    assert site_packages not in destino.parents


@pytest.mark.skipif(sys.platform != "linux", reason="XDG só vale no Linux")
def test_state_dir_honours_xdg_on_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setattr(config, "PACKAGE_ROOT", tmp_path / "site-packages")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))

    assert state_dir() == tmp_path / "xdg-state" / "mfit2keep"


@pytest.mark.skipif(sys.platform != "win32", reason="só o Windows usa LOCALAPPDATA")
def test_state_dir_uses_local_appdata_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # LOCALAPPDATA não sincroniza com o perfil: token de máquina não deve viajar.
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setattr(config, "PACKAGE_ROOT", tmp_path / "site-packages")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    assert state_dir() == tmp_path / "Local" / "mfit2keep"


def test_existing_legacy_state_dir_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tmp_path / "repo" / ".state"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setattr(config, "PACKAGE_ROOT", tmp_path / "repo")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))

    # Migrar sozinho quebraria o vínculo com as notas já criadas no Keep.
    assert state_dir() == legacy


def test_env_file_lands_in_the_user_area_outside_a_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "_IN_REPO", False)

    destino = env_file()

    assert destino.name == ".env"
    assert destino.parent.name == "mfit2keep"


@pytest.mark.skipif(sys.platform != "linux", reason="XDG só vale no Linux")
def test_env_file_honours_xdg_on_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))

    assert env_file() == tmp_path / "xdg-config" / "mfit2keep" / ".env"


@pytest.mark.skipif(sys.platform != "win32", reason="só o Windows usa APPDATA")
def test_env_file_uses_appdata_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_IN_REPO", False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    assert env_file() == tmp_path / "Roaming" / "mfit2keep" / ".env"


def test_replace_env_vars_removes_the_plaintext_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_env(tmp_path, "MFIT_EMAIL=eu@x.com\nMFIT_PASSWORD=segredo\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    content = path.read_text(encoding="utf-8")
    assert "segredo" not in content
    assert "MFIT_PASSWORD_ENC=blob" in content
    assert "MFIT_EMAIL=eu@x.com" in content


def test_replace_env_vars_also_removes_an_exported_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sem tratar `export`, o segredo em texto puro sobrevive à "proteção".
    path = write_env(tmp_path, "export MFIT_PASSWORD=segredo\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    assert "segredo" not in path.read_text(encoding="utf-8")


def test_replace_env_vars_keeps_comments_and_blank_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = "# minhas notas\n\nMFIT_EMAIL=eu@x.com\n# MFIT_TOKEN=colar aqui\nMFIT_PASSWORD=s\n"
    path = write_env(tmp_path, original, monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    content = path.read_text(encoding="utf-8")
    assert "# minhas notas" in content
    assert "# MFIT_TOKEN=colar aqui" in content


def test_replace_env_vars_creates_the_file_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MFIT2KEEP_ENV_FILE", str(tmp_path / "novo" / ".env"))

    path = config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    assert path.read_text(encoding="utf-8") == "MFIT_PASSWORD_ENC=blob\n"


@pytest.mark.skipif(not secure_io.POSIX, reason="modo de diretório é conceito POSIX")
def test_writing_the_env_does_not_tighten_an_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projeto = tmp_path / "projeto"
    projeto.mkdir(mode=0o755)
    write_env(projeto, "MFIT_PASSWORD=segredo\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    # Apertar a raiz do repositório para 0700 é efeito colateral, não segurança.
    assert projeto.stat().st_mode & 0o777 == 0o755


def test_replace_env_vars_removes_an_export_with_tab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # O dotenv aceita `export\tNOME=`; um removeprefix("export ") não pegaria.
    path = write_env(tmp_path, "export\tMFIT_PASSWORD=segredo\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    assert dotenv_values(path).get("MFIT_PASSWORD") is None


def test_variable_that_merely_starts_with_export_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_env(tmp_path, "exportD=4\nMFIT_PASSWORD=segredo\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    assert dotenv_values(path).get("exportD") == "4"


def test_multiline_secret_is_removed_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Descartar só a primeira linha deixaria a cauda do segredo no arquivo.
    path = write_env(
        tmp_path, 'MFIT_EMAIL=eu@x.com\nMFIT_PASSWORD="primeira\nsegunda"\n', monkeypatch
    )

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    content = path.read_text(encoding="utf-8")
    assert "primeira" not in content
    assert "segunda" not in content
    assert "MFIT_EMAIL=eu@x.com" in content


def test_quoted_single_line_value_does_not_swallow_the_next_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_env(tmp_path, 'MFIT_PASSWORD="segredo"\nMFIT_EMAIL=eu@x.com\n', monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    assert dotenv_values(path).get("MFIT_EMAIL") == "eu@x.com"


def test_writing_a_plaintext_value_is_not_mistaken_for_a_leftover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Gravar MFIT_PASSWORD em texto puro é uso legítimo (o painel faz isso no
    # primeiro uso); só a troca por uma versão _ENC exige que o texto puro suma.
    path = write_env(tmp_path, "MFIT_EMAIL=eu@x.com\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD=segredo"])

    assert dotenv_values(path).get("MFIT_PASSWORD") == "segredo"


def test_new_plaintext_password_invalidates_the_encrypted_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A forma cifrada tem precedência na leitura. Sem remover a antiga, trocar
    # a senha no painel não teria efeito nenhum — o app entraria com a velha.
    path = write_env(tmp_path, "MFIT_PASSWORD_ENC=blob-da-senha-velha\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD=senha-nova"])

    conteudo = dotenv_values(path)
    assert conteudo.get("MFIT_PASSWORD") == "senha-nova"
    assert conteudo.get("MFIT_PASSWORD_ENC") is None


def test_encrypting_still_removes_the_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_env(tmp_path, "MFIT_PASSWORD=texto-puro\n", monkeypatch)

    config.replace_env_vars(["MFIT_PASSWORD_ENC=blob"])

    conteudo = dotenv_values(path)
    assert conteudo.get("MFIT_PASSWORD") is None
    assert conteudo.get("MFIT_PASSWORD_ENC") == "blob"

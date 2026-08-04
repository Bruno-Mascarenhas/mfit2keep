import subprocess
import sys

import pytest

from mfit2keep import secrets_store
from mfit2keep.secrets_store import Backend, SecretsError, backend_of, credential_name, resolve

requires_systemd_creds = pytest.mark.skipif(
    not secrets_store.cipher_available(),
    reason="sem cifragem local nesta máquina",
)


def test_credential_name_is_namespaced() -> None:
    assert credential_name("MFIT_PASSWORD") == "mfit2keep.mfit_password"


def test_backend_reports_plaintext() -> None:
    assert backend_of(plaintext="senha", encrypted=None) is Backend.PLAINTEXT


def test_backend_reports_encrypted() -> None:
    assert backend_of(plaintext=None, encrypted="blob") is Backend.ENCRYPTED


def test_backend_reports_absent() -> None:
    assert backend_of(plaintext=None, encrypted=None) is Backend.ABSENT


def test_encrypted_wins_over_plaintext_in_the_backend_report() -> None:
    # Deixar a variável antiga preenchida por engano não pode "rebaixar" o status.
    assert backend_of(plaintext="senha", encrypted="blob") is Backend.ENCRYPTED


def test_resolve_returns_plaintext_when_there_is_no_blob() -> None:
    assert resolve("mfit_password", plaintext="senha", encrypted=None) == "senha"


def test_resolve_without_anything_is_none() -> None:
    assert resolve("mfit_password", plaintext=None, encrypted=None) is None


def test_resolve_prefers_the_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets_store, "decrypt", lambda _key, _blob: "do-blob")

    assert resolve("mfit_password", plaintext="do-texto-puro", encrypted="blob") == "do-blob"


def test_backend_matches_the_operating_system() -> None:
    esperado = {
        "linux": secrets_store.SystemdCredsBackend,
        "win32": secrets_store.DpapiBackend,
    }.get(sys.platform, secrets_store.UnavailableBackend)

    assert isinstance(secrets_store.backend, esperado)


def test_unsupported_system_explains_the_alternative() -> None:
    backend = secrets_store.UnavailableBackend()

    assert not backend.available()
    with pytest.raises(SecretsError, match="keyring"):
        backend.encrypt("mfit_password", "senha")


def test_secret_never_goes_through_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(command, 0, stdout="blob", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    secrets_store.SystemdCredsBackend().encrypt("mfit_password", "minha-senha")

    # argv é visível para qualquer usuário via ps; o segredo tem que ir por stdin.
    assert "minha-senha" not in " ".join(captured["command"])  # type: ignore[arg-type]
    assert captured["input"] == "minha-senha"


def test_failure_message_does_not_include_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Name doesn't match")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SecretsError, match="Name doesn't match") as info:
        secrets_store.SystemdCredsBackend().encrypt("mfit_password", "minha-senha")

    assert "minha-senha" not in str(info.value)


def test_missing_binary_becomes_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("systemd-creds")

    monkeypatch.setattr(subprocess, "run", explode)

    with pytest.raises(SecretsError, match="Não foi possível cifrar"):
        secrets_store.SystemdCredsBackend().encrypt("mfit_password", "senha")


@requires_systemd_creds
def test_round_trip_on_this_machine() -> None:
    blob = secrets_store.encrypt("mfit_password", "senha-de-teste")

    assert secrets_store.decrypt("mfit_password", blob) == "senha-de-teste"


@requires_systemd_creds
def test_blob_does_not_contain_the_secret() -> None:
    blob = secrets_store.encrypt("mfit_password", "senha-de-teste")

    assert "senha-de-teste" not in blob


@requires_systemd_creds
def test_blob_is_bound_to_its_name() -> None:
    blob = secrets_store.encrypt("mfit_password", "senha-de-teste")

    # Nome diferente não decifra: o blob não é reutilizável para outro segredo.
    with pytest.raises(SecretsError):
        secrets_store.decrypt("google_master_token", blob)


@requires_systemd_creds
def test_blob_is_single_line_for_the_env_file() -> None:
    blob = secrets_store.encrypt("mfit_password", "senha-de-teste")

    # Um .env não aceita valor multilinha sem aspas.
    assert "\n" not in blob

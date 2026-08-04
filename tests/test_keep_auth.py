from pathlib import Path
from typing import Any

import gpsoauth
import keyring
import pytest
from keyring.errors import KeyringError

from mfit2keep import keep_auth
from mfit2keep.config import Settings
from mfit2keep.keep_auth import KeepAuthError, KeepCredentials


@pytest.fixture(autouse=True)
def isolated_token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keep_auth, "TOKEN_FILE", tmp_path / "keep_token.json")


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    store: dict[tuple[str, str], str] = {}

    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setattr(keyring, "get_password", lambda s, u: store.get((s, u)))
    return store


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "email": None,
        "password": None,
        "token": None,
        "google_email": "eu@gmail.com",
        "google_master_token": None,
    }
    return Settings(**(base | overrides))


def test_device_id_is_sixteen_hex_chars() -> None:
    device_id = keep_auth.new_device_id()

    assert len(device_id) == 16
    assert int(device_id, 16) >= 0


def test_env_token_is_used_directly(fake_keyring: dict[tuple[str, str], str]) -> None:
    credentials = keep_auth.load(settings(google_master_token="aas_et/abc"))

    assert credentials.master_token == "aas_et/abc"
    assert credentials.email == "eu@gmail.com"


def test_env_device_id_is_stable_across_calls() -> None:
    first = keep_auth.load(settings(google_master_token="aas_et/abc"))
    second = keep_auth.load(settings(google_master_token="aas_et/abc"))

    # Device id novo a cada execução parece aparelho novo para o Google.
    assert first.device_id == second.device_id


def test_oauth_cookie_in_env_is_rejected_with_a_useful_message() -> None:
    # É o erro nº1 do fluxo, e o gkeepapi só diz "LoginException: Unknown".
    with pytest.raises(KeepAuthError, match="ainda precisa ser trocado"):
        keep_auth.load(settings(google_master_token="oauth2_4/0Adeu5"))


def test_env_token_without_google_email_is_rejected() -> None:
    with pytest.raises(KeepAuthError, match="GOOGLE_EMAIL"):
        keep_auth.load(settings(google_email=None, google_master_token="aas_et/abc"))


def test_store_then_load_round_trips_through_keyring(
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    keep_auth.store(KeepCredentials("eu@gmail.com", "aas_et/abc", "dead"))

    credentials = keep_auth.load(settings())

    assert credentials == KeepCredentials("eu@gmail.com", "aas_et/abc", "dead")


@pytest.mark.filterwarnings("ignore::mfit2keep.keep_auth.KeyringUnavailableWarning")
def test_store_falls_back_to_file_without_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object) -> None:
        raise KeyringError("sem D-Bus")

    monkeypatch.setattr(keyring, "set_password", explode)
    monkeypatch.setattr(keyring, "get_password", explode)

    where = keep_auth.store(KeepCredentials("eu@gmail.com", "aas_et/abc", "dead"))

    assert where == str(keep_auth.TOKEN_FILE)
    assert keep_auth.load(settings()).master_token == "aas_et/abc"


@pytest.mark.filterwarnings("ignore::mfit2keep.keep_auth.KeyringUnavailableWarning")
def test_token_file_is_not_world_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyring, "set_password", lambda *_: (_ for _ in ()).throw(KeyringError()))

    keep_auth.store(KeepCredentials("eu@gmail.com", "aas_et/abc", "dead"))

    # O master token equivale à senha da conta.
    assert keep_auth.TOKEN_FILE.stat().st_mode & 0o077 == 0


def test_missing_token_asks_for_keep_login(fake_keyring: dict[tuple[str, str], str]) -> None:
    with pytest.raises(KeepAuthError, match="keep-login"):
        keep_auth.load(settings())


def test_corrupted_payload_is_reported(fake_keyring: dict[tuple[str, str], str]) -> None:
    fake_keyring[(keep_auth.SERVICE, "eu@gmail.com")] = "{nao é json"

    with pytest.raises(KeepAuthError, match="corrompidas"):
        keep_auth.load(settings())


async def test_exchange_returns_the_master_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpsoauth, "exchange_token", lambda *_args, **_kw: {"Token": "aas_et/novo"})

    assert await keep_auth.exchange_oauth_token("eu@gmail.com", "oauth2_4/x") == "aas_et/novo"


async def test_exchange_failure_explains_single_use_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gpsoauth, "exchange_token", lambda *_args, **_kw: {"Error": "BadAuthentication"}
    )

    with pytest.raises(KeepAuthError, match="uso único"):
        await keep_auth.exchange_oauth_token("eu@gmail.com", "oauth2_4/velho")


def test_token_is_reachable_without_google_email_in_the_env(
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    # `keep-login --email` aceita a conta sem gravá-la em lugar nenhum.
    keep_auth.store(KeepCredentials("outra@gmail.com", "aas_et/abc", "dead"))

    credentials = keep_auth.load(settings(google_email=None))

    assert credentials.master_token == "aas_et/abc"
    assert credentials.email == "outra@gmail.com"


def test_stored_token_is_written_under_both_keys(
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    keep_auth.store(KeepCredentials("eu@gmail.com", "aas_et/abc", "dead"))

    assert (keep_auth.SERVICE, "eu@gmail.com") in fake_keyring
    assert (keep_auth.SERVICE, keep_auth.DEFAULT_ACCOUNT) in fake_keyring


def test_forget_clears_both_keys(
    fake_keyring: dict[tuple[str, str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(keyring, "delete_password", lambda s, u: fake_keyring.pop((s, u), None))
    keep_auth.store(KeepCredentials("eu@gmail.com", "aas_et/abc", "dead"))

    keep_auth.forget("eu@gmail.com")

    assert fake_keyring == {}


def test_plaintext_fallback_is_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object) -> None:
        raise KeyringError("sem D-Bus")

    monkeypatch.setattr(keyring, "set_password", explode)

    # Em cron/SSH o keyring some; degradar para texto puro em silêncio é o pior caso.
    with pytest.warns(keep_auth.KeyringUnavailableWarning, match="texto puro"):
        keep_auth.store(KeepCredentials("eu@gmail.com", "aas_et/abc", "dead"))


def test_reading_from_the_plaintext_file_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object) -> None:
        raise KeyringError("sem D-Bus")

    monkeypatch.setattr(keyring, "set_password", explode)
    monkeypatch.setattr(keyring, "get_password", explode)
    with pytest.warns(keep_auth.KeyringUnavailableWarning):
        keep_auth.store(KeepCredentials("eu@gmail.com", "aas_et/abc", "dead"))

    with pytest.warns(keep_auth.KeyringUnavailableWarning, match="texto puro"):
        keep_auth.load(settings())

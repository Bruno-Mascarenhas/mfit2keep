"""O painel local: isolamento, e nenhum segredo de volta para o navegador."""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mfit2keep import keep_auth, secrets_store, web
from mfit2keep.config import ConfigError
from mfit2keep.sources.mfit import MfitSource
from mfit2keep.sources.mfit_api import MfitError


@pytest.fixture
def painel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    """Sobe o servidor numa porta livre e devolve (url_base, token)."""
    monkeypatch.setenv("MFIT2KEEP_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("MFIT2KEEP_STATE_DIR", str(tmp_path / "estado"))

    servidor, url = web.build_server(0)
    base, token = url.split("/?t=")
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        yield base, token
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=5)


def pedir(
    base: str, rota: str, token: str | None = None, corpo: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    dados = None if corpo is None else json.dumps(corpo).encode("utf-8")
    requisicao = urllib.request.Request(base + rota, data=dados)
    requisicao.add_header("Content-Type", "application/json")
    if token is not None:
        requisicao.add_header("X-Token", token)
    try:
        with urllib.request.urlopen(requisicao, timeout=10) as resposta:
            return resposta.status, json.loads(resposta.read())
    except urllib.error.HTTPError as erro:
        return erro.code, json.loads(erro.read())


def test_serves_the_page_without_a_token(painel: tuple[str, str]) -> None:
    base, _ = painel

    with urllib.request.urlopen(base + "/", timeout=10) as resposta:
        corpo = resposta.read().decode("utf-8")

    # A página em si não é segredo — o que ela faz é que exige token.
    assert resposta.status == 200
    assert "mfit2keep" in corpo


def test_api_refuses_without_token(painel: tuple[str, str]) -> None:
    base, _ = painel

    status, corpo = pedir(base, "/api/estado")

    assert status == 403
    assert "Token" in corpo["erro"]


def test_api_refuses_with_the_wrong_token(painel: tuple[str, str]) -> None:
    base, _ = painel

    status, _ = pedir(base, "/api/estado", token="chute")

    assert status == 403


def test_write_action_refuses_without_token(painel: tuple[str, str]) -> None:
    base, _ = painel

    status, _ = pedir(base, "/api/config", corpo={"mfit_email": "invasor@x.com"})

    assert status == 403


def test_state_never_returns_the_secrets(painel: tuple[str, str]) -> None:
    base, token = painel
    pedir(
        base,
        "/api/config",
        token,
        {"mfit_email": "eu@x.com", "mfit_password": "minha-senha", "google_email": "eu@gmail.com"},
    )

    status, estado = pedir(base, "/api/estado", token)

    assert status == 200
    # A tela mostra "tem senha", nunca a senha.
    assert "minha-senha" not in json.dumps(estado)
    assert estado["tem_senha"] is True
    assert estado["mfit_email"] == "eu@x.com"


def test_saving_writes_the_env_file(painel: tuple[str, str], tmp_path: Path) -> None:
    base, token = painel

    status, _ = pedir(
        base, "/api/config", token, {"mfit_email": "eu@x.com", "mfit_password": "segredo"}
    )

    assert status == 200
    conteudo = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "MFIT_EMAIL=eu@x.com" in conteudo


def test_saving_without_password_keeps_the_previous_one(
    painel: tuple[str, str], tmp_path: Path
) -> None:
    base, token = painel
    pedir(base, "/api/config", token, {"mfit_email": "eu@x.com", "mfit_password": "segredo"})

    # Campo de senha em branco significa "não mexer", não "apagar".
    pedir(base, "/api/config", token, {"mfit_email": "outro@x.com"})

    conteudo = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "MFIT_PASSWORD=segredo" in conteudo
    assert "MFIT_EMAIL=outro@x.com" in conteudo


def test_empty_save_is_reported(painel: tuple[str, str]) -> None:
    base, token = painel

    status, corpo = pedir(base, "/api/config", token, {})

    assert status == 400
    assert "Nada para salvar" in corpo["erro"]


def test_expected_error_becomes_a_message_not_a_crash(
    painel: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, token = painel

    def explode(_payload: dict[str, Any]) -> dict[str, Any]:
        raise ConfigError("faltou alguma coisa")

    monkeypatch.setitem(web.ACTIONS, "/api/proteger", explode)

    status, corpo = pedir(base, "/api/proteger", token, {})

    assert status == 400
    assert corpo["erro"] == "faltou alguma coisa"


def test_unknown_route_is_not_found(painel: tuple[str, str]) -> None:
    base, token = painel

    status, _ = pedir(base, "/api/inexistente", token, {})

    assert status == 404


def test_static_files_are_served(painel: tuple[str, str]) -> None:
    base, _ = painel

    with urllib.request.urlopen(base + "/static/app.js", timeout=10) as resposta:
        assert resposta.status == 200
        assert "text/javascript" in resposta.headers["Content-Type"]


def test_directory_traversal_is_blocked(painel: tuple[str, str]) -> None:
    base, _ = painel

    status, _ = pedir(base, "/static/../../../etc/passwd")

    assert status == 404


def test_each_run_gets_a_different_token() -> None:
    primeiro, url_a = web.build_server(0)
    segundo, url_b = web.build_server(0)
    try:
        assert url_a.split("?t=")[1] != url_b.split("?t=")[1]
    finally:
        primeiro.server_close()
        segundo.server_close()


def test_server_binds_only_to_loopback() -> None:
    servidor, _ = web.build_server(0)
    try:
        # Escutar em 0.0.0.0 exporia a senha para a rede local.
        assert servidor.server_address[0] == "127.0.0.1"
    finally:
        servidor.server_close()


def test_frontend_files_exist() -> None:
    diretorio = web.frontend_dir()

    assert (diretorio / "index.html").is_file()
    assert (diretorio / "app.js").is_file()
    assert (diretorio / "style.css").is_file()


def test_state_queries_the_keyring_only_once(
    painel: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    chamadas = 0
    original = keep_auth.stored_backend

    def contando(settings: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return original(settings)

    monkeypatch.setattr(keep_auth, "stored_backend", contando)

    web.read_state()

    # A tela recarrega o estado depois de cada ação; cada consulta bate no keyring.
    assert chamadas == 1


def test_exception_group_from_the_task_group_becomes_a_message(
    painel: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, token = painel

    def explode(_payload: dict[str, Any]) -> dict[str, Any]:
        # Os dias vêm de um TaskGroup: o erro chega sempre embrulhado.
        raise ExceptionGroup("dias", [MfitError("token expirou")])

    monkeypatch.setitem(web.ACTIONS, "/api/sync", explode)

    status, corpo = pedir(base, "/api/sync", token, {})

    assert status == 400
    assert corpo["erro"] == "token expirou"


def test_listing_routines_without_step_one_says_what_to_do(painel: tuple[str, str]) -> None:
    base, token = painel

    status, corpo = pedir(base, "/api/rotinas", token, {})

    assert status == 400
    assert "passo 1" in corpo["erro"]


def test_sync_without_the_keep_token_fails_before_touching_the_network(
    painel: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, token = painel
    pedir(base, "/api/config", token, {"mfit_email": "eu@x.com", "mfit_password": "segredo"})

    async def nunca(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("não deveria ter buscado os treinos na rede")

    monkeypatch.setattr(MfitSource, "fetch_workouts", nunca)

    status, corpo = pedir(base, "/api/sync", token, {"routine_id": "1"})

    assert status == 400
    assert "passo 2" in corpo["erro"]


def test_changing_the_password_keeps_it_protected(
    painel: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, token = painel
    monkeypatch.setattr(secrets_store, "cipher_available", lambda: True)
    monkeypatch.setattr(secrets_store, "encrypt", lambda _chave, valor: f"cifrado:{valor}")
    pedir(base, "/api/config", token, {"mfit_email": "eu@x.com", "mfit_password": "velha"})
    pedir(base, "/api/proteger", token, {})

    _, corpo = pedir(base, "/api/config", token, {"mfit_password": "nova"})

    # Gravar em texto puro invalida o cifrado; sem recifrar, trocar a senha
    # desprotegeria o .env sem o usuário perceber.
    assert corpo["senha_cifrada"] is True
    assert "protegida" in corpo["mensagem"]


def test_changing_the_password_warns_when_it_cannot_reprotect(
    painel: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, token = painel
    monkeypatch.setattr(secrets_store, "cipher_available", lambda: True)
    monkeypatch.setattr(secrets_store, "encrypt", lambda _chave, valor: f"cifrado:{valor}")
    pedir(base, "/api/config", token, {"mfit_email": "eu@x.com", "mfit_password": "velha"})
    pedir(base, "/api/proteger", token, {})

    monkeypatch.setattr(secrets_store, "cipher_available", lambda: False)
    _, corpo = pedir(base, "/api/config", token, {"mfit_password": "nova"})

    assert corpo["senha_cifrada"] is False
    assert "texto puro" in corpo["mensagem"]


def test_the_anonymous_window_step_does_not_offer_a_normal_link() -> None:
    pagina = (web.frontend_dir() / "index.html").read_text(encoding="utf-8")

    # Um link abriria aba normal — o contrário do que o passo manda fazer.
    assert 'href="https://accounts.google.com/EmbeddedSetup"' not in pagina
    assert "endereco-google" in pagina

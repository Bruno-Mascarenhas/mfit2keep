"""Painel local para quem não usa terminal.

Um servidor HTTP mínimo (só biblioteca padrão, sem build e sem npm) que abre no
navegador e cobre o caminho inteiro: preencher o ``.env``, fazer o ritual do
master token, cifrar os segredos e sincronizar.

Três decisões de segurança, porque esta tela manipula senha e master token:

* escuta **só em 127.0.0.1** — nada de rede;
* toda chamada exige o cabeçalho ``X-Token`` com um segredo sorteado na hora.
  Qualquer página que você visite pode fazer POST para ``localhost``, mas não
  consegue ler o token nem mandar cabeçalho customizado sem passar pelo CORS;
* **nenhum segredo volta para o navegador** — a tela mostra "preenchido" ou
  "vazio", nunca o valor.
"""

import asyncio
import json
import secrets
import threading
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mfit2keep import keep_auth, secrets_store
from mfit2keep.config import ConfigError, env_file, load_settings, replace_env_vars
from mfit2keep.destinations.base import NoteDestination, NoteResult
from mfit2keep.destinations.local import LocalMarkdownDestination
from mfit2keep.errors import EXPECTED_ERRORS, expected_from
from mfit2keep.keep_auth import KeepAuthError
from mfit2keep.render import routine_to_notes
from mfit2keep.secure_io import write_secret
from mfit2keep.sources.mfit import MfitSource

HOST = "127.0.0.1"

#: Tipo dos arquivos servidos; o resto é recusado.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


def frontend_dir() -> Path:
    """Onde estão os arquivos da interface.

    No clone eles ficam em ``src/frontend``; instalados como pacote, o build
    os copia para dentro de ``mfit2keep/frontend``.
    """
    embarcado = Path(__file__).resolve().parent / "frontend"
    if embarcado.is_dir():
        return embarcado
    return Path(__file__).resolve().parents[1] / "frontend"


# ------------------------------------------------------------------ ações


def read_state() -> dict[str, Any]:
    """O que a tela precisa saber — sem devolver segredo nenhum."""
    settings = load_settings()
    # Uma consulta só: a tela recarrega o estado depois de cada ação, e cada
    # chamada destas bate no keyring.
    onde_esta_o_token = keep_auth.stored_backend(settings)
    return {
        "env_file": str(env_file()),
        "mfit_email": settings.email or "",
        "google_email": settings.google_email or "",
        "tem_senha": bool(settings.password or settings.password_enc),
        "senha_cifrada": bool(settings.password_enc),
        "token_keep": str(onde_esta_o_token),
        "tem_token_keep": onde_esta_o_token is not secrets_store.Backend.ABSENT,
        "cifragem_disponivel": secrets_store.cipher_available(),
        "cifragem_nome": secrets_store.cipher_name(),
    }


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Grava o ``.env`` preservando o que o usuário não mexeu."""
    senha_nova = str(payload.get("mfit_password") or "").strip()
    linhas: list[str] = []
    for variavel, valor in (
        ("MFIT_EMAIL", payload.get("mfit_email")),
        ("MFIT_PASSWORD", senha_nova),
        ("GOOGLE_EMAIL", payload.get("google_email")),
    ):
        texto = str(valor or "").strip()
        if texto:
            linhas.append(f"{variavel}={texto}")

    if not linhas:
        raise ConfigError("Nada para salvar.")

    # Gravar a senha em texto puro invalida a versão cifrada (é o que faz a
    # troca de senha ter efeito). Quem já tinha protegido não pode descobrir
    # sozinho que voltou ao texto puro.
    estava_cifrada = bool(load_settings().password_enc)

    caminho = env_file()
    if not caminho.exists():
        # Primeiro uso: o arquivo nasce restrito, não vazio e frouxo.
        write_secret(caminho, "")
    replace_env_vars(linhas)

    if not (senha_nova and estava_cifrada):
        return read_state()
    return {**_reproteger(senha_nova), **read_state()}


def _reproteger(senha: str) -> dict[str, Any]:
    """Recifra a senha recém-trocada, ou diz que ela ficou exposta."""
    if not secrets_store.cipher_available():
        return {
            "mensagem": "Salvo. Atenção: a senha voltou a ficar em texto puro no .env — "
            f"não há cifragem local aqui ({secrets_store.cipher_name()}).",
        }
    # Só a senha: cifrar todo o MANAGED mexeria também no master token.
    replace_env_vars([f"MFIT_PASSWORD_ENC={secrets_store.encrypt('mfit_password', senha)}"])
    return {"mensagem": "Salvo, e a senha nova já foi protegida."}


def exchange_keep_token(payload: dict[str, Any]) -> dict[str, Any]:
    cookie = str(payload.get("oauth_token") or "").strip()
    if not cookie:
        raise KeepAuthError("Cole o valor do cookie oauth_token.")

    email = str(payload.get("google_email") or "").strip() or load_settings().google_email
    if not email:
        raise KeepAuthError("Informe a conta Google antes.")

    async def run() -> str:
        device_id = keep_auth.new_device_id()
        master = await keep_auth.exchange_oauth_token(email, cookie, device_id)
        return keep_auth.store(keep_auth.KeepCredentials(email, master, device_id))

    onde = asyncio.run(run())
    return {"onde": onde, **read_state()}


def protect_secrets(_payload: dict[str, Any]) -> dict[str, Any]:
    if not secrets_store.cipher_available():
        raise ConfigError(
            f"Sem cifragem local nesta máquina ({secrets_store.cipher_name()}). "
            "A senha continua no .env e o master token, no keyring."
        )

    settings = load_settings()
    linhas = [
        f"{segredo.encrypted_var}={secrets_store.encrypt(segredo.key, texto)}"
        for segredo in secrets_store.MANAGED
        if (texto := settings.secret_pair(segredo.env_var)[0])
    ]
    if not linhas:
        return {"mensagem": "Nada em texto puro para cifrar.", **read_state()}

    replace_env_vars(linhas)
    return {"mensagem": f"{len(linhas)} segredo(s) cifrado(s).", **read_state()}


def _exigir(passo: str, estado: dict[str, Any], chave: str) -> None:
    """Barra a ação com a linguagem da tela, não a do terminal.

    As mensagens de ``config.py`` e ``keep_auth.py`` falam de variável de
    ambiente e de comando — certas para a CLI, inúteis para quem só viu a
    tela. E a checagem vem antes da rede: sem ela, faltar o passo 2 só
    aparecia depois de baixar todos os dias do treino.
    """
    if not estado[chave]:
        raise ConfigError(passo)


def list_routines(_payload: dict[str, Any]) -> dict[str, Any]:
    _exigir(
        "Preencha o passo 1 (e-mail e senha do MFIT) e clique em Salvar.",
        read_state(),
        "tem_senha",
    )

    async def run() -> list[dict[str, str]]:
        async with MfitSource(load_settings()) as source:
            return [
                {"id": rotina.id, "nome": rotina.name, "fim": rotina.ends_at or ""}
                for rotina in await source.list_routines()
            ]

    return {"rotinas": asyncio.run(run())}


def run_sync(payload: dict[str, Any]) -> dict[str, Any]:
    rotina = str(payload.get("routine_id") or "").strip()
    if not rotina:
        raise ConfigError("Escolha uma rotina.")
    destino = str(payload.get("destino") or "keep")

    estado = read_state()
    _exigir("Preencha o passo 1 (e-mail e senha do MFIT) e clique em Salvar.", estado, "tem_senha")
    if destino == "keep":
        _exigir(
            "Faça o passo 2 (Liberar o Google Keep) antes de criar as notas.",
            estado,
            "tem_token_keep",
        )

    async def run() -> list[NoteResult]:
        async with MfitSource(load_settings()) as source:
            treinos = await source.fetch_workouts(rotina)
        notas = routine_to_notes(treinos)
        async with _destination(destino) as saida:
            return await saida.upsert_all(notas)

    resultados = asyncio.run(run())
    return {
        "notas": [
            {"titulo": r.note_title, "acao": str(r.action), "onde": r.reference or ""}
            for r in resultados
        ]
    }


def _destination(destino: str) -> NoteDestination:
    if destino == "keep":
        from mfit2keep.destinations.keep import KeepDestination

        return KeepDestination(keep_auth.load(load_settings()))
    return LocalMarkdownDestination(Path.cwd() / "notas")


#: Rota -> ação. Tudo é POST menos o estado, para não cachear.
ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "/api/config": save_config,
    "/api/keep-login": exchange_keep_token,
    "/api/proteger": protect_secrets,
    "/api/rotinas": list_routines,
    "/api/sync": run_sync,
}


# ----------------------------------------------------------------- servidor


class Handler(BaseHTTPRequestHandler):
    """Serve a página e as ações. Instanciado pelo servidor a cada conexão."""

    token: str = ""
    server_version = "mfit2keep"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        """Silencia o log padrão: ele iria para stderr a cada clique."""

    # ------------------------------------------------------------- helpers

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # A página não embute nada de fora e não deve ser embutida por ninguém.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        """Confere o token do cabeçalho, em tempo constante."""
        enviado = self.headers.get("X-Token", "")
        return secrets.compare_digest(enviado, self.token)

    # ---------------------------------------------------------------- rotas

    def do_GET(self) -> None:
        caminho = self.path.split("?", 1)[0]
        if caminho in ("/", "/index.html"):
            self._serve_file("index.html")
        elif caminho == "/api/estado":
            if not self._authorized():
                self._send_json(HTTPStatus.FORBIDDEN, {"erro": "Token inválido."})
                return
            self._send_json(HTTPStatus.OK, read_state())
        elif caminho.startswith("/static/"):
            self._serve_file(caminho.removeprefix("/static/"))
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"erro": "Não encontrado."})

    def do_POST(self) -> None:
        caminho = self.path.split("?", 1)[0]
        acao = ACTIONS.get(caminho)
        if acao is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"erro": "Não encontrado."})
            return
        if not self._authorized():
            self._send_json(HTTPStatus.FORBIDDEN, {"erro": "Token inválido."})
            return

        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"erro": "Corpo inválido."})
            return

        try:
            self._send_json(HTTPStatus.OK, acao(payload))
        except EXPECTED_ERRORS as erro:
            # Erro previsto vira mensagem na tela; o resto sobe e aparece no log.
            self._send_json(HTTPStatus.BAD_REQUEST, {"erro": str(erro)})
        except BaseExceptionGroup as grupo:
            # Os dias vêm de um TaskGroup: sem desembrulhar, a conexão morreria
            # sem resposta e a tela só mostraria "erro de rede".
            if (previsto := expected_from(grupo)) is None:
                raise
            self._send_json(HTTPStatus.BAD_REQUEST, {"erro": str(previsto)})

    def _serve_file(self, nome: str) -> None:
        caminho = (frontend_dir() / nome).resolve()
        # Impede subir de diretório com "../".
        if not caminho.is_file() or frontend_dir().resolve() not in caminho.parents:
            self._send_json(HTTPStatus.NOT_FOUND, {"erro": "Não encontrado."})
            return
        tipo = CONTENT_TYPES.get(caminho.suffix)
        if tipo is None:
            self._send_json(HTTPStatus.FORBIDDEN, {"erro": "Tipo não servido."})
            return
        self._send(HTTPStatus.OK, caminho.read_bytes(), tipo)


def build_server(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Cria o servidor em 127.0.0.1 e devolve a URL já com o token.

    O token vive na subclasse: cada execução do painel tem o seu, e ele morre
    junto com o processo.
    """
    token = secrets.token_urlsafe(32)

    class BoundHandler(Handler):
        pass

    BoundHandler.token = token
    servidor = ThreadingHTTPServer((HOST, port), BoundHandler)
    porta = servidor.server_address[1]
    return servidor, f"http://{HOST}:{porta}/?t={token}"


def serve(port: int = 0, *, open_browser: bool = True) -> str:
    """Sobe o painel e devolve a URL. Bloqueia até Ctrl+C."""
    servidor, url = build_server(port)
    if open_browser:
        # Timer para o navegador só abrir depois que o servidor já aceita.
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever()
    finally:
        servidor.server_close()
    return url

"""Obtenção e guarda do *master token* do Google.

A API oficial do Keep (``keep.googleapis.com``) é exclusiva do Google Workspace —
conta pessoal ``@gmail.com`` não tem acesso. O único caminho que funciona é o
``gkeepapi``, autenticado com um *master token* (``aas_et/…``).

Esse token só sai de um ritual manual, feito uma vez:

1. Abra ``https://accounts.google.com/EmbeddedSetup`` numa janela anônima.
2. Faça login e clique em "Eu concordo". A página fica girando para sempre —
   é esperado, o fluxo é de setup de Android.
3. Abra o DevTools → Application → Cookies → ``https://accounts.google.com``
   e copie o valor do cookie ``oauth_token`` (começa com ``oauth2_4/``).
4. Rode ``mfit2keep keep-login`` e cole quando for pedido.

O master token equivale à senha da conta: dá acesso completo e não expira.
Por isso ele vai para o keyring do sistema, nunca para o ``.env``.
"""

import asyncio
import contextlib
import hashlib
import json
import secrets
from dataclasses import dataclass

import gpsoauth
import keyring
from keyring.errors import KeyringError

from .config import STATE_DIR, Settings

SERVICE = "mfit2keep"
#: Fallback quando não há keyring (servidor headless, container).
TOKEN_FILE = STATE_DIR / "keep_token.json"


class KeepAuthError(RuntimeError):
    """Falha ao obter ou recuperar o master token."""


@dataclass(frozen=True, slots=True)
class KeepCredentials:
    email: str
    master_token: str
    device_id: str


def new_device_id() -> str:
    """O gpsoauth espera um android_id de 16 dígitos hexadecimais.

    Uma vez gerado, é guardado junto do token e reusado: trocar de device_id a
    cada execução parece login de aparelho novo para o Google.
    """
    return secrets.token_hex(8)


def _stable_device_id(email: str) -> str:
    """android_id derivado do e-mail, para o token que vem do .env.

    Ali não há onde guardar um id sorteado, e mudar de device_id a cada
    execução parece aparelho novo para o Google.
    """
    return hashlib.sha256(email.encode()).hexdigest()[:16]


async def exchange_oauth_token(email: str, oauth_token: str, device_id: str | None = None) -> str:
    """Troca o cookie ``oauth_token`` pelo master token ``aas_et/…``."""
    device_id = device_id or new_device_id()
    response = await asyncio.to_thread(
        gpsoauth.exchange_token, email, oauth_token.strip(), device_id
    )

    token = response.get("Token")
    if not token:
        raise KeepAuthError(
            "O Google não devolveu o master token. Resposta: "
            f"{response.get('Error') or response}. "
            "O cookie oauth_token é de uso único — refaça o passo 1 numa aba anônima nova."
        )
    return token


def store(credentials: KeepCredentials) -> str:
    """Guarda no keyring; cai para arquivo 0600 se não houver keyring."""
    payload = json.dumps(
        {
            "email": credentials.email,
            "master_token": credentials.master_token,
            "device_id": credentials.device_id,
        }
    )
    try:
        keyring.set_password(SERVICE, credentials.email, payload)
    except KeyringError:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(payload, encoding="utf-8")
        TOKEN_FILE.chmod(0o600)
        return str(TOKEN_FILE)
    return f"keyring ({SERVICE})"


def load(settings: Settings) -> KeepCredentials:
    """Recupera as credenciais do Keep.

    Ordem de procura: ``.env`` (``GOOGLE_MASTER_TOKEN``), keyring, arquivo de
    fallback. O ``.env`` vem primeiro porque é explícito — quem o preencheu
    quis usá-lo.
    """
    email = settings.google_email

    if settings.google_master_token:
        if not email:
            raise KeepAuthError("Defina GOOGLE_EMAIL no .env — o Keep precisa saber a conta.")
        _reject_oauth_cookie(settings.google_master_token)
        return KeepCredentials(
            email=email,
            master_token=settings.google_master_token,
            device_id=_stable_device_id(email),
        )

    payload: str | None = None
    if email:
        try:
            payload = keyring.get_password(SERVICE, email)
        except KeyringError:
            payload = None

    if payload is None and TOKEN_FILE.exists():
        payload = TOKEN_FILE.read_text(encoding="utf-8")

    if payload is None:
        raise KeepAuthError("Nenhum master token guardado. Rode `mfit2keep keep-login` primeiro.")

    try:
        data = json.loads(payload)
        return KeepCredentials(
            email=data["email"],
            master_token=data["master_token"],
            device_id=data.get("device_id") or new_device_id(),
        )
    except (ValueError, KeyError) as exc:
        raise KeepAuthError(f"Credenciais do Keep corrompidas: {exc}") from exc


def _reject_oauth_cookie(token: str) -> None:
    """Erro nº 1 do fluxo: colar o cookie em vez do master token.

    O cookie ``oauth2_4/…`` ainda precisa passar pelo ``exchange_token``, e o
    erro que o gkeepapi devolve nesse caso é um ``LoginException: Unknown``,
    que não diz nada.
    """
    if token.startswith("oauth2_"):
        raise KeepAuthError(
            "GOOGLE_MASTER_TOKEN contém o cookie oauth_token (oauth2_…), não o master token. "
            "Ele ainda precisa ser trocado: rode `mfit2keep keep-login` e cole o cookie lá. "
            "Lembre que o cookie é de uso único e expira em poucos minutos."
        )


def forget(email: str) -> None:
    with contextlib.suppress(KeyringError):
        keyring.delete_password(SERVICE, email)
    TOKEN_FILE.unlink(missing_ok=True)

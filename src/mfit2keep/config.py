"""Configuração lida do ambiente / arquivo .env."""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from mfit2keep import secrets_store
from mfit2keep.secure_io import write_secret

#: Mesma gramática que o python-dotenv aceita: `NOME=`, com indentação e
#: `export` opcionais. O `\s+` obrigatório preserva `exportD=4` como variável
#: própria, em vez de confundi-la com um `export`.
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
#: Repositório clonado (instalação editável): o .env e o .state ficam ao lado do código.
_IN_REPO = (PACKAGE_ROOT / "pyproject.toml").is_file()
PROJECT_ROOT = PACKAGE_ROOT


class ConfigError(RuntimeError):
    """Falta configuração obrigatória."""


def _user_dir(kind: str) -> Path:
    """Diretório do app no lugar que cada sistema considera correto.

    Windows não tem XDG: config vai em ``%APPDATA%`` (que sincroniza com o
    perfil) e estado em ``%LOCALAPPDATA%`` (que não sincroniza — token de
    máquina não deve viajar). macOS usa ``Application Support``.
    """
    if sys.platform == "win32":
        variable = "APPDATA" if kind == "config" else "LOCALAPPDATA"
        base = os.getenv(variable) or "~/AppData/Roaming"
    elif sys.platform == "darwin":
        base = "~/Library/Application Support"
    else:
        variable = "XDG_CONFIG_HOME" if kind == "config" else "XDG_STATE_HOME"
        default = "~/.config" if kind == "config" else "~/.local/state"
        base = os.getenv(variable) or default
    return Path(base).expanduser() / "mfit2keep"


def state_dir() -> Path:
    """Onde ficam tokens e o mapa de notas.

    Instalado como pacote, ``parents[2]`` aponta para dentro do site-packages —
    gravar segredo ali é errado e pode nem ser permitido. Por isso o padrão é
    ``~/.local/state/mfit2keep``, com o diretório do repositório valendo apenas
    quando o código roda a partir do clone.
    """
    if override := os.getenv("MFIT2KEEP_STATE_DIR"):
        return Path(override).expanduser()

    legacy = PACKAGE_ROOT / ".state"
    if legacy.is_dir():
        # Já existe estado do jeito antigo: continuar usando evita órfãs no Keep.
        return legacy
    if _IN_REPO:
        return legacy
    return _user_dir("state")


def env_file() -> Path:
    if override := os.getenv("MFIT2KEEP_ENV_FILE"):
        return Path(override).expanduser()
    if _IN_REPO:
        return PACKAGE_ROOT / ".env"
    return _user_dir("config") / ".env"


#: Mantido por compatibilidade com quem importa o módulo.
STATE_DIR = state_dir()


@dataclass(frozen=True, slots=True)
class Settings:
    email: str | None
    password: str | None
    token: str | None
    #: Conta Google usada no Keep.
    google_email: str | None = None
    #: Master token ``aas_et/…``. O keyring é o lugar recomendado; isto aqui é
    #: o atalho para quem prefere manter tudo no .env.
    google_master_token: str | None = None
    #: Versões cifradas com systemd-creds (veja :mod:`mfit2keep.secrets_store`).
    password_enc: str | None = None
    google_master_token_enc: str | None = None

    def secret_pair(self, env_var: str) -> tuple[str | None, str | None]:
        """Par (texto puro, cifrado) de um segredo, pelo nome da variável.

        Existe para a CLI percorrer :data:`secrets_store.MANAGED` sem manter
        um mapa paralelo de nomes.
        """
        match env_var:
            case "MFIT_PASSWORD":
                return self.password, self.password_enc
            case "GOOGLE_MASTER_TOKEN":
                return self.google_master_token, self.google_master_token_enc
        raise ConfigError(f"Segredo desconhecido: {env_var}")

    def resolved_password(self) -> str | None:
        return secrets_store.resolve(
            "mfit_password", plaintext=self.password, encrypted=self.password_enc
        )

    def resolved_master_token(self) -> str | None:
        return secrets_store.resolve(
            "google_master_token",
            plaintext=self.google_master_token,
            encrypted=self.google_master_token_enc,
        )

    def require_credentials(self) -> tuple[str, str]:
        password = self.resolved_password()
        if not self.email or not password:
            raise ConfigError(
                f"Defina MFIT_EMAIL e MFIT_PASSWORD em {env_file()} (copie de .env.example)."
            )
        return self.email, password


def replace_env_vars(new_lines: list[str]) -> Path:
    """Reescreve o ``.env`` trocando variáveis, preservando o resto do arquivo.

    Cada linha nova substitui a variável de mesmo nome e também a versão em
    texto puro correspondente (``X_ENC`` remove ``X``) — o objetivo é justamente
    não deixar o segredo antigo para trás.
    """
    path = env_file()
    replaced = {line.split("=", 1)[0] for line in new_lines}
    obsolete = replaced | {name.removesuffix("_ENC") for name in replaced}

    previous = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = _lines_to_keep(previous, obsolete)

    write_secret(path, "\n".join([*kept, *new_lines]) + "\n")
    _assert_plaintext_is_gone(path, obsolete)
    return path


def _lines_to_keep(previous: list[str], obsolete: set[str]) -> list[str]:
    """Filtra as linhas, tratando valor entre aspas que ocupa mais de uma linha.

    Descartar só a primeira linha deixaria a cauda do segredo no arquivo — meio
    master token em texto puro, exatamente o que o comando promete remover.
    """
    kept: list[str] = []
    closing_quote: str | None = None

    for line in previous:
        if closing_quote is not None:
            # Ainda dentro do valor multilinha que está sendo removido.
            if closing_quote in line:
                closing_quote = None
            continue
        if _env_var_of(line) in obsolete:
            closing_quote = _unclosed_quote(line)
            continue
        kept.append(line)
    return kept


def _unclosed_quote(line: str) -> str | None:
    """Aspa que abre o valor e não fecha na mesma linha, se houver."""
    value = line.split("=", 1)[1].lstrip() if "=" in line else ""
    for quote in ('"', "'"):
        if value.startswith(quote) and value.count(quote) < 2:
            return quote
    return None


def _env_var_of(line: str) -> str | None:
    """Nome da variável definida na linha, ou ``None`` se ela não define nada.

    Comentário e linha em branco devolvem ``None`` e por isso sobrevivem. O
    ``export`` precisa ser reconhecido: sem isso um ``export MFIT_PASSWORD=...``
    ficava no arquivo depois de cifrar — o segredo em texto puro justamente
    onde o usuário achou que tinha saído.
    """
    match = _ASSIGNMENT.match(line)
    return match.group(1) if match else None


def _assert_plaintext_is_gone(path: Path, obsolete: set[str]) -> None:
    """Confere a promessa com o mesmo parser que o app usa para ler.

    A filtragem é linha a linha e o formato do dotenv não é: valor entre aspas
    ocupando duas linhas, por exemplo, deixaria metade do segredo para trás. Em
    vez de confiar na reescrita, relemos e falamos a verdade ao usuário.
    """
    remaining = dotenv_values(path)
    leftover = sorted(
        name for name in obsolete if not name.endswith("_ENC") and remaining.get(name)
    )
    if leftover:
        raise ConfigError(
            f"Não consegui remover de {path}: {', '.join(leftover)}. "
            "Apague essas linhas à mão — o segredo ainda está em texto puro."
        )


def load_settings() -> Settings:
    """Lê o .env sem exportar nada para ``os.environ``.

    ``load_dotenv`` colocaria a senha e o master token no ambiente do processo,
    e daí eles seriam herdados por qualquer subprocesso — inclusive os que o
    ``keyring`` dispara. ``dotenv_values`` devolve um dicionário e para por aí.
    """
    from_file = dotenv_values(env_file())

    def get(name: str) -> str | None:
        value = from_file.get(name) or os.getenv(name)
        return value.strip() if value else None

    return Settings(
        email=get("MFIT_EMAIL"),
        password=get("MFIT_PASSWORD"),
        token=get("MFIT_TOKEN"),
        google_email=get("GOOGLE_EMAIL"),
        google_master_token=get("GOOGLE_MASTER_TOKEN"),
        password_enc=get("MFIT_PASSWORD_ENC"),
        google_master_token_enc=get("GOOGLE_MASTER_TOKEN_ENC"),
    )

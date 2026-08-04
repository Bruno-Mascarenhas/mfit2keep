"""Configuração lida do ambiente / arquivo .env."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from mfit2keep import secrets_store
from mfit2keep.secure_io import write_secret

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
#: Repositório clonado (instalação editável): o .env e o .state ficam ao lado do código.
_IN_REPO = (PACKAGE_ROOT / "pyproject.toml").is_file()
PROJECT_ROOT = PACKAGE_ROOT


class ConfigError(RuntimeError):
    """Falta configuração obrigatória."""


def _xdg(variable: str, default: str) -> Path:
    return Path(os.getenv(variable) or default).expanduser() / "mfit2keep"


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
    return _xdg("XDG_STATE_HOME", "~/.local/state")


def env_file() -> Path:
    if override := os.getenv("MFIT2KEEP_ENV_FILE"):
        return Path(override).expanduser()
    if _IN_REPO:
        return PACKAGE_ROOT / ".env"
    return _xdg("XDG_CONFIG_HOME", "~/.config") / ".env"


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
    dropped = {name.removesuffix("_ENC") for name in replaced}

    kept = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.split("=", 1)[0].strip() not in dropped | replaced
    ]
    write_secret(path, "\n".join([*kept, *new_lines]) + "\n")
    return path


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

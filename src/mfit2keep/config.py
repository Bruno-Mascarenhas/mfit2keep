"""Configuração lida do ambiente / arquivo .env."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

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

    def require_credentials(self) -> tuple[str, str]:
        if not self.email or not self.password:
            raise ConfigError(
                f"Defina MFIT_EMAIL e MFIT_PASSWORD em {env_file()} (copie de .env.example)."
            )
        return self.email, self.password


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
    )

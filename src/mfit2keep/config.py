"""Configuração lida do ambiente / arquivo .env."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = PROJECT_ROOT / ".state"


class ConfigError(RuntimeError):
    """Falta configuração obrigatória."""


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
                "Defina MFIT_EMAIL e MFIT_PASSWORD no .env "
                f"(copie de {PROJECT_ROOT / '.env.example'})."
            )
        return self.email, self.password


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        email=os.getenv("MFIT_EMAIL") or None,
        password=os.getenv("MFIT_PASSWORD") or None,
        token=os.getenv("MFIT_TOKEN") or None,
        google_email=os.getenv("GOOGLE_EMAIL") or None,
        google_master_token=os.getenv("GOOGLE_MASTER_TOKEN") or None,
    )

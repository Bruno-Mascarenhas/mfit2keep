"""Guarda de segredos cifrados, com um backend por sistema operacional.

O problema é o mesmo em qualquer OS: com a senha em texto puro no ``.env``,
qualquer cópia do disco entrega a credencial — backup na nuvem, notebook
perdido, SSD devolvido em garantia.

Cada sistema tem a sua ferramenta nativa para isso, e todas cifram amarrando a
chave à **máquina e ao usuário**, de modo que o blob é lixo em qualquer outro
lugar. O resultado é sempre base64, então cabe numa linha do ``.env``::

    MFIT_PASSWORD_ENC=70rBNnmpSA6n22iJf58WXSAAAAABAAAADAAAABAAAA...

===========  ==========================================================
Linux        ``systemd-creds --user`` (TPM2 quando disponível)
Windows      DPAPI (``CryptProtectData``), escopo do usuário
outros       nenhum — o app avisa e mantém o segredo no keyring do sistema
===========  ==========================================================

O que isto **não** faz, em nenhum dos sistemas: proteger contra código
malicioso rodando com o seu usuário. Esse processo chama a mesma API de
decifragem que o app. O ganho real está no dado em repouso.
"""

import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

#: Prefixo dos nomes: o blob é atado ao nome, então decifrar com outro falha.
NAME_PREFIX = "mfit2keep"
TIMEOUT_SECONDS = 30


class SecretsError(RuntimeError):
    """Falha ao cifrar ou decifrar um segredo."""


@dataclass(frozen=True, slots=True)
class ManagedSecret:
    """Um segredo que o app sabe cifrar, e como ele aparece no ``.env``.

    Junta o que antes eram listas paralelas na CLI: variável em texto puro,
    variável cifrada, chave da cifragem e rótulo para o usuário.
    """

    env_var: str
    label: str

    @property
    def encrypted_var(self) -> str:
        return f"{self.env_var}_ENC"

    @property
    def key(self) -> str:
        return self.env_var.lower()


#: Ordem estável — é a ordem em que a CLI mostra e cifra.
MANAGED = (
    ManagedSecret("MFIT_PASSWORD", "senha do MFIT"),
    ManagedSecret("GOOGLE_MASTER_TOKEN", "master token do Google"),
)


class Backend(StrEnum):
    PLAINTEXT = "texto puro"
    KEYRING = "keyring do sistema"
    ENCRYPTED = "cifrado na máquina"
    ABSENT = "ausente"


def credential_name(secret_key: str) -> str:
    return f"{NAME_PREFIX}.{secret_key.lower()}"


# --------------------------------------------------------------- backends


class CipherBackend(ABC):
    """Cifragem local amarrada a esta máquina e a este usuário."""

    #: Nome curto mostrado ao usuário ("systemd-creds (TPM2)").
    name: str = "nenhum"

    @abstractmethod
    def available(self) -> bool:
        """Dá para usar aqui, agora?"""

    @abstractmethod
    def encrypt(self, secret_key: str, value: str) -> str: ...

    @abstractmethod
    def decrypt(self, secret_key: str, blob: str) -> str: ...


class SystemdCredsBackend(CipherBackend):
    """Linux: ``systemd-creds`` no escopo do usuário, com TPM2 quando houver."""

    name = "systemd-creds (TPM2)"

    def available(self) -> bool:
        if shutil.which("systemd-creds") is None:
            return False
        try:
            self.encrypt("_probe", "x")
        except SecretsError:
            return False
        return True

    def encrypt(self, secret_key: str, value: str) -> str:
        """O segredo entra por stdin: em argv apareceria no ``ps``."""
        return self._run("encrypt", secret_key, value, action="cifrar").replace("\n", "")

    def decrypt(self, secret_key: str, blob: str) -> str:
        return self._run("decrypt", secret_key, blob, action="decifrar")

    def _run(self, verb: str, secret_key: str, stdin: str, *, action: str) -> str:
        command = [
            "systemd-creds",
            verb,
            "--user",
            f"--name={credential_name(secret_key)}",
            "-",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SecretsError(f"Não foi possível {action} com systemd-creds: {error}") from error

        if completed.returncode != 0:
            # stderr do systemd-creds não contém o segredo, só o motivo da recusa.
            raise SecretsError(
                f"systemd-creds falhou ao {action} ({completed.returncode}): "
                f"{completed.stderr.strip()[:200]}"
            )
        return completed.stdout


class DpapiBackend(CipherBackend):
    """Windows: DPAPI no escopo do usuário (``CryptProtectData``).

    Mesmo modelo de ameaça do ``systemd-creds``: a chave é derivada da conta do
    usuário nesta máquina, então o blob não decifra em outro lugar. O nome do
    segredo entra como *entropia adicional*, o que faz um blob não servir para
    outro — igual ao ``--name`` do systemd-creds.
    """

    name = "DPAPI (Windows)"

    def available(self) -> bool:
        return sys.platform == "win32"

    def encrypt(self, secret_key: str, value: str) -> str:
        from mfit2keep import _dpapi

        # O erro do ctypes vira SecretsError: quem chama trata um tipo só,
        # igual ao backend do Linux.
        try:
            return _dpapi.protect(value, entropy=credential_name(secret_key))
        except _dpapi.DpapiError as error:
            raise SecretsError(f"Não foi possível cifrar com o DPAPI: {error}") from error

    def decrypt(self, secret_key: str, blob: str) -> str:
        from mfit2keep import _dpapi

        try:
            return _dpapi.unprotect(blob, entropy=credential_name(secret_key))
        except _dpapi.DpapiError as error:
            raise SecretsError(f"Não foi possível decifrar com o DPAPI: {error}") from error


class UnavailableBackend(CipherBackend):
    """Sistema sem equivalente nativo — macOS, BSD, container mínimo."""

    name = "indisponível"

    def available(self) -> bool:
        return False

    def encrypt(self, secret_key: str, value: str) -> str:
        raise SecretsError(_unsupported_message())

    def decrypt(self, secret_key: str, blob: str) -> str:
        raise SecretsError(_unsupported_message())


def _unsupported_message() -> str:
    return (
        f"Não há cifragem local para {sys.platform}. "
        "Use o keyring do sistema (`mfit2keep keep-login`) e mantenha o .env sem segredo."
    )


#: Cifragem nativa de cada sistema. Fora da tabela, o app usa só o keyring.
_BACKENDS: dict[str, type[CipherBackend]] = {
    "win32": DpapiBackend,
    "linux": SystemdCredsBackend,
}


def _pick_backend() -> CipherBackend:
    return _BACKENDS.get(sys.platform, UnavailableBackend)()


#: Backend deste sistema. Trocável nos testes.
backend: CipherBackend = _pick_backend()


# ------------------------------------------------------------------- api


def cipher_available() -> bool:
    """Existe cifragem local utilizável nesta máquina?"""
    return backend.available()


def cipher_name() -> str:
    return backend.name


def encrypt(secret_key: str, value: str) -> str:
    return backend.encrypt(secret_key, value)


def decrypt(secret_key: str, blob: str) -> str:
    return backend.decrypt(secret_key, blob)


def resolve(secret_key: str, *, plaintext: str | None, encrypted: str | None) -> str | None:
    """Valor final do segredo, preferindo a forma cifrada.

    O cifrado ganha para que deixar a variável antiga preenchida por engano não
    faça o app silenciosamente voltar a usar texto puro.
    """
    if encrypted:
        return decrypt(secret_key, encrypted)
    return plaintext


def backend_of(*, plaintext: str | None, encrypted: str | None) -> Backend:
    if encrypted:
        return Backend.ENCRYPTED
    if plaintext:
        return Backend.PLAINTEXT
    return Backend.ABSENT

"""Guarda de segredos: texto puro, keyring do sistema ou ``systemd-creds``.

O problema concreto: com a senha do MFIT em texto puro no ``.env``, qualquer
cópia do disco entrega a credencial — backup no Drive, disco roubado, ou o SSD
saindo para RMA. Nada disso exige um atacante sofisticado.

``systemd-creds`` resolve exatamente essa classe: ele cifra amarrando a chave ao
**TPM2 desta placa**, então o blob é lixo em qualquer outra máquina. E o
resultado é base64, o que dá a experiência que se espera de um ``.env``::

    MFIT_PASSWORD_ENC=70rBNnmpSA6n22iJf58WXSAAAAABAAAADAAAABAAAA...

O que isto **não** faz: proteger contra código malicioso rodando com o seu
usuário. Esse processo simplesmente chama ``systemd-creds decrypt``, igual ao
app. Nenhuma das alternativas (keyring, sops, age, gpg-agent destravado) muda
isso — quem tem o seu UID tem os seus segredos. O ganho real está no dado
em repouso, e é ele que estava faltando.
"""

import shutil
import subprocess
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
    variável cifrada, chave do systemd-creds e rótulo para o usuário.
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
    SYSTEMD_CREDS = "systemd-creds (TPM2)"
    ABSENT = "ausente"


def credential_name(secret_key: str) -> str:
    return f"{NAME_PREFIX}.{secret_key.lower()}"


def systemd_creds_available() -> bool:
    """``systemd-creds`` existe e consegue cifrar no escopo do usuário?"""
    if shutil.which("systemd-creds") is None:
        return False
    try:
        encrypt("_probe", "x")
    except SecretsError:
        return False
    return True


def encrypt(secret_key: str, value: str) -> str:
    """Devolve o blob base64 de ``value``, atado ao TPM2 e ao nome.

    O segredo entra por stdin: em argv ele apareceria no ``ps`` de qualquer
    usuário da máquina.
    """
    return _run(
        ["systemd-creds", "encrypt", "--user", f"--name={credential_name(secret_key)}", "-", "-"],
        value,
        acao="cifrar",
    ).replace("\n", "")


def decrypt(secret_key: str, blob: str) -> str:
    """Recupera o segredo a partir do blob. O blob em si não é sigiloso."""
    return _run(
        ["systemd-creds", "decrypt", "--user", f"--name={credential_name(secret_key)}", "-", "-"],
        blob,
        acao="decifrar",
    )


def _run(command: list[str], stdin: str, *, acao: str) -> str:
    try:
        completed = subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecretsError(f"Não foi possível {acao} com systemd-creds: {exc}") from exc

    if completed.returncode != 0:
        # stderr do systemd-creds não contém o segredo, só o motivo da recusa.
        raise SecretsError(
            f"systemd-creds falhou ao {acao} ({completed.returncode}): "
            f"{completed.stderr.strip()[:200]}"
        )
    return completed.stdout


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
        return Backend.SYSTEMD_CREDS
    if plaintext:
        return Backend.PLAINTEXT
    return Backend.ABSENT

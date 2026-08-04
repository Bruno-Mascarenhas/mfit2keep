"""Escrita de arquivos que contêm segredo.

O padrão ingênuo — ``path.write_text(...)`` seguido de ``path.chmod(0o600)`` —
cria o arquivo com a permissão do umask (0664 nesta máquina) e só depois
restringe. Entre as duas chamadas existe uma janela em que qualquer usuário
local lê o master token do Google ou o JWT do MFIT.

Aqui o arquivo já nasce 0600, via ``os.open`` com o modo no próprio ``open``, e
a troca é atômica (escreve em temporário no mesmo diretório e faz ``rename``),
para que uma falha no meio não deixe um arquivo truncado.
"""

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

#: Só o dono lê e escreve.
SECRET_MODE = 0o600
#: Só o dono entra no diretório.
SECRET_DIR_MODE = 0o700


def ensure_private_dir(path: Path) -> None:
    """Cria o diretório privado; se já existia e está frouxo, aperta.

    Só deve ser chamado para diretório que é NOSSO (o ``.state/``). Apertar um
    diretório de terceiro — a raiz do repositório, por exemplo, que é o pai do
    ``.env`` — é efeito colateral, não segurança.
    """
    path.mkdir(parents=True, exist_ok=True, mode=SECRET_DIR_MODE)
    if path.stat().st_mode & 0o077:
        path.chmod(SECRET_DIR_MODE)


def write_secret(path: Path, content: str) -> None:
    """Grava ``content`` em ``path`` sem nunca expor o conteúdo a terceiros.

    Cria o diretório pai se faltar, mas **não mexe na permissão de um diretório
    que já existe**: o arquivo nasce 0600, e isso é o que protege o segredo.
    """
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=SECRET_DIR_MODE)

    # O pid no nome evita colisão entre duas execuções simultâneas.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    # O modo vai no próprio open: o kernel cria já 0600 (umask só tira bits).
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SECRET_MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_secret_json(path: Path, data: dict[str, Any]) -> None:
    """Estado nosso (``.state/``): aqui o diretório privado é responsabilidade nossa."""
    ensure_private_dir(path.parent)
    write_secret(path, json.dumps(data))


def read_secret_json(path: Path) -> dict[str, Any] | None:
    """Lê o JSON, devolvendo ``None`` se não existir ou estiver corrompido."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


def is_world_readable(path: Path) -> bool:
    """Alguém além do dono consegue ler este arquivo?"""
    try:
        return bool(path.stat().st_mode & 0o077)
    except OSError:
        return False


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Trava entre processos, para read-modify-write de arquivo de estado.

    Sem isso, dois ``sync`` simultâneos leem o mesmo mapa de notas, cada um
    grava a sua versão e os vínculos de um deles somem — na sincronização
    seguinte o app cria notas duplicadas no Keep.
    """
    ensure_private_dir(path.parent)
    lock = path.with_suffix(f"{path.suffix}.lock")
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT, SECRET_MODE)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

"""Escrita de arquivos que contêm segredo, em qualquer sistema.

O padrão ingênuo — ``path.write_text(...)`` seguido de ``path.chmod(0o600)`` —
cria o arquivo com a permissão do umask e só depois restringe. Entre as duas
chamadas existe uma janela em que qualquer usuário local lê o master token.
Aqui o arquivo já nasce restrito, via ``os.open`` com o modo no próprio open, e
a troca é atômica (escreve em temporário no mesmo diretório e faz ``replace``).

Diferença entre sistemas, dita na cara: no POSIX o modo ``0600`` é a proteção.
No Windows ele é praticamente decorativo — quem protege ali é a ACL herdada do
perfil do usuário, e é por isso que o Windows ganha o DPAPI em
:mod:`mfit2keep.secrets_store`. A trava entre processos também muda de API
(``fcntl`` no POSIX, ``msvcrt`` no Windows), mas a semântica é a mesma.
"""

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

#: Só o dono lê e escreve. Sem efeito prático no Windows.
SECRET_MODE = 0o600
#: Só o dono entra no diretório.
SECRET_DIR_MODE = 0o700

POSIX = os.name == "posix"


def ensure_private_dir(path: Path) -> None:
    """Cria o diretório privado; se já existia e está frouxo, aperta.

    Só deve ser chamado para diretório que é NOSSO (o ``.state/``). Apertar um
    diretório de terceiro — a raiz do repositório, por exemplo, que é o pai do
    ``.env`` — é efeito colateral, não segurança.
    """
    path.mkdir(parents=True, exist_ok=True, mode=SECRET_DIR_MODE)
    if POSIX and path.stat().st_mode & 0o077:
        path.chmod(SECRET_DIR_MODE)


def write_secret(path: Path, content: str) -> None:
    """Grava ``content`` em ``path`` sem nunca expor o conteúdo a terceiros.

    Cria o diretório pai se faltar, mas **não mexe na permissão de um diretório
    que já existe**: o arquivo nasce restrito, e isso é o que protege o segredo.
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
        # os.replace é atômico nos dois sistemas, inclusive sobre arquivo existente.
        os.replace(tmp, path)
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
    """Alguém além do dono consegue ler este arquivo?

    Só responde no POSIX. No Windows a resposta viria da ACL, que este projeto
    não inspeciona — e responder ``False`` ali seria dar uma garantia que não
    foi verificada.
    """
    if not POSIX:
        return False
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
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, SECRET_MODE)
    try:
        _lock(descriptor)
        yield
    finally:
        try:
            _unlock(descriptor)
        finally:
            os.close(descriptor)


# O teste é sobre sys.platform, e não sobre a constante POSIX, porque é assim
# que o mypy estreita o tipo e consegue checar cada sistema separadamente.
if sys.platform == "win32":  # pragma: no cover - exercitado no runner Windows do CI
    import msvcrt

    #: O msvcrt trava por faixa de bytes; um byte basta para servir de mutex.
    _LOCK_BYTES = 1

    def _lock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        # LK_LOCK tenta 10 vezes, com 1s de intervalo, e só então falha.
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, _LOCK_BYTES)

    def _unlock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, _LOCK_BYTES)

else:
    import fcntl

    def _lock(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_EX)

    def _unlock(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def platform_summary() -> str:
    """Uma linha sobre como os segredos ficam protegidos neste sistema."""
    if POSIX:
        return "arquivos 0600 e trava via fcntl"
    return f"ACL do perfil do usuário e trava via msvcrt ({sys.platform})"

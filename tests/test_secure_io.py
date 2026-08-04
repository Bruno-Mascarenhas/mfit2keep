import asyncio
import os
import sys
from pathlib import Path

import pytest

from mfit2keep import secure_io
from mfit2keep.secure_io import (
    ensure_private_dir,
    exclusive_lock,
    is_world_readable,
    read_secret_json,
    write_secret,
    write_secret_json,
)


@pytest.fixture(autouse=True)
def permissive_umask() -> object:
    """umask 0 é o pior caso: sem ele o teste passaria por sorte."""
    previous = os.umask(0)
    yield
    os.umask(previous)


def test_secret_file_is_never_world_readable(tmp_path: Path) -> None:
    path = tmp_path / "token.json"

    write_secret(path, "aas_et/SECRETO")

    # O arquivo tem que nascer 0600 — write_text + chmod deixaria uma janela 0666.
    assert path.stat().st_mode & 0o777 == 0o600
    assert not is_world_readable(path)


def test_parent_directory_is_private(tmp_path: Path) -> None:
    path = tmp_path / "estado" / "token.json"

    write_secret(path, "segredo")

    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_existing_loose_directory_is_tightened(tmp_path: Path) -> None:
    loose = tmp_path / "estado"
    loose.mkdir(mode=0o755)

    ensure_private_dir(loose)

    assert loose.stat().st_mode & 0o077 == 0


def test_content_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "token.json"

    write_secret_json(path, {"token": "aas_et/abc", "device_id": "dead"})

    assert read_secret_json(path) == {"token": "aas_et/abc", "device_id": "dead"}


def test_overwrite_keeps_permissions(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    write_secret(path, "primeiro")

    write_secret(path, "segundo")

    assert path.read_text(encoding="utf-8") == "segundo"
    assert path.stat().st_mode & 0o777 == 0o600


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    write_secret(tmp_path / "token.json", "segredo")

    assert [p.name for p in tmp_path.iterdir()] == ["token.json"]


def test_missing_file_reads_as_none(tmp_path: Path) -> None:
    assert read_secret_json(tmp_path / "nao-existe.json") is None


def test_corrupted_file_reads_as_none(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("{isso nao e json", encoding="utf-8")

    assert read_secret_json(path) is None


def test_non_object_json_reads_as_none(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_secret_json(path) is None


def test_write_is_atomic_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    write_secret(path, "conteudo bom")

    class Explosivo:
        def __str__(self) -> str:
            raise RuntimeError("falha no meio da escrita")

    with pytest.raises(TypeError):
        write_secret(path, Explosivo())  # type: ignore[arg-type]

    # O arquivo anterior continua íntegro e nenhum .tmp sobra.
    assert path.read_text(encoding="utf-8") == "conteudo bom"
    assert [p.name for p in tmp_path.iterdir()] == ["token.json"]


async def test_lock_serializes_two_processes(tmp_path: Path) -> None:
    """A trava é entre processos — subprocesso de verdade, não thread."""
    alvo = tmp_path / "estado.json"
    script = tmp_path / "escreve.py"
    script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "from mfit2keep.secure_io import exclusive_lock\n"
        "alvo = Path(sys.argv[1])\n"
        "with exclusive_lock(alvo):\n"
        "    atual = alvo.read_text() if alvo.exists() else ''\n"
        "    time.sleep(0.2)\n"
        "    alvo.write_text(atual + sys.argv[2])\n",
        encoding="utf-8",
    )

    processos = [
        await asyncio.create_subprocess_exec(sys.executable, str(script), str(alvo), letra)
        for letra in ("a", "b")
    ]
    for processo in processos:
        assert await processo.wait() == 0

    # Sem a trava, o segundo leria antes do primeiro gravar e sobrescreveria.
    assert sorted(alvo.read_text(encoding="utf-8")) == ["a", "b"]


def test_lock_is_reentrant_across_calls(tmp_path: Path) -> None:
    alvo = tmp_path / "estado.json"

    with exclusive_lock(alvo):
        pass
    with exclusive_lock(alvo):
        pass  # travar de novo depois de soltar tem que funcionar


@pytest.mark.skipif(not secure_io.POSIX, reason="modo POSIX não existe no Windows")
def test_posix_reports_world_readable(tmp_path: Path) -> None:
    frouxo = tmp_path / "frouxo.json"
    frouxo.write_text("{}", encoding="utf-8")
    frouxo.chmod(0o644)

    assert is_world_readable(frouxo)


@pytest.mark.skipif(secure_io.POSIX, reason="só o Windows não inspeciona ACL")
def test_windows_does_not_claim_to_know_the_acl(tmp_path: Path) -> None:
    alvo = tmp_path / "token.json"
    write_secret(alvo, "segredo")

    # Responder False sem olhar a ACL seria dar garantia não verificada;
    # o contrato é justamente não afirmar nada ali.
    assert is_world_readable(alvo) is False

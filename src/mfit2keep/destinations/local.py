"""Destino local: grava cada nota como Markdown com checkboxes.

Serve para conferir o resultado sem depender de nenhuma conta, e é o fallback
quando o destino remoto está fora do ar.
"""

import asyncio
import hashlib
import re
from pathlib import Path

from mfit2keep.destinations.base import MARKER, Action, NoteDestination, NoteResult
from mfit2keep.matching import CheckedState
from mfit2keep.models import ChecklistNote

_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACES = re.compile(r"[\s_-]+")
#: Rodapé que identifica um arquivo criado por este app.
_STAMP = f"<!-- {MARKER}:{{}} -->"
_STAMP_PATTERN = re.compile(rf"<!--\s*{re.escape(MARKER)}:")
#: "- [x] 1. Supino" — checkbox no Markdown, com ou sem indentação.
_CHECKBOX = re.compile(r"^\s*-\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+)$", re.MULTILINE)


class LocalDestinationError(RuntimeError):
    """O destino local não pode continuar sem arriscar arquivo do usuário."""


def slugify(text: str) -> str:
    cleaned = _SLUG_STRIP.sub("", text).strip().lower()
    return _SLUG_SPACES.sub("-", cleaned) or "nota"


def _id_suffix(external_id: str) -> str:
    """Parte estável do nome do arquivo, vinda do id do treino no MFIT."""
    tail = external_id.rsplit(":", 1)[-1]
    if tail.isalnum():
        return tail
    return hashlib.sha256(external_id.encode()).hexdigest()[:10]


class LocalMarkdownDestination(NoteDestination):
    def __init__(self, out_dir: Path) -> None:
        self._out_dir = out_dir
        self._out_dir.mkdir(parents=True, exist_ok=True)

    async def upsert(self, note: ChecklistNote) -> NoteResult:
        return await asyncio.to_thread(self._write, note)

    def _write(self, note: ChecklistNote) -> NoteResult:
        path = self._path_for(note)
        previous = path.read_text(encoding="utf-8") if path.exists() else None

        if previous is not None and not _STAMP_PATTERN.search(previous):
            # Arquivo homônimo que o app não criou: melhor falhar do que
            # destruir uma anotação do usuário.
            raise LocalDestinationError(
                f"{path} já existe e não foi criado pelo mfit2keep. "
                "Escolha outra pasta com --saida ou mova o arquivo."
            )

        self._drop_renamed_copies(note, keeping=path)
        # As marcações do arquivo anterior são preservadas: o usuário risca os
        # exercícios feitos direto no .md.
        content = self._to_markdown(note, previous=previous)

        if previous == content:
            return NoteResult(note.title, Action.UNCHANGED, str(path))

        path.write_text(content, encoding="utf-8")
        return NoteResult(note.title, Action.UPDATED if previous else Action.CREATED, str(path))

    def _path_for(self, note: ChecklistNote) -> Path:
        """Nome do arquivo com sufixo estável do treino.

        Só o slug do título não serve: "Perna A" e "Perna-A" geram o mesmo
        slug, e um treino sobrescreveria o arquivo do outro sem aviso.
        """
        slug = slugify(note.title)
        if not note.external_id:
            return self._out_dir / f"{slug}.md"
        return self._out_dir / f"{slug}-{_id_suffix(note.external_id)}.md"

    def _drop_renamed_copies(self, note: ChecklistNote, *, keeping: Path) -> None:
        """Remove o arquivo antigo quando o treino foi renomeado no MFIT."""
        if not note.external_id:
            return
        stamp = _STAMP.format(note.external_id)
        for path in self._out_dir.glob("*.md"):
            if path == keeping:
                continue
            if stamp in path.read_text(encoding="utf-8"):
                path.unlink()

    async def purge(self, *, archive: bool = False) -> list[NoteResult]:
        return await asyncio.to_thread(self._purge, archive)

    def _purge(self, archive: bool) -> list[NoteResult]:
        archive_dir = self._out_dir / "arquivadas"
        results: list[NoteResult] = []

        for path in sorted(self._out_dir.glob("*.md")):
            # Sem o carimbo, o arquivo não é nosso — não se toca.
            if not _STAMP_PATTERN.search(path.read_text(encoding="utf-8")):
                continue
            if archive:
                archive_dir.mkdir(parents=True, exist_ok=True)
                target = _free_path(archive_dir / path.name)
                path.replace(target)
                results.append(NoteResult(path.stem, Action.ARCHIVED, str(target)))
            else:
                path.unlink()
                results.append(NoteResult(path.stem, Action.TRASHED, str(path)))
        return results

    @staticmethod
    def _to_markdown(note: ChecklistNote, *, previous: str | None = None) -> str:
        before = CheckedState(_parse_checkboxes(previous or ""))

        lines = [f"# {note.title}", ""]
        for item in note.items:
            checked = item.checked or before.take(item.text)
            lines.append(f"- [{'x' if checked else ' '}] {item.text}")
        lines += ["", _STAMP.format(note.external_id or "")]
        return "\n".join(lines) + "\n"


def _parse_checkboxes(markdown: str) -> list[tuple[str, bool]]:
    """Lê os `- [ ] texto` / `- [x] texto` de um arquivo já existente."""
    return [
        (match.group("text").strip(), match.group("mark").lower() == "x")
        for match in _CHECKBOX.finditer(markdown)
    ]


def _free_path(path: Path) -> Path:
    """Primeiro nome livre: arquivar duas vezes não pode sobrescrever a 1ª."""
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise LocalDestinationError(f"Não há nome livre para arquivar {path}.")

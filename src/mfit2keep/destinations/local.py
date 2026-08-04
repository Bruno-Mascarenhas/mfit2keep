"""Destino local: grava cada nota como Markdown com checkboxes.

Serve para conferir o resultado sem depender de nenhuma conta, e é o fallback
quando o destino remoto está fora do ar.
"""

import asyncio
import re
from pathlib import Path

from ..models import ChecklistNote
from .base import MARKER, Action, NoteDestination, NoteResult

_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACES = re.compile(r"[\s_-]+")
#: Rodapé que identifica um arquivo criado por este app.
_STAMP = f"<!-- {MARKER}:{{}} -->"
_STAMP_PATTERN = re.compile(rf"<!--\s*{re.escape(MARKER)}:")


def slugify(text: str) -> str:
    cleaned = _SLUG_STRIP.sub("", text).strip().lower()
    return _SLUG_SPACES.sub("-", cleaned) or "nota"


class LocalMarkdownDestination(NoteDestination):
    name = "local"

    def __init__(self, out_dir: Path) -> None:
        self._out_dir = out_dir
        self._out_dir.mkdir(parents=True, exist_ok=True)

    async def upsert(self, note: ChecklistNote) -> NoteResult:
        return await asyncio.to_thread(self._write, note)

    def _write(self, note: ChecklistNote) -> NoteResult:
        path = self._out_dir / f"{slugify(note.title)}.md"
        content = self._to_markdown(note)

        previous = path.read_text(encoding="utf-8") if path.exists() else None
        if previous == content:
            return NoteResult(note.title, Action.UNCHANGED, str(path))

        path.write_text(content, encoding="utf-8")
        return NoteResult(note.title, Action.UPDATED if previous else Action.CREATED, str(path))

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
                target = archive_dir / path.name
                path.replace(target)
                results.append(NoteResult(path.stem, Action.ARCHIVED, str(target)))
            else:
                path.unlink()
                results.append(NoteResult(path.stem, Action.TRASHED, str(path)))
        return results

    @staticmethod
    def _to_markdown(note: ChecklistNote) -> str:
        lines = [f"# {note.title}", ""]
        for item in note.items:
            lines.append(f"- [{'x' if item.checked else ' '}] {item.text}")
            lines.extend(
                f"  - [{'x' if child.checked else ' '}] {child.text}" for child in item.children
            )
        lines += ["", _STAMP.format(note.external_id or "")]
        return "\n".join(lines) + "\n"

"""Contrato dos destinos de nota.

Toda a lógica de MFIT → :class:`ChecklistNote` é independente do destino; trocar
Google Keep por Google Tasks (ou qualquer outro) é implementar esta interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Self

from mfit2keep.models import ChecklistNote

#: Marca que identifica o que este app criou. Só o que tem a marca pode ser
#: apagado ou arquivado — as notas que já existiam na conta ficam intocadas.
MARKER = "mfit2keep"


class Action(StrEnum):
    CREATED = "criada"
    UPDATED = "atualizada"
    UNCHANGED = "sem mudança"
    ARCHIVED = "arquivada"
    TRASHED = "apagada"


@dataclass(frozen=True, slots=True)
class NoteResult:
    """O que aconteceu com uma nota no destino."""

    note_title: str
    action: Action
    reference: str | None = None  # id, URL ou caminho no destino


class NoteDestination(ABC):
    """Destino capaz de guardar notas com checkboxes."""

    @abstractmethod
    async def upsert(self, note: ChecklistNote) -> NoteResult:
        """Cria a nota ou atualiza a existente com o mesmo ``external_id``."""

    async def upsert_all(self, notes: list[ChecklistNote]) -> list[NoteResult]:
        """Sequencial de propósito: as APIs de nota costumam limitar concorrência."""
        return [await self.upsert(note) for note in notes]

    @abstractmethod
    async def purge(self, *, archive: bool = False) -> list[NoteResult]:
        """Apaga (ou arquiva) apenas as notas marcadas com :data:`MARKER`.

        Nunca pode tocar em nada que o app não tenha criado.
        """

    async def aclose(self) -> None:
        """Libera recursos (conexões, sessões) — chamado ao fim da execução.

        No-op de propósito: destino sem conexão (o local, por exemplo) não
        precisa sobrescrever. Não é ``@abstractmethod`` por isso.
        """
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

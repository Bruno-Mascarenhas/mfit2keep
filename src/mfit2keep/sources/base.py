"""Contrato das fontes de treino.

Simétrico ao :mod:`mfit2keep.destinations.base`. Do lado de cá entra qualquer
serviço, arquivo ou planilha que saiba descrever um treino; do lado de lá sai
qualquer formato de nota. O meio — :class:`~mfit2keep.models.Workout` — não
conhece nenhum dos dois.

É esta interface que permite trocar o MFIT por outro app sem tocar em render,
matching ou destino.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from mfit2keep.models import Workout


class SourceError(RuntimeError):
    """A fonte não conseguiu entregar os treinos."""


@dataclass(frozen=True, slots=True)
class RoutineSummary:
    """Uma rotina disponível na fonte, para o usuário escolher qual sincronizar."""

    id: str
    name: str
    starts_at: str | None = None
    ends_at: str | None = None


class WorkoutSource(ABC):
    """De onde os treinos vêm."""

    @abstractmethod
    async def list_routines(self) -> list[RoutineSummary]:
        """Rotinas que o usuário pode sincronizar."""

    @abstractmethod
    async def fetch_workouts(self, routine_id: str | None) -> list[Workout]:
        """Os treinos de uma rotina, já no modelo de domínio.

        O id é opaco e específico da fonte: no MFIT é o número da URL, num
        arquivo não existe. Fonte que precisa dele recusa ``None``.
        """

    async def aclose(self) -> None:
        """Libera recursos (conexão, sessão). No-op para fonte sem estado."""
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

"""Fonte MFIT Personal: adapta a API do MFIT ao contrato de :mod:`sources.base`.

É a única parte do projeto que sabe que o MFIT existe. O cliente HTTP fica em
:mod:`mfit2keep.sources.mfit_api` e a tradução do JSON em
:mod:`mfit2keep.sources.mfit_parser`; aqui só se junta os dois.
"""

from typing import Any

from mfit2keep.config import Settings
from mfit2keep.models import Workout
from mfit2keep.sources.base import RoutineSummary, SourceError, WorkoutSource
from mfit2keep.sources.mfit_api import MfitClient
from mfit2keep.sources.mfit_parser import parse_routine, parse_session


class MfitSource(WorkoutSource):
    """Treinos vindos da conta do aluno no MFIT Personal."""

    def __init__(self, settings: Settings, *, client: MfitClient | None = None) -> None:
        self._client = client or MfitClient(settings)

    async def list_routines(self) -> list[RoutineSummary]:
        routines = await self._client.list_workouts()
        if not isinstance(routines, list):
            routines = [routines]
        return [
            RoutineSummary(
                id=str(routine.get("id", "")),
                name=str(routine.get("nome", "")),
                starts_at=_optional(routine.get("dataInicio")),
                ends_at=_optional(routine.get("dataFim")),
            )
            for routine in routines
        ]

    async def fetch_workouts(self, routine_id: str | None) -> list[Workout]:
        """Busca a rotina e a sessão de cada dia — os dias vão todos em paralelo."""
        if not routine_id:
            raise SourceError("Informe o ID da rotina (o número na URL do MFIT).")
        routine: dict[str, Any] = await self._client.workout_details(routine_id)

        days: list[dict[str, Any]] = routine.get("workouts") or []
        if not days:
            # Treino avulso não tem dias: a própria resposta já é a sessão.
            return [parse_session(routine)]

        day_ids = [day["id"] for day in days if day.get("id") is not None]
        return parse_routine(routine, await self._client.workout_sessions(day_ids))

    async def aclose(self) -> None:
        await self._client.aclose()


def _optional(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None

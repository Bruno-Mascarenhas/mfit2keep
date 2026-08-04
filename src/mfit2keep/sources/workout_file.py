"""Fonte de arquivo: treinos vindos de um JSON no formato neutro.

É a prova de que a costura de fonte é real — e o caminho de saída do MFIT.
Exporte com ``--destino arquivo``, e daí em diante ``--fonte arquivo`` alimenta
o app sem nenhuma conta, sem rede e sem depender de nenhum serviço.
"""

import json
from pathlib import Path

from mfit2keep.interchange import InterchangeError, workouts_from_dict
from mfit2keep.models import Workout
from mfit2keep.sources.base import RoutineSummary, SourceError, WorkoutSource

#: Um arquivo é uma rotina só; o id existe para caber no mesmo contrato.
FILE_ROUTINE_ID = "arquivo"


class WorkoutFileSource(WorkoutSource):
    """Lê os treinos de um arquivo exportado antes."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def list_routines(self) -> list[RoutineSummary]:
        workouts = self._read()
        return [
            RoutineSummary(
                id=FILE_ROUTINE_ID,
                name=f"{self._path.name} ({len(workouts)} treinos)",
            )
        ]

    async def fetch_workouts(self, routine_id: str | None) -> list[Workout]:
        # O id é ignorado de propósito: o arquivo já é a rotina inteira.
        return self._read()

    def _read(self) -> list[Workout]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise SourceError(f"Não consegui ler {self._path}: {error}") from error
        except ValueError as error:
            raise SourceError(f"{self._path} não é JSON válido: {error}") from error

        if not isinstance(payload, dict):
            raise SourceError(f"{self._path} não contém um export de treinos.")
        try:
            return workouts_from_dict(payload)
        except InterchangeError as error:
            raise SourceError(f"{self._path}: {error}") from error

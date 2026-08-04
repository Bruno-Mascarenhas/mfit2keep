"""Fontes de treino disponíveis.

Acrescentar uma fonte nova é: implementar :class:`WorkoutSource`, e registrar
aqui. Nada em render, matching ou destinos precisa saber que ela existe.
"""

from mfit2keep.sources.base import RoutineSummary, SourceError, WorkoutSource

#: Nome usado na CLI (``--fonte mfit``) → descrição para o ``--help``.
AVAILABLE = {
    "mfit": "Conta do aluno no MFIT Personal (rede)",
    "arquivo": "Arquivo JSON exportado antes, no formato neutro",
}

__all__ = ["AVAILABLE", "RoutineSummary", "SourceError", "WorkoutSource"]

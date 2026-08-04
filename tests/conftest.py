"""Fixtures com o formato real da API do MFIT (payloads reduzidos à mão)."""

from typing import Any

import pytest

from mfit2keep.config import Settings


def serie(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "tipo": 0,
        "repeticao": "3x12 a 15",
        "carga": "0",
        "tempo": "",
        "velocidade": "",
        "distancia": "",
        "pace": "",
        "intervalo": 45.0,
        "intervalText": "45",
        "intervalSeconds": 45,
        "status": 0,
        "obs": "",
        "ordenacao": 1,
    }
    return base | overrides


def exercise(name: str, *series: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "name": name,
        "ordenacao": 0,
        "isCombinado": False,
        "series": list(series) or [serie()],
    }
    return base | overrides


def group(*exercises: dict[str, Any], order: int = 0) -> dict[str, Any]:
    return {"id": 1, "order": order, "type": 0, "exercises": list(exercises)}


@pytest.fixture
def session_bicep() -> dict[str, Any]:
    """Um dia de treino como vem de ``/v2/client/workout/session?id=``."""
    return {
        "id": 156902750,
        "nome": "Bíceps/Triceps",
        "obs": "",
        "exercs": [
            group(exercise("Triceps Coice na Polia"), order=0),
            group(exercise("Rosca Scott com Halteres"), order=1),
            group(
                exercise("Esteira Caminhada", serie(repeticao="40", intervalText="0", intervalo=0)),
                order=2,
            ),
        ],
    }


@pytest.fixture
def routine() -> dict[str, Any]:
    """A rotina como vem de ``/v2/client/workout/?id=``."""
    return {
        "id": 36318803,
        "nome": "A/B/C/D/E",
        "descricao": "",
        "workouts": [
            {"id": 156902750, "nome": "Bíceps/Triceps", "diaTipo": 1, "obs": "", "ordenacao": 0},
            {"id": 156902751, "nome": "Costa", "diaTipo": 2, "obs": "", "ordenacao": 0},
        ],
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(email="aluno@exemplo.com", password="segredo", token=None)

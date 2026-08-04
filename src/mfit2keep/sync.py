"""Orquestra o caminho completo: MFIT → modelo → notas → destino."""

from typing import Any

from mfit2keep.mfit import MfitClient
from mfit2keep.models import Workout
from mfit2keep.parser import parse_routine, parse_session


async def fetch_workouts(client: MfitClient, routine_id: int | str) -> list[Workout]:
    """Busca a rotina e a sessão de cada dia — os dias vão todos em paralelo."""
    routine: dict[str, Any] = await client.workout_details(routine_id)

    days: list[dict[str, Any]] = routine.get("workouts") or []
    if not days:
        # Alguns treinos avulsos não têm dias: a própria resposta é a sessão.
        return [parse_session(routine)]

    day_ids = [day["id"] for day in days if day.get("id") is not None]
    sessions = await client.workout_sessions(day_ids)
    return parse_routine(routine, sessions)


async def list_routines(client: MfitClient) -> list[dict[str, Any]]:
    routines = await client.list_workouts()
    return routines if isinstance(routines, list) else [routines]

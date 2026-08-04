"""Orquestra o caminho completo: MFIT → modelo → notas → destino."""

from typing import Any

from .config import Settings
from .destinations.base import NoteDestination, NoteResult
from .mfit import MfitClient
from .models import ChecklistNote, Workout
from .parser import parse_routine, parse_session
from .render import RenderOptions, routine_to_notes


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


def build_notes(
    workouts: list[Workout], options: RenderOptions | None = None
) -> list[ChecklistNote]:
    return routine_to_notes(workouts, options)


async def sync(
    settings: Settings,
    routine_id: int | str,
    destination: NoteDestination,
    options: RenderOptions | None = None,
) -> list[NoteResult]:
    async with MfitClient(settings) as client:
        workouts = await fetch_workouts(client, routine_id)
    async with destination:
        return await destination.upsert_all(build_notes(workouts, options))

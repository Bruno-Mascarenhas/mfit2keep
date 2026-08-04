"""A costura de fonte: o app tem que funcionar sem o MFIT existir."""

import json
from pathlib import Path

import pytest

from mfit2keep.interchange import FORMAT_NAME, FORMAT_VERSION, workouts_to_dict
from mfit2keep.models import Exercise, Workout
from mfit2keep.render import routine_to_notes
from mfit2keep.sources.base import SourceError, WorkoutSource
from mfit2keep.sources.workout_file import WorkoutFileSource


def treinos() -> list[Workout]:
    return [
        Workout(
            id="1",
            name="Peito",
            letter="A",
            exercises=[Exercise(name="Supino", reps="4x10", rest="60s")],
        ),
        Workout(id="2", name="Costas", letter="B", exercises=[Exercise(name="Remada")]),
    ]


def arquivo_com(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "treinos.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def exportado(tmp_path: Path) -> Path:
    return arquivo_com(tmp_path, workouts_to_dict(treinos()))


def test_file_source_implements_the_contract() -> None:
    assert issubclass(WorkoutFileSource, WorkoutSource)


async def test_file_source_returns_the_exported_workouts(tmp_path: Path) -> None:
    async with WorkoutFileSource(exportado(tmp_path)) as source:
        assert await source.fetch_workouts(None) == treinos()


async def test_file_source_ignores_the_routine_id(tmp_path: Path) -> None:
    # Um arquivo já é a rotina inteira; exigir id seria cerimônia à toa.
    async with WorkoutFileSource(exportado(tmp_path)) as source:
        assert await source.fetch_workouts("qualquer-coisa") == treinos()


async def test_file_source_lists_one_routine(tmp_path: Path) -> None:
    async with WorkoutFileSource(exportado(tmp_path)) as source:
        [routine] = await source.list_routines()

    assert "treinos.json" in routine.name
    assert "2 treinos" in routine.name


async def test_render_is_identical_whatever_the_source(tmp_path: Path) -> None:
    # O ponto da arquitetura: trocar a fonte não muda uma vírgula da nota.
    async with WorkoutFileSource(exportado(tmp_path)) as source:
        from_file = await source.fetch_workouts(None)

    assert routine_to_notes(from_file) == routine_to_notes(treinos())


async def test_missing_file_is_a_clear_error(tmp_path: Path) -> None:
    async with WorkoutFileSource(tmp_path / "nao-existe.json") as source:
        with pytest.raises(SourceError, match="Não consegui ler"):
            await source.fetch_workouts(None)


async def test_broken_json_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "treinos.json"
    path.write_text("{isso nao e json", encoding="utf-8")

    async with WorkoutFileSource(path) as source:
        with pytest.raises(SourceError, match="não é JSON válido"):
            await source.fetch_workouts(None)


async def test_json_that_is_not_an_export_is_rejected(tmp_path: Path) -> None:
    async with WorkoutFileSource(arquivo_com(tmp_path, [1, 2, 3])) as source:
        with pytest.raises(SourceError, match="não contém um export"):
            await source.fetch_workouts(None)


async def test_future_format_version_is_rejected(tmp_path: Path) -> None:
    payload = {"format": FORMAT_NAME, "version": FORMAT_VERSION + 1, "workouts": []}

    async with WorkoutFileSource(arquivo_com(tmp_path, payload)) as source:
        with pytest.raises(SourceError, match="versão"):
            await source.fetch_workouts(None)

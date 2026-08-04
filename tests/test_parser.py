from typing import Any

import pytest

from mfit2keep.parser import day_letter, parse_routine, parse_session
from tests.conftest import exercise, group, serie


def test_day_letter_maps_dia_tipo_to_alphabet() -> None:
    assert day_letter(1) == "A"
    assert day_letter(5) == "E"
    assert day_letter(26) == "Z"


@pytest.mark.parametrize("value", [0, 27, None, "", "abc"])
def test_day_letter_rejects_out_of_range(value: object) -> None:
    assert day_letter(value) is None


def test_parse_session_reads_names_reps_and_rest(session_bicep: dict[str, Any]) -> None:
    workout = parse_session(session_bicep)

    assert workout.name == "Bíceps/Triceps"
    assert [e.name for e in workout.exercises] == [
        "Triceps Coice na Polia",
        "Rosca Scott com Halteres",
        "Esteira Caminhada",
    ]
    assert workout.exercises[0].reps == "3x12 a 15"
    assert workout.exercises[0].rest == "45s"


def test_cardio_without_interval_has_no_rest(session_bicep: dict[str, Any]) -> None:
    cardio = parse_session(session_bicep).exercises[-1]

    # intervalText "0" significa "sem intervalo" — não pode virar "0s" na nota.
    assert cardio.rest is None
    assert cardio.reps == "40"


def test_load_zero_is_dropped(session_bicep: dict[str, Any]) -> None:
    assert all(e.load is None for e in parse_session(session_bicep).exercises)


def test_load_with_value_gets_unit() -> None:
    session = {"id": 1, "nome": "X", "exercs": [group(exercise("Supino", serie(carga="20")))]}

    assert parse_session(session).exercises[0].load == "20kg"


def test_combined_series_share_a_group() -> None:
    session = {
        "id": 1,
        "nome": "Bi-set",
        "exercs": [
            group(exercise("Rosca Direta"), exercise("Tríceps Testa")),
            group(exercise("Agachamento"), order=1),
        ],
    }

    first, second, third = parse_session(session).exercises
    assert first.group == second.group is not None
    assert third.group is None


def test_exercises_follow_group_order() -> None:
    session = {
        "id": 1,
        "nome": "X",
        "exercs": [
            group(exercise("Terceiro"), order=2),
            group(exercise("Primeiro"), order=0),
            group(exercise("Segundo"), order=1),
        ],
    }

    assert [e.name for e in parse_session(session).exercises] == [
        "Primeiro",
        "Segundo",
        "Terceiro",
    ]


def test_repeated_series_are_deduplicated() -> None:
    session = {
        "id": 1,
        "nome": "X",
        "exercs": [group(exercise("Supino", serie(), serie(), serie()))],
    }

    # Três séries idênticas viram um texto só, não "3x12 / 3x12 / 3x12".
    assert parse_session(session).exercises[0].reps == "3x12 a 15"


def test_distinct_series_are_joined() -> None:
    session = {
        "id": 1,
        "nome": "X",
        "exercs": [group(exercise("Supino", serie(repeticao="12"), serie(repeticao="10")))],
    }

    assert parse_session(session).exercises[0].reps == "12 / 10"


def test_parse_routine_uses_day_metadata(
    routine: dict[str, Any], session_bicep: dict[str, Any]
) -> None:
    sessions = {
        "156902750": session_bicep,
        "156902751": {"id": 156902751, "nome": "Costa", "exercs": [group(exercise("Remada"))]},
    }

    workouts = parse_routine(routine, sessions)

    assert [w.title for w in workouts] == ["A — Bíceps/Triceps", "B — Costa"]


def test_parse_routine_skips_days_without_session(routine: dict[str, Any]) -> None:
    workouts = parse_routine(routine, {"156902750": {"id": 1, "nome": "X", "exercs": []}})

    assert len(workouts) == 1


def test_exercise_without_name_gets_placeholder() -> None:
    anonymous = exercise("") | {"name": None}
    session = {"id": 1, "nome": "X", "exercs": [group(anonymous)]}

    assert parse_session(session).exercises[0].name == "Exercício sem nome"


def test_series_columns_stay_aligned() -> None:
    session = {
        "id": 1,
        "nome": "X",
        "exercs": [
            group(
                exercise(
                    "Supino",
                    serie(repeticao="12", carga="20", intervalText="60"),
                    serie(repeticao="10", carga="30", intervalText="60"),
                )
            )
        ],
    }

    supino = parse_session(session).exercises[0]

    assert supino.reps == "12 / 10"
    assert supino.load == "20kg / 30kg"
    # Coluna constante encolhe: mostrar "60s" uma vez não é ambíguo.
    assert supino.rest == "60s"


def test_missing_value_in_a_varying_column_keeps_its_slot() -> None:
    session = {
        "id": 1,
        "nome": "X",
        "exercs": [
            group(
                exercise(
                    "Supino",
                    serie(repeticao="12", carga="0"),
                    serie(repeticao="10", carga="30"),
                )
            )
        ],
    }

    supino = parse_session(session).exercises[0]

    # Sem o "—", a carga "30kg" pareceria valer para a primeira série.
    assert supino.reps == "12 / 10"
    assert supino.load == "— / 30kg"


def test_identical_series_collapse_to_one_row() -> None:
    session = {
        "id": 1,
        "nome": "X",
        "exercs": [group(exercise("Supino", serie(), serie(), serie()))],
    }

    supino = parse_session(session).exercises[0]

    assert supino.reps == "3x12 a 15"
    assert supino.rest == "45s"

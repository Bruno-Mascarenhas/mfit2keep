"""O formato neutro é o que permite sair do MFIT — ele precisa fechar o ciclo."""

import pytest

from mfit2keep.interchange import (
    FORMAT_NAME,
    FORMAT_VERSION,
    InterchangeError,
    workouts_from_dict,
    workouts_to_dict,
)
from mfit2keep.models import Exercise, Workout


def treinos() -> list[Workout]:
    return [
        Workout(
            id="156902750",
            name="Bíceps/Triceps",
            letter="A",
            description="aquecer antes",
            exercises=[
                Exercise(name="Rosca Direta", reps="3x12", load="20kg", rest="45s"),
                Exercise(name="Tríceps Testa", reps="3x12", notes="pegada fechada"),
            ],
        ),
        Workout(id="156902751", name="Costa", letter="B", exercises=[]),
    ]


def test_round_trip_preserves_everything() -> None:
    original = treinos()

    assert workouts_from_dict(workouts_to_dict(original)) == original


def test_export_declares_format_and_version() -> None:
    payload = workouts_to_dict(treinos())

    assert payload["format"] == FORMAT_NAME
    assert payload["version"] == FORMAT_VERSION


def test_export_is_plain_json_without_python_types() -> None:
    payload = workouts_to_dict(treinos())

    exercise = payload["workouts"][0]["exercises"][0]
    assert set(exercise) == {"name", "reps", "load", "rest", "notes", "group"}
    assert all(value is None or isinstance(value, str) for value in exercise.values())


def test_workout_without_exercises_round_trips() -> None:
    empty = [Workout(id="1", name="Descanso", exercises=[])]

    assert workouts_from_dict(workouts_to_dict(empty)) == empty


def test_another_tool_can_produce_the_format_by_hand() -> None:
    # O ponto do formato: qualquer ferramenta gera isto sem importar o pacote.
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [{"name": "Peito", "exercises": [{"name": "Supino", "reps": "4x10"}]}],
    }

    [workout] = workouts_from_dict(payload)

    assert workout.name == "Peito"
    assert workout.exercises[0] == Exercise(name="Supino", reps="4x10")


def test_numeric_field_is_accepted_as_text() -> None:
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [{"name": "Peito", "exercises": [{"name": "Supino", "reps": 12}]}],
    }

    assert workouts_from_dict(payload)[0].exercises[0].reps == "12"


def test_foreign_file_is_rejected() -> None:
    with pytest.raises(InterchangeError, match="não é um export"):
        workouts_from_dict({"format": "outra-coisa", "version": 1, "workouts": []})


def test_future_version_is_rejected_instead_of_misread() -> None:
    # Ler campo com significado novo em silêncio seria pior que falhar.
    with pytest.raises(InterchangeError, match="versão"):
        workouts_from_dict({"format": FORMAT_NAME, "version": FORMAT_VERSION + 1, "workouts": []})


def test_missing_workouts_list_is_rejected() -> None:
    with pytest.raises(InterchangeError, match="workouts"):
        workouts_from_dict({"format": FORMAT_NAME, "version": FORMAT_VERSION})


def test_exercise_without_name_is_rejected() -> None:
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [{"name": "Peito", "exercises": [{"reps": "4x10"}]}],
    }

    with pytest.raises(InterchangeError, match="sem nome"):
        workouts_from_dict(payload)


def test_structure_where_text_was_expected_is_rejected() -> None:
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [{"name": "Peito", "exercises": [{"name": "Supino", "reps": {"a": 1}}]}],
    }

    with pytest.raises(InterchangeError, match="Esperava texto"):
        workouts_from_dict(payload)

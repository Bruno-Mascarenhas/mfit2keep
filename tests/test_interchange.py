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
                Exercise(
                    name="Rosca Direta",
                    reps="3x12",
                    load="20kg",
                    rest="45s",
                    muscle_group="Bíceps",
                ),
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
    assert set(exercise) == {"name", "reps", "load", "rest", "notes", "group", "muscle_group"}
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


def test_workouts_without_id_get_distinct_ones() -> None:
    # Num arquivo escrito à mão o campo costuma faltar. Sem id distinto, o
    # destino trataria os cinco dias como um só e quatro sumiriam.
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [
            {"name": "Peito", "exercises": [{"name": "Supino"}]},
            {"name": "Costas", "exercises": [{"name": "Remada"}]},
        ],
    }

    ids = [workout.id for workout in workouts_from_dict(payload)]

    assert len(set(ids)) == 2
    assert all(ids)


def test_derived_id_is_stable_when_the_order_changes() -> None:
    def payload(nomes: list[str]) -> dict[str, object]:
        return {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "workouts": [{"name": nome, "exercises": [{"name": "X"}]} for nome in nomes],
        }

    primeiro = {w.name: w.id for w in workouts_from_dict(payload(["Peito", "Costas"]))}
    invertido = {w.name: w.id for w in workouts_from_dict(payload(["Costas", "Peito"]))}

    # Reordenar os dias no arquivo não pode desfazer o vínculo com as notas.
    assert primeiro == invertido


def test_two_workouts_with_the_same_name_still_get_distinct_ids() -> None:
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [
            {"name": "Perna", "exercises": [{"name": "Agachamento"}]},
            {"name": "Perna", "exercises": [{"name": "Leg Press"}]},
        ],
    }

    ids = [workout.id for workout in workouts_from_dict(payload)]

    assert len(set(ids)) == 2


def test_explicit_id_always_wins() -> None:
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [{"id": "156902750", "name": "Peito", "exercises": [{"name": "Supino"}]}],
    }

    assert workouts_from_dict(payload)[0].id == "156902750"


def test_line_break_in_a_field_is_flattened() -> None:
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [{"name": "Peito", "exercises": [{"name": "Supino\nInclinado"}]}],
    }

    assert workouts_from_dict(payload)[0].exercises[0].name == "Supino Inclinado"

"""O emoji do título e o reconhecimento de cardio."""

import pytest

from mfit2keep.models import Exercise, Workout
from mfit2keep.muscles import DEFAULT_EMOJI, exercise_emoji, is_cardio, workout_emoji


def workout(name: str, *exercises: Exercise) -> Workout:
    return Workout(id="1", name=name, exercises=list(exercises))


@pytest.mark.parametrize(
    ("name", "emoji"),
    [
        ("Bíceps/Triceps", "💪"),
        ("Biceps e triceps", "💪"),
        ("Braço", "💪"),
        ("Costa", "🦍"),
        ("Costas e Bíceps", "🦍💪"),
        ("Dorsal", "🦍"),
        ("Perna", "🦵"),
        ("Inferiores", "🦵"),
        ("Membros inferiores", "🦵"),
        ("Ombro", "🙌"),
        ("Deltoides", "🙌"),
        ("Peitoral", "🐦"),
        ("Glúteos", "🍑"),
        ("Abdômen", "🔥"),
        ("Cardio", "🏃"),
        ("Alongamento", "🧘"),
    ],
)
def test_workout_name_picks_the_emoji(name: str, emoji: str) -> None:
    assert workout_emoji(workout(name)) == emoji


def test_accent_and_case_do_not_matter() -> None:
    assert workout_emoji(workout("BÍCEPS")) == workout_emoji(workout("biceps"))


def test_two_groups_follow_the_order_of_the_name() -> None:
    assert workout_emoji(workout("Peito e Tríceps")) == "🐦💪"
    assert workout_emoji(workout("Tríceps e Peito")) == "💪🐦"


def test_a_third_group_does_not_fit_the_watch() -> None:
    emoji = workout_emoji(workout("Peito, Ombro e Tríceps"))

    # Os três grupos casam; só os dois primeiros cabem no título.
    assert emoji == "🐦🙌"
    assert "💪" not in emoji


def test_unknown_name_falls_back_to_the_exercises() -> None:
    treino = workout(
        "Treino A",
        Exercise(name="Supino Reto", muscle_group="Peitoral"),
        Exercise(name="Crucifixo", muscle_group="Peitoral"),
        Exercise(name="Tríceps Corda", muscle_group="Tríceps"),
    )

    assert workout_emoji(treino) == "🐦💪"


@pytest.mark.parametrize(
    ("name", "emoji"),
    [
        # O músculo da coxa também se chama "bíceps"; o da panturrilha, "tríceps".
        ("Bíceps Femoral Deitado", "🦵"),
        ("Tríceps Sural em Pé", "🦵"),
        ("Deltoide Posterior na Máquina", "🙌"),
        ("Oblíquos na Polia", "🔥"),
        ("Isquiotibial na Bola", "🦵"),
    ],
)
def test_a_misleading_name_does_not_win(name: str, emoji: str) -> None:
    assert exercise_emoji(Exercise(name=name)) == emoji


def test_exercise_name_saves_a_group_that_is_not_muscular() -> None:
    # O MFIT às vezes classifica pelo material ("Elásticos e Faixas").
    exercise = Exercise(name="Biceps Concentrado", muscle_group="Elásticos e Faixas")

    assert exercise_emoji(exercise) == "💪"


def test_abs_and_cardio_do_not_name_the_day() -> None:
    # Todo dia da rotina fecha com abdominal e esteira; não é isso que o define.
    treino = workout(
        "Treino B",
        Exercise(name="Remada Baixa", muscle_group="Dorsal"),
        Exercise(name="Abdominal Supra", muscle_group="Abdômen"),
        Exercise(name="Abdominal Infra", muscle_group="Abdômen"),
        Exercise(name="Esteira Caminhada", muscle_group="Aeróbio"),
    )

    assert workout_emoji(treino) == "🦍"


def test_a_day_of_only_cardio_still_gets_its_emoji() -> None:
    treino = workout("Dia 6", Exercise(name="Esteira", muscle_group="Aeróbio"))

    assert workout_emoji(treino) == "🏃"


def test_workout_without_any_clue_keeps_the_barbell() -> None:
    assert workout_emoji(workout("Treino A")) == DEFAULT_EMOJI
    assert workout_emoji(workout("Treino A", Exercise(name="Exercício sem nome"))) == DEFAULT_EMOJI


def test_the_letter_prefix_does_not_confuse_the_choice() -> None:
    assert workout_emoji(Workout(id="1", name="A - Costas", letter="A")) == "🦍"


@pytest.mark.parametrize(
    "exercise",
    [
        Exercise(name="Esteira Caminhada", muscle_group="Aeróbio"),
        Exercise(name="Bike Spinning", muscle_group="Aeróbio"),
        Exercise(name="Esteira Caminhada"),
        Exercise(name="Elíptico"),
        Exercise(name="Corrida na esteira"),
    ],
)
def test_cardio_is_recognized(exercise: Exercise) -> None:
    assert is_cardio(exercise)


@pytest.mark.parametrize(
    "exercise",
    [
        Exercise(name="Supino Reto", muscle_group="Peitoral"),
        Exercise(name="Abdominal Remador", muscle_group="Abdômen"),
        # "Corda" é acessório de tríceps — não pode virar pular corda.
        Exercise(name="Tríceps na Polia com Corda", muscle_group="Tríceps"),
        Exercise(name="Remada Baixa Triangulo", muscle_group="Dorsal"),
    ],
)
def test_weightlifting_is_not_cardio(exercise: Exercise) -> None:
    assert not is_cardio(exercise)

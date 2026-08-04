from mfit2keep.models import Exercise, Workout
from mfit2keep.render import RenderOptions, exercise_line, routine_to_notes, workout_to_note


def make_workout(*exercises: Exercise, letter: str | None = "A") -> Workout:
    return Workout(id="1", name="Peito", letter=letter, exercises=list(exercises))


def test_line_puts_name_first() -> None:
    line = exercise_line(Exercise(name="Supino", reps="3x12", rest="45s"), RenderOptions())

    # O nome vem primeiro porque é o que sobra quando o relógio trunca a linha.
    assert line.startswith("Supino")


def test_line_includes_reps_load_and_rest() -> None:
    line = exercise_line(
        Exercise(name="Supino", reps="3x12", load="20kg", rest="45s"), RenderOptions()
    )

    assert "3x12" in line
    assert "20kg" in line
    assert "45s" in line


def test_options_can_hide_rest_and_load() -> None:
    line = exercise_line(
        Exercise(name="Supino", reps="3x12", load="20kg", rest="45s"),
        RenderOptions(include_rest=False, include_load=False),
    )

    assert line == "Supino — 3x12"


def test_line_without_details_is_just_the_name() -> None:
    assert exercise_line(Exercise(name="Prancha"), RenderOptions()) == "Prancha"


def test_notes_go_in_parentheses() -> None:
    line = exercise_line(Exercise(name="Supino", notes="pegada fechada"), RenderOptions())

    assert line == "Supino (pegada fechada)"


def test_max_line_length_truncates_with_ellipsis() -> None:
    long = Exercise(name="Elevação Lateral Inclinado com Halteres", reps="3x15")

    line = exercise_line(long, RenderOptions(max_line_length=20))

    assert len(line) <= 20
    assert line.endswith("…")


def test_max_line_length_zero_does_not_truncate() -> None:
    long = Exercise(name="Elevação Lateral Inclinado com Halteres", reps="3x15")

    assert not exercise_line(long, RenderOptions(max_line_length=0)).endswith("…")


def test_items_are_numbered_by_default() -> None:
    note = workout_to_note(make_workout(Exercise(name="A"), Exercise(name="B")))

    assert [i.text for i in note.items] == ["1. A", "2. B"]


def test_numbering_can_be_disabled() -> None:
    note = workout_to_note(make_workout(Exercise(name="A")), RenderOptions(numbered=False))

    assert note.items[0].text == "A"


def test_combined_series_continuation_is_marked() -> None:
    note = workout_to_note(
        make_workout(
            Exercise(name="Rosca", group="g0"),
            Exercise(name="Tríceps", group="g0"),
            Exercise(name="Agachamento"),
        )
    )

    assert not note.items[0].text.startswith("↳")
    assert "↳" in note.items[1].text
    assert "↳" not in note.items[2].text


def test_title_carries_letter_and_prefix() -> None:
    note = workout_to_note(make_workout(Exercise(name="A")))

    assert note.title == "🏋️ A — Peito"


def test_title_does_not_repeat_letter_already_in_name() -> None:
    workout = Workout(id="1", name="A - Peito", letter="A", exercises=[])

    assert workout.title == "A - Peito"


def test_external_id_is_stable_per_workout() -> None:
    note = workout_to_note(make_workout(Exercise(name="A")))

    # É o que permite atualizar a nota em vez de duplicar na próxima sincronização.
    assert note.external_id == "mfit:1"


def test_routine_to_notes_keeps_one_note_per_workout() -> None:
    workouts = [
        Workout(id="1", name="Peito", exercises=[Exercise(name="Supino")]),
        Workout(id="2", name="Costa", exercises=[Exercise(name="Remada")]),
    ]

    assert len(routine_to_notes(workouts)) == 2


def test_empty_workout_yields_note_without_items() -> None:
    assert workout_to_note(make_workout()).items == []

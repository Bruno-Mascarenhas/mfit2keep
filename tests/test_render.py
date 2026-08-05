import pytest

from mfit2keep.models import Exercise, Workout
from mfit2keep.render import (
    RenderOptions,
    RepsMode,
    TitleStyle,
    exercise_line,
    routine_to_notes,
    watch_reps,
    workout_to_note,
)


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

    # O estilo padrão é o de sempre: o mesmo halteres em todos os dias.
    assert note.title == "🏋️ A — Peito"


def rotina() -> list[Workout]:
    return [
        Workout(id=str(position), name=name)
        for position, name in enumerate(["Bíceps/Triceps", "Costa", "Perna", "Peitoral", "Ombro"])
    ]


def test_classic_style_repeats_the_same_emoji() -> None:
    titles = [note.title for note in routine_to_notes(rotina(), RenderOptions())]

    assert titles == [f"🏋️ {workout.name}" for workout in rotina()]


def test_muscle_style_gives_each_day_its_own_emoji() -> None:
    options = RenderOptions(style=TitleStyle.MUSCULOS)

    titles = [note.title for note in routine_to_notes(rotina(), options)]

    # Na lista do relógio é o emoji que separa um dia do outro.
    assert titles == ["💪 Bíceps/Triceps", "🦍 Costa", "🦵 Perna", "🐦 Peitoral", "🙌 Ombro"]


def test_clean_style_has_no_emoji_at_all() -> None:
    options = RenderOptions(style=TitleStyle.CLEAN)

    titles = [note.title for note in routine_to_notes(rotina(), options)]

    assert titles == [workout.name for workout in rotina()]


def test_clean_style_still_carries_the_day_letter() -> None:
    note = workout_to_note(make_workout(), RenderOptions(style=TitleStyle.CLEAN))

    assert note.title == "A — Peito"


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


def test_title_keeps_the_letter_when_the_name_starts_with_it() -> None:
    # "Abdominal" começa com "A", mas isso não é o prefixo do dia.
    workout = Workout(id="1", name="Abdominal e Core", letter="A", exercises=[])

    assert workout.title == "A — Abdominal e Core"


def test_title_does_not_duplicate_a_real_letter_prefix() -> None:
    for name in ("A - Peito", "A — Peito", "A: Peito", "A) Peito", "A. Peito"):
        assert Workout(id="1", name=name, letter="A", exercises=[]).title == name


def test_title_without_letter_is_just_the_name() -> None:
    assert Workout(id="1", name="Peito", letter=None, exercises=[]).title == "Peito"


def test_title_of_a_name_equal_to_the_letter() -> None:
    assert Workout(id="1", name="A", letter="A", exercises=[]).title == "A"


def test_title_uses_a_different_letter_prefix_normally() -> None:
    # Nome com prefixo "B -" num dia "A": o dia continua tendo que aparecer.
    workout = Workout(id="1", name="B - Costas", letter="A", exercises=[])

    assert workout.title == "A — B - Costas"


@pytest.mark.parametrize(
    ("prescribed", "minimum", "maximum"),
    [
        # A faixa é do professor; a ponta é de quem treina.
        ("3 a 4x de 12 a 15", "3x12", "4x15"),
        ("3 a 4x de 15", "3x15", "4x15"),
        ("3x de 12 a 15", "3x12", "3x15"),
        ("3x12 a 15", "3x12", "3x15"),
        ("3 a 4x de 12", "3x12", "4x12"),
        ("3x12-15", "3x12", "3x15"),
        ("3 - 4x de 12 até 15", "3x12", "4x15"),
        ("4X10", "4x10", "4x10"),
        # Sem faixa, as duas pontas são a mesma.
        ("3x15", "3x15", "3x15"),
        ("5x20", "5x20", "5x20"),
        # O que o professor escreveu além da conta continua inteiro.
        ("3x12 a 15 3T", "3x12 3T", "3x15 3T"),
        ("3x15 2T", "3x15 2T", "3x15 2T"),
        ("3x12 a 15 halteres", "3x12 halteres", "3x15 halteres"),
        ("3x15+ 20 ISO + 152T", "3x15+ 20 ISO + 152T", "3x15+ 20 ISO + 152T"),
        # Drop-set e pirâmide são sequências de séries, não faixas: mexer ali
        # apagaria um degrau do treino.
        ("3x12/10/8", "3x12/10/8", "3x12/10/8"),
        ("3x12-10-8", "3x12-10-8", "3x12-10-8"),
        ("4x10 - 8 - 6", "4x10 - 8 - 6", "4x10 - 8 - 6"),
        # Número colado numa letra é unidade, não a ponta de uma faixa.
        ("3x12 a 40kg", "3x12 a 40kg", "3x12 a 40kg"),
        ("3x12 - 40kg", "3x12 - 40kg", "3x12 - 40kg"),
        # Prescrição em texto livre passa intacta.
        ("até a falha", "até a falha", "até a falha"),
        ("máximo", "máximo", "máximo"),
    ],
)
def test_reps_pick_the_end_of_the_range(prescribed: str, minimum: str, maximum: str) -> None:
    supino = Exercise(name="Supino", reps=prescribed)

    assert watch_reps(supino, RepsMode.MIN) == minimum
    assert watch_reps(supino, RepsMode.MAX) == maximum
    # O padrão não opina: é a ficha como o MFIT mandou.
    assert watch_reps(supino, RepsMode.MFIT) == prescribed


def test_the_default_mode_leaves_the_prescription_alone() -> None:
    supino = Exercise(name="Supino", reps="3 a 4x de 12 a 15")

    assert exercise_line(supino, RenderOptions()) == "Supino — 3 a 4x de 12 a 15"


@pytest.mark.parametrize(
    ("prescribed", "expected"),
    [
        ("35", {"mfit": "35 min", "min": "35 min", "max": "35 min"}),
        ("25 a 30", {"mfit": "25 a 30 min", "min": "25 min", "max": "30 min"}),
        # Já veio com unidade: não se repete.
        ("35 min", {"mfit": "35 min", "min": "35 min", "max": "35 min"}),
        ("35min", {"mfit": "35min", "min": "35min", "max": "35min"}),
    ],
)
def test_cardio_reps_are_always_minutes(prescribed: str, expected: dict[str, str]) -> None:
    # Minutos não são preferência: no aeróbio o campo de repetições é tempo,
    # e "35" sem unidade é só um número solto na tela.
    esteira = Exercise(name="Esteira Caminhada", reps=prescribed, muscle_group="Aeróbio")

    assert {mode.value: watch_reps(esteira, mode) for mode in RepsMode} == expected


def test_cardio_prescribed_in_sets_still_picks_the_end_of_the_range() -> None:
    # Circuito catalogado como aeróbio: a unidade não é minuto, mas a faixa
    # continua sendo faixa — a escolha de --reps não pode sumir aqui.
    corda = Exercise(name="Corda Naval", reps="3 a 4x de 12 a 15", muscle_group="Aeróbio")

    assert watch_reps(corda, RepsMode.MIN) == "3x12"
    assert watch_reps(corda, RepsMode.MAX) == "4x15"
    assert watch_reps(corda, RepsMode.MFIT) == "3 a 4x de 12 a 15"


def test_only_cardio_gets_minutes() -> None:
    # "15" num exercício de força é repetição, não tempo.
    assert watch_reps(Exercise(name="Abdominal Supra", reps="15"), RepsMode.MIN) == "15"


def test_cardio_line_reads_like_the_watch_shows_it() -> None:
    esteira = Exercise(name="Esteira Caminhada", reps="35", muscle_group="Aeróbio")

    assert exercise_line(esteira, RenderOptions()) == "Esteira Caminhada — 35 min"


def test_exercise_without_reps_survives_the_shortening() -> None:
    assert watch_reps(Exercise(name="Prancha"), RepsMode.MIN) is None

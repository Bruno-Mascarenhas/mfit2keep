from mfit2keep.matching import CheckedState, item_key


def test_key_ignores_the_numbering() -> None:
    # Remover um exercício renumera todos os seguintes; isso não pode zerar as marcas.
    assert item_key("3. Supino Reto — 4x10") == item_key("2. Supino Reto — 4x10")


def test_key_ignores_the_prescription() -> None:
    assert item_key("1. Supino — 4x10 · ↺60s") == item_key("1. Supino — 3x12 · 20kg · ↺45s")


def test_key_ignores_the_combined_series_marker() -> None:
    assert item_key("↳ 2. Tríceps Testa — 3x12") == item_key("2. Tríceps Testa — 3x12")


def test_key_is_case_insensitive() -> None:
    assert item_key("1. SUPINO — 4x10") == item_key("1. supino — 4x10")


def test_different_exercises_have_different_keys() -> None:
    assert item_key("1. Supino — 4x10") != item_key("1. Crucifixo — 4x10")


def test_item_without_details_still_has_a_key() -> None:
    assert item_key("1. Prancha") == "prancha"


def test_state_survives_renumbering() -> None:
    before = CheckedState([("1. Aquecimento — 5min", True), ("2. Supino — 4x10", True)])

    # O primeiro exercício saiu da ficha; o Supino virou o item 1.
    assert before.take("1. Supino — 4x10") is True


def test_state_survives_load_change() -> None:
    before = CheckedState([("1. Supino — 4x10 · ↺60s", True)])

    assert before.take("1. Supino — 4x10 · 30kg · ↺60s") is True


def test_unknown_item_starts_unchecked() -> None:
    before = CheckedState([("1. Supino — 4x10", True)])

    assert before.take("1. Crucifixo — 3x12") is False


def test_duplicate_names_are_consumed_in_order() -> None:
    # Drop-set: o mesmo exercício aparece duas vezes na ficha.
    before = CheckedState([("1. Rosca — 3x12", True), ("5. Rosca — 1x20", False)])

    assert before.take("1. Rosca — 3x12") is True
    assert before.take("5. Rosca — 1x20") is False


def test_duplicate_names_do_not_share_one_mark() -> None:
    before = CheckedState([("1. Rosca — 3x12", True)])

    assert before.take("1. Rosca — 3x12") is True
    # Só havia uma marca; a segunda ocorrência não pode herdá-la.
    assert before.take("5. Rosca — 1x20") is False


def test_empty_state_marks_nothing() -> None:
    assert CheckedState([]).take("1. Supino — 4x10") is False

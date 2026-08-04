from pathlib import Path

import pytest

from mfit2keep.destinations.base import MARKER, Action
from mfit2keep.destinations.local import (
    LocalDestinationError,
    LocalMarkdownDestination,
    slugify,
)
from mfit2keep.models import ChecklistItem, ChecklistNote


def note(*texts: str, title: str = "🏋️ A — Peito", external_id: str = "mfit:1") -> ChecklistNote:
    return ChecklistNote(
        title=title,
        items=[ChecklistItem(text=t) for t in texts],
        external_id=external_id,
    )


def test_slugify_strips_accents_and_symbols() -> None:
    assert slugify("🏋️ A — Bíceps/Triceps") == "a-bícepstriceps"


def test_slugify_never_returns_empty() -> None:
    assert slugify("🏋️") == "nota"


async def test_first_write_creates(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        result = await destination.upsert(note("1. Supino"))

    assert result.action is Action.CREATED
    assert Path(result.reference or "").exists()


async def test_second_identical_write_is_unchanged(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        await destination.upsert(note("1. Supino"))
        result = await destination.upsert(note("1. Supino"))

    assert result.action is Action.UNCHANGED


async def test_changed_content_updates_same_file(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        first = await destination.upsert(note("1. Supino"))
        second = await destination.upsert(note("1. Supino", "2. Crucifixo"))

    assert second.action is Action.UPDATED
    # Mesmo treino não pode gerar arquivo novo a cada sincronização.
    assert first.reference == second.reference
    assert len(list(tmp_path.glob("*.md"))) == 1


async def test_markdown_has_checkboxes(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        result = await destination.upsert(note("1. Supino", "2. Crucifixo"))

    content = Path(result.reference or "").read_text(encoding="utf-8")
    assert "- [ ] 1. Supino" in content
    assert "- [ ] 2. Crucifixo" in content
    assert content.startswith("# 🏋️ A — Peito")


async def test_external_id_is_persisted(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        result = await destination.upsert(note("1. Supino"))

    assert "mfit:1" in Path(result.reference or "").read_text(encoding="utf-8")


async def test_upsert_all_writes_every_note(tmp_path: Path) -> None:
    # Treinos distintos têm external_id distinto — é o que os separa em arquivos.
    notes = [
        note("1. Supino", title="A", external_id="mfit:1"),
        note("1. Remada", title="B", external_id="mfit:2"),
    ]

    async with LocalMarkdownDestination(tmp_path) as destination:
        results = await destination.upsert_all(notes)

    assert [r.action for r in results] == [Action.CREATED, Action.CREATED]
    assert len(list(tmp_path.glob("*.md"))) == 2


async def test_out_dir_is_created(tmp_path: Path) -> None:
    target = tmp_path / "nao" / "existe"

    LocalMarkdownDestination(target)

    assert target.is_dir()


async def test_purge_removes_only_stamped_files(tmp_path: Path) -> None:
    intruso = tmp_path / "minhas-anotacoes.md"
    intruso.write_text("# Minhas anotações\n\n- [ ] nada a ver\n", encoding="utf-8")

    async with LocalMarkdownDestination(tmp_path) as destination:
        await destination.upsert(note("1. Supino"))
        results = await destination.purge()

    # Arquivo sem o carimbo é do usuário e não pode sumir.
    assert [r.action for r in results] == [Action.TRASHED]
    assert intruso.exists()
    assert len(list(tmp_path.glob("*.md"))) == 1


async def test_purge_with_archive_moves_instead_of_deleting(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        created = await destination.upsert(note("1. Supino"))
        results = await destination.purge(archive=True)

    assert [r.action for r in results] == [Action.ARCHIVED]
    assert not Path(created.reference or "").exists()
    assert len(list((tmp_path / "arquivadas").glob("*.md"))) == 1


async def test_purge_on_empty_dir_is_a_noop(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        assert await destination.purge() == []


async def test_markdown_carries_the_marker_stamp(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        result = await destination.upsert(note("1. Supino"))

    content = Path(result.reference or "").read_text(encoding="utf-8")
    assert MARKER in content


async def test_resync_preserves_marks_made_in_the_file(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        created = await destination.upsert(note("1. Supino — 4x10", "2. Crucifixo — 3x12"))
        path = Path(created.reference or "")
        # O usuário risca o que já fez, direto no .md.
        path.write_text(
            path.read_text(encoding="utf-8").replace("- [ ] 1. Supino", "- [x] 1. Supino"),
            encoding="utf-8",
        )
        await destination.upsert(
            note("1. Supino — 4x10", "2. Crucifixo — 3x12", "3. Pullover — 3x12")
        )

    content = path.read_text(encoding="utf-8")
    assert "- [x] 1. Supino — 4x10" in content
    assert "- [ ] 3. Pullover — 3x12" in content


async def test_renumbering_keeps_the_marks(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        created = await destination.upsert(note("1. Aquecimento — 5min", "2. Supino — 4x10"))
        path = Path(created.reference or "")
        path.write_text(
            path.read_text(encoding="utf-8").replace("- [ ] 2. Supino", "- [x] 2. Supino"),
            encoding="utf-8",
        )
        # O treinador tira o aquecimento: o Supino vira o item 1.
        await destination.upsert(note("1. Supino — 4x10"))

    assert "- [x] 1. Supino — 4x10" in path.read_text(encoding="utf-8")


async def test_refuses_to_overwrite_a_file_it_did_not_create(tmp_path: Path) -> None:
    intruso = tmp_path / f"{slugify('🏋️ A — Peito')}-1.md"
    intruso.write_text("# Minhas metas 2026\n\n- [x] correr 10km\n", encoding="utf-8")

    with pytest.raises(LocalDestinationError, match="não foi criado pelo mfit2keep"):
        async with LocalMarkdownDestination(tmp_path) as destination:
            await destination.upsert(note("1. Supino"))

    assert "correr 10km" in intruso.read_text(encoding="utf-8")


async def test_renaming_the_workout_does_not_leave_a_stale_file(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        await destination.upsert(note("1. Supino", title="🏋️ A — Peito"))
        await destination.upsert(note("1. Supino", title="🏋️ A — Peitoral"))

    assert len(list(tmp_path.glob("*.md"))) == 1


async def test_similar_titles_do_not_share_a_file(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        await destination.upsert(note("1. Supino", title="Perna A", external_id="mfit:1"))
        await destination.upsert(note("1. Agachamento", title="Perna-A", external_id="mfit:2"))

    # Slug idêntico, treinos diferentes: precisam de arquivos diferentes.
    assert len(list(tmp_path.glob("*.md"))) == 2


async def test_archiving_twice_does_not_overwrite_the_first(tmp_path: Path) -> None:
    async with LocalMarkdownDestination(tmp_path) as destination:
        await destination.upsert(note("1. Supino"))
        await destination.purge(archive=True)
        await destination.upsert(note("1. Supino"))
        await destination.purge(archive=True)

    assert len(list((tmp_path / "arquivadas").glob("*.md"))) == 2

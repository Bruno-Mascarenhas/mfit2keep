from pathlib import Path

from mfit2keep.destinations.base import MARKER, Action
from mfit2keep.destinations.local import LocalMarkdownDestination, slugify
from mfit2keep.models import ChecklistItem, ChecklistNote


def note(*texts: str, title: str = "🏋️ A — Peito") -> ChecklistNote:
    return ChecklistNote(
        title=title,
        items=[ChecklistItem(text=t) for t in texts],
        external_id="mfit:1",
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
    notes = [note("1. Supino", title="A"), note("1. Remada", title="B")]

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

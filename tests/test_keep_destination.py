"""Testes do destino Google Keep.

Usam um ``gkeepapi.Keep`` de verdade com rede desligada: ``createList``, ``get``
e a ordenação por ``sort`` são o código real da biblioteca, então uma regressão
de ordem dos exercícios aparece aqui. Só ``authenticate``/``sync``/``dump``
são substituídos.
"""

import json
from pathlib import Path
from typing import Any

import gkeepapi
import pytest

from mfit2keep import secure_io
from mfit2keep.destinations import keep as keep_module
from mfit2keep.destinations.base import MARKER, Action
from mfit2keep.destinations.keep import KeepDestination
from mfit2keep.keep_auth import KeepCredentials
from mfit2keep.models import ChecklistItem, ChecklistNote


class OfflineKeep:
    """Implementa o ``KeepClient`` delegando para um ``gkeepapi.Keep`` real.

    Composição em vez de herança: a lista e a ordenação são o código de verdade
    da biblioteca, mas nada aqui toca a rede.
    """

    def __init__(self) -> None:
        self._keep = gkeepapi.Keep()
        self.authenticated_with: tuple[str, str, str | None] | None = None
        self.sync_count = 0

    def authenticate(
        self,
        email: str,
        master_token: str,
        state: dict[str, Any] | None = None,
        sync: bool = True,
        device_id: str | None = None,
    ) -> None:
        self.authenticated_with = (email, master_token, device_id)

    def get(self, node_id: str) -> Any:
        return self._keep.get(node_id)

    def createList(
        self, title: str | None = None, items: list[tuple[str, bool]] | None = None
    ) -> Any:
        return self._keep.createList(title, items)

    def sync(self, resync: bool = False) -> None:
        self.sync_count += 1
        # O Keep atribui o server_id na subida; imitamos para as URLs saírem certas.
        for node in self.all():
            if node.server_id is None:
                node.server_id = f"srv-{node.id[:8]}"

    def dump(self) -> dict[str, Any]:
        return {}

    def findLabel(self, query: str, create: bool = False) -> Any:
        return self._keep.findLabel(query, create)

    def find(self, labels: list[Any] | None = None, trashed: bool | None = False) -> Any:
        return self._keep.find(labels=labels, trashed=trashed)

    def all(self) -> Any:
        return self._keep.all()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mapa de notas e cache de estado ficam no tmp — nunca no .state real."""
    monkeypatch.setattr(keep_module, "NOTE_MAP", tmp_path / "keep_notes.json")
    monkeypatch.setattr(keep_module, "STATE_CACHE", tmp_path / "keep_state.json")


@pytest.fixture
def credentials() -> KeepCredentials:
    return KeepCredentials(email="eu@gmail.com", master_token="aas_et/abc", device_id="dead")


def note(*texts: str, title: str = "🏋️ A — Peito") -> ChecklistNote:
    return ChecklistNote(
        title=title,
        items=[ChecklistItem(text=t) for t in texts],
        external_id="mfit:1",
    )


async def test_first_sync_creates_the_list(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)

    [result] = await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    assert result.action is Action.CREATED
    assert result.reference is not None
    assert result.reference.startswith("https://keep.google.com/#NOTE/")


async def test_created_list_keeps_exercise_order(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    wanted = [f"{i}. Exercício {i}" for i in range(1, 11)]

    await KeepDestination(credentials, client=client).upsert_all([note(*wanted)])

    created = next(iter(client.all()))
    assert [item.text for item in created.items] == wanted


async def test_items_start_unchecked(credentials: KeepCredentials) -> None:
    client = OfflineKeep()

    await KeepDestination(credentials, client=client).upsert_all([note("1. Supino")])

    assert all(not item.checked for item in next(iter(client.all())).items)


async def test_identical_resync_is_unchanged(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)

    await destination.upsert_all([note("1. Supino", "2. Crucifixo")])
    [result] = await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    assert result.action is Action.UNCHANGED
    assert len(list(client.all())) == 1


async def test_unchanged_resync_preserves_checkmarks(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    # O usuário marca o primeiro exercício no relógio, no meio do treino.
    created = next(iter(client.all()))
    created.items[0].checked = True

    await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    assert [item.checked for item in created.items] == [True, False]


async def test_changed_workout_updates_the_same_note(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])

    [result] = await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    assert result.action is Action.UPDATED
    # Atualizar não pode duplicar a nota no Keep.
    assert len(list(client.all())) == 1


async def test_update_preserves_order(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. A")])
    wanted = [f"{i}. Exercício {i}" for i in range(1, 9)]

    await destination.upsert_all([note(*wanted)])

    assert [item.text for item in next(iter(client.all())).items] == wanted


async def test_update_keeps_checkmarks_of_surviving_items(
    credentials: KeepCredentials,
) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    created = next(iter(client.all()))
    created.items[1].checked = True  # "2. Crucifixo" feito

    await destination.upsert_all([note("1. Supino", "2. Crucifixo", "3. Pullover")])

    state = {item.text: item.checked for item in created.items}
    assert state == {"1. Supino": False, "2. Crucifixo": True, "3. Pullover": False}


async def test_removed_exercise_disappears(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    await destination.upsert_all([note("1. Supino")])

    assert [item.text for item in next(iter(client.all())).items] == ["1. Supino"]


async def test_title_change_alone_triggers_update(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino", title="🏋️ A — Peito")])

    [result] = await destination.upsert_all([note("1. Supino", title="🏋️ A — Peitoral")])

    assert result.action is Action.UPDATED
    assert next(iter(client.all())).title == "🏋️ A — Peitoral"


async def test_note_map_survives_a_new_destination(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    await KeepDestination(credentials, client=client).upsert_all([note("1. Supino")])

    # Execução seguinte: destino novo, mesmo cliente — tem que reencontrar a nota.
    [result] = await KeepDestination(credentials, client=client).upsert_all([note("1. Supino")])

    assert result.action is Action.UNCHANGED
    assert len(list(client.all())) == 1


async def test_trashed_note_is_recreated(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])

    next(iter(client.all())).trash()
    [result] = await destination.upsert_all([note("1. Supino")])

    assert result.action is Action.CREATED


async def test_each_workout_gets_its_own_note(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    notes = [
        ChecklistNote(title="A", items=[ChecklistItem(text="Supino")], external_id="mfit:1"),
        ChecklistNote(title="B", items=[ChecklistItem(text="Remada")], external_id="mfit:2"),
    ]

    results = await KeepDestination(credentials, client=client).upsert_all(notes)

    assert [r.action for r in results] == [Action.CREATED, Action.CREATED]
    assert len(list(client.all())) == 2


async def test_batch_syncs_once(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    notes = [
        ChecklistNote(title=f"Dia {i}", items=[ChecklistItem(text="X")], external_id=f"mfit:{i}")
        for i in range(5)
    ]

    await KeepDestination(credentials, client=client).upsert_all(notes)

    # Uma subida para o lote inteiro — cinco notas não podem virar cinco syncs.
    assert client.sync_count == 1


async def test_authentication_uses_the_stored_device_id(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    # Sem passar client no construtor, para exercitar o caminho de autenticação.
    destination = KeepDestination(credentials)
    destination._client = client

    await destination.upsert_all([note("1. Supino")])

    assert client.authenticated_with == ("eu@gmail.com", "aas_et/abc", "dead")


async def test_created_note_carries_the_marker_label(credentials: KeepCredentials) -> None:
    client = OfflineKeep()

    await KeepDestination(credentials, client=client).upsert_all([note("1. Supino")])

    created = next(iter(client.all()))
    assert [label.name for label in created.labels.all()] == [MARKER]


async def test_purge_trashes_only_marked_notes(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    minha = client.createList("Lista de compras", [("Café", False)])
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])

    results = await destination.purge()

    # A nota do usuário não tem o label e não pode ser tocada.
    assert [r.action for r in results] == [Action.TRASHED]
    assert not minha.trashed
    assert next(n for n in client.all() if n.title.startswith("🏋️")).trashed


async def test_purge_with_archive_does_not_trash(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])

    results = await destination.purge(archive=True)

    nossa = next(n for n in client.all() if n.title.startswith("🏋️"))
    assert [r.action for r in results] == [Action.ARCHIVED]
    assert nossa.archived
    assert not nossa.trashed


async def test_purge_without_any_marked_note_is_a_noop(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    client.createList("Lista de compras", [("Café", False)])

    results = await KeepDestination(credentials, client=client).purge()

    assert results == []


async def test_sync_after_purge_creates_a_fresh_note(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])
    await destination.purge()

    [result] = await destination.upsert_all([note("1. Supino")])

    # A nota velha foi para a lixeira; sincronizar de novo cria outra, não a ressuscita.
    assert result.action is Action.CREATED


async def test_note_without_the_label_is_never_rewritten(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])

    # O usuário tira o label na mão (ou o id do mapa é de outra conta).
    nossa = next(iter(client.all()))
    label = client.findLabel(MARKER)
    nossa.labels.remove(label)

    [result] = await destination.upsert_all([note("1. Supino", "2. Crucifixo")])

    assert result.action is Action.CREATED
    assert [item.text for item in nossa.items] == ["1. Supino"]


async def test_archiving_releases_the_link(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])
    await destination.purge(archive=True)

    [result] = await destination.upsert_all([note("1. Supino")])

    # Sem soltar o vínculo, o sync atualizaria a nota arquivada e invisível.
    assert result.action is Action.CREATED
    assert len([n for n in client.all() if not n.archived and not n.trashed]) == 1


async def test_renumbering_keeps_the_marks(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Aquecimento — 5min", "2. Supino — 4x10")])

    nossa = next(iter(client.all()))
    nossa.items[1].checked = True  # marcou o Supino no relógio

    await destination.upsert_all([note("1. Supino — 4x10")])

    assert [(i.text, i.checked) for i in nossa.items] == [("1. Supino — 4x10", True)]


async def test_load_change_keeps_the_marks(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino — 4x10")])

    nossa = next(iter(client.all()))
    nossa.items[0].checked = True

    await destination.upsert_all([note("1. Supino — 4x10 · 30kg")])

    assert nossa.items[0].checked is True


async def test_duplicate_exercises_do_not_share_one_mark(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("Rosca — 3x12", "Rosca — 1x20")])

    nossa = next(iter(client.all()))
    nossa.items[0].checked = True  # só a primeira ocorrência

    await destination.upsert_all([note("Rosca — 3x12", "Rosca — 1x20", "Tríceps — 3x12")])

    assert [i.checked for i in nossa.items] == [True, False, False]


async def test_note_map_survives_a_failure_writing_the_state_cache(
    credentials: KeepCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = OfflineKeep()
    real_write = secure_io.write_secret_json

    def fail_on_state_cache(path: Path, data: dict[str, Any]) -> None:
        if path == keep_module.STATE_CACHE:
            raise OSError("disco cheio")
        real_write(path, data)

    monkeypatch.setattr(keep_module, "write_secret_json", fail_on_state_cache)

    await KeepDestination(credentials, client=client).upsert_all([note("1. Supino")])

    # Sem o vínculo gravado, a execução seguinte duplicaria a nota no Keep.
    saved = json.loads(keep_module.NOTE_MAP.read_text(encoding="utf-8"))
    assert saved == {"mfit:1": next(iter(client.all())).id}


async def test_upsert_after_purge_records_the_new_link(credentials: KeepCredentials) -> None:
    client = OfflineKeep()
    destination = KeepDestination(credentials, client=client)
    await destination.upsert_all([note("1. Supino")])
    await destination.purge()

    await destination.upsert_all([note("1. Supino")])

    # `_forgotten` não pode continuar valendo e apagar o vínculo recém-criado.
    saved = json.loads(keep_module.NOTE_MAP.read_text(encoding="utf-8"))
    alive = next(node for node in client.all() if not node.trashed)
    assert saved == {"mfit:1": alive.id}

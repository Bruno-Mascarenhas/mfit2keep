"""Destino Google Keep, via ``gkeepapi`` (não oficial).

A API oficial do Keep é Workspace-only, então conta pessoal só chega lá pelo
``gkeepapi`` autenticado com master token — veja :mod:`mfit2keep.keep_auth`.

Três particularidades moldam este arquivo:

* ``gkeepapi`` é síncrono (usa ``requests``), então tudo vai para uma thread com
  :func:`asyncio.to_thread` — o loop não pode bloquear.
* ``List.add()`` sem ``sort`` explícito embaralha a lista. A ordem dos
  exercícios importa, então replicamos o que o ``createList`` faz: um ``sort``
  inteiro decrescente por item.
* O Keep não guarda metadados nossos na nota, então o vínculo
  ``external_id -> id da nota`` fica num mapa local, em ``.state/``.
"""

import asyncio
import json
import random
from pathlib import Path
from typing import Any, Protocol

import gkeepapi
from gkeepapi.node import List as KeepList

from ..config import STATE_DIR
from ..keep_auth import KeepCredentials
from ..models import ChecklistNote
from .base import MARKER, Action, NoteDestination, NoteResult

NOTE_MAP = STATE_DIR / "keep_notes.json"
STATE_CACHE = STATE_DIR / "keep_state.json"
NOTE_URL = "https://keep.google.com/#NOTE/{}"


class KeepClient(Protocol):
    """Só o que usamos do ``gkeepapi.Keep`` — permite injetar um fake nos testes."""

    def authenticate(
        self,
        email: str,
        master_token: str,
        state: dict[str, Any] | None = ...,
        sync: bool = ...,
        device_id: str | None = ...,
    ) -> None: ...

    def get(self, node_id: str) -> Any: ...

    def createList(
        self, title: str | None = ..., items: list[tuple[str, bool]] | None = ...
    ) -> Any: ...

    def sync(self, resync: bool = ...) -> None: ...

    def dump(self) -> dict[str, Any]: ...

    def findLabel(self, query: str, create: bool = ...) -> Any: ...

    def find(self, labels: list[Any] | None = ..., trashed: bool | None = ...) -> Any: ...


class KeepDestination(NoteDestination):
    """Cria/atualiza uma nota de checkboxes por treino.

    Ao atualizar, os itens que continuam existindo mantêm o estado marcado —
    sincronizar no meio do treino não apaga o que já foi feito.
    """

    name = "keep"

    def __init__(self, credentials: KeepCredentials, *, client: KeepClient | None = None) -> None:
        self._credentials = credentials
        self._client = client
        self._authenticated = client is not None
        self._note_ids: dict[str, str] = _load_note_map()

    # ------------------------------------------------------------------ auth

    async def _keep(self) -> KeepClient:
        if self._client is None:
            self._client = gkeepapi.Keep()
        if not self._authenticated:
            await asyncio.to_thread(self._authenticate)
            self._authenticated = True
        return self._client

    def _authenticate(self) -> None:
        assert self._client is not None
        # O estado em cache evita rebaixar a conta inteira a cada execução.
        self._client.authenticate(
            self._credentials.email,
            self._credentials.master_token,
            state=_load_json(STATE_CACHE),
            device_id=self._credentials.device_id,
        )

    # ---------------------------------------------------------------- upsert

    async def upsert(self, note: ChecklistNote) -> NoteResult:
        return (await self.upsert_all([note]))[0]

    async def upsert_all(self, notes: list[ChecklistNote]) -> list[NoteResult]:
        keep = await self._keep()
        applied = await asyncio.to_thread(self._apply_all, keep, notes)
        # Um sync só para o lote — e antes de montar as URLs, que dependem do
        # server_id que o Keep atribui na subida.
        await asyncio.to_thread(self._flush)
        return [NoteResult(note.title, action, _url(node)) for note, action, node in applied]

    def _apply_all(
        self, keep: KeepClient, notes: list[ChecklistNote]
    ) -> list[tuple[ChecklistNote, Action, KeepList]]:
        return [(note, *self._apply(keep, note)) for note in notes]

    def _apply(self, keep: KeepClient, note: ChecklistNote) -> tuple[Action, KeepList]:
        wanted = [item.text for item in note.items]
        existing = self._find_existing(keep, note)

        if existing is None:
            created: KeepList = keep.createList(note.title, [(text, False) for text in wanted])
            self._mark(keep, created)
            if note.external_id:
                self._note_ids[note.external_id] = created.id
            return Action.CREATED, created

        self._mark(keep, existing)
        if [item.text for item in existing.items] == wanted and existing.title == note.title:
            return Action.UNCHANGED, existing

        _rewrite_items(existing, note.title, wanted)
        return Action.UPDATED, existing

    @staticmethod
    def _mark(keep: KeepClient, node: KeepList) -> None:
        """Cola o label ``mfit2keep`` na nota.

        É o que autoriza `limpar` a apagá-la depois: sem o label, a nota é do
        usuário e o app não encosta nela.
        """
        label = keep.findLabel(MARKER, create=True)
        if label is not None and node.labels.get(label.id) is None:
            node.labels.add(label)

    def _find_existing(self, keep: KeepClient, note: ChecklistNote) -> KeepList | None:
        node_id = self._note_ids.get(note.external_id or "")
        if not node_id:
            return None
        node = keep.get(node_id)
        # Nota apagada na mão: esquecemos o vínculo e criamos outra.
        if node is None or node.trashed or node.deleted:
            return None
        return node if isinstance(node, KeepList) else None

    # ----------------------------------------------------------------- purge

    async def purge(self, *, archive: bool = False) -> list[NoteResult]:
        keep = await self._keep()
        results = await asyncio.to_thread(self._purge_sync, keep, archive)
        await asyncio.to_thread(self._flush)
        return results

    def _purge_sync(self, keep: KeepClient, archive: bool) -> list[NoteResult]:
        label = keep.findLabel(MARKER)
        if label is None:
            return []

        results: list[NoteResult] = []
        # O filtro por label é a garantia: nota sem o label nunca entra na lista.
        for node in list(keep.find(labels=[label.id], trashed=False)):
            if archive:
                node.archived = True
                action = Action.ARCHIVED
            else:
                node.trash()
                action = Action.TRASHED
                self._forget(node.id)
            results.append(NoteResult(node.title, action, _url(node)))
        return results

    def _forget(self, node_id: str) -> None:
        """Solta o vínculo para que um `sync` futuro crie uma nota nova."""
        for external_id, mapped in list(self._note_ids.items()):
            if mapped == node_id:
                del self._note_ids[external_id]

    # ----------------------------------------------------------------- close

    async def aclose(self) -> None:
        return None

    def _flush(self) -> None:
        assert self._client is not None
        self._client.sync()
        _save_json(STATE_CACHE, self._client.dump())
        _save_json(NOTE_MAP, self._note_ids)


def _rewrite_items(node: KeepList, title: str, wanted: list[str]) -> None:
    """Reescreve a lista preservando o que já estava marcado.

    O ``sort`` decrescente e explícito é o que garante a ordem: sem ele o
    ``add()`` usa um valor aleatório e a lista sai embaralhada no relógio.
    """
    checked_before = {item.text: item.checked for item in node.items}

    for item in list(node.items):
        item.delete()

    sort = random.randint(1000000000, 9999999999)
    for text in wanted:
        node.add(text, checked_before.get(text, False), sort)
        sort -= KeepList.SORT_DELTA

    node.title = title


def _url(node: Any) -> str | None:
    server_id = getattr(node, "server_id", None)
    if server_id:
        return NOTE_URL.format(server_id)
    node_id = getattr(node, "id", None)
    return str(node_id) if node_id else None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(0o600)


def _load_note_map() -> dict[str, str]:
    loaded = _load_json(NOTE_MAP) or {}
    return {str(k): str(v) for k, v in loaded.items()}

"""Casa itens antigos com novos ao ressincronizar, sem perder o que foi marcado.

O texto do item é a linha inteira renderizada ("3. Supino — 4x10 · ↺60s"), e ela
muda por motivos que não deveriam zerar o checkbox:

* o treinador remove um exercício e todos os seguintes são renumerados;
* a carga ou o intervalo prescrito muda;
* o usuário roda com ``--sem-numerar``.

Por isso o casamento usa uma *chave*: o nome do exercício, extraído da linha.
Dois itens com a mesma chave (drop-set, série repetida no fim da ficha) são
consumidos em ordem, então o segundo não herda a marca do primeiro.
"""

import re
from collections import defaultdict, deque

#: "12. ", "3. " — numeração adicionada pelo render.
_NUMBER_PREFIX = re.compile(r"^\s*\d+\.\s*")
#: "↳ " — marca de continuação de série combinada.
_CONTINUATION = re.compile(r"^\s*↳\s*")
#: " — 4x10 · ↺60s" — os detalhes vêm depois do travessão.
_DETAIL_SEPARATOR = " — "


def item_key(text: str) -> str:
    """Parte estável da linha: o nome do exercício, normalizado."""
    # O render escreve "↳ 2. Nome": a seta vem antes do número, então ela sai primeiro.
    stripped = _NUMBER_PREFIX.sub("", _CONTINUATION.sub("", text)).strip()
    name = stripped.split(_DETAIL_SEPARATOR, 1)[0]
    return name.casefold().strip() or stripped.casefold()


class CheckedState:
    """Guarda o estado marcado de uma lista e o devolve por chave, em ordem."""

    def __init__(self, items: list[tuple[str, bool]]) -> None:
        self._by_key: defaultdict[str, deque[bool]] = defaultdict(deque)
        for text, checked in items:
            self._by_key[item_key(text)].append(checked)

    def take(self, text: str) -> bool:
        """Consome o estado do próximo item com essa chave.

        Consumir (em vez de só consultar) é o que evita que dois exercícios de
        mesmo nome recebam ambos a marca de um só.
        """
        queue = self._by_key.get(item_key(text))
        if not queue:
            return False
        return queue.popleft()

"""Modelo de domínio — independente do formato da API do MFIT e do destino da nota."""

from dataclasses import dataclass, field

type Items = list["ChecklistItem"]


@dataclass(frozen=True, slots=True)
class Exercise:
    """Um exercício dentro de um treino."""

    name: str
    sets: str | None = None
    reps: str | None = None
    load: str | None = None
    rest: str | None = None
    notes: str | None = None
    #: Exercícios da mesma série combinada (bi-set, tri-set) compartilham a chave.
    group: str | None = None

    def summary(self) -> str:
        """Linha curta o suficiente para caber na tela de um smartwatch."""
        detail = " x ".join(part for part in (self.sets, self.reps) if part)
        extras = [part for part in (detail, self.load, self.rest) if part]
        return f"{self.name} — {' | '.join(extras)}" if extras else self.name


@dataclass(frozen=True, slots=True)
class Workout:
    """Um treino (ex.: "Treino A - Peito e Tríceps")."""

    id: str
    name: str
    exercises: list[Exercise] = field(default_factory=list)
    letter: str | None = None
    description: str | None = None

    @property
    def title(self) -> str:
        if self.letter and not self.name.strip().upper().startswith(self.letter.upper()):
            return f"{self.letter} — {self.name}"
        return self.name


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    text: str
    checked: bool = False
    #: Itens filhos viram sub-checkboxes onde o destino suportar.
    children: Items = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ChecklistNote:
    """Nota com checkboxes, pronta para ser enviada a qualquer destino."""

    title: str
    items: list[ChecklistItem]
    #: Identificador estável derivado do treino, usado para atualizar em vez de duplicar.
    external_id: str | None = None

    def as_text(self) -> str:
        """Fallback em texto para destinos que não têm checkbox nativo."""
        lines = [self.title, ""]
        for item in self.items:
            lines.append(f"[{'x' if item.checked else ' '}] {item.text}")
            lines.extend(
                f"    [{'x' if child.checked else ' '}] {child.text}" for child in item.children
            )
        return "\n".join(lines)

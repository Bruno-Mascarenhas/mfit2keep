"""Modelo de domínio — independente do formato da API do MFIT e do destino da nota."""

import re
from dataclasses import dataclass, field

#: Letra do dia como prefixo isolado: "A - Peito", "C: Perna", "D) Ombro".
#: Os separadores aceitos incluem hifen, en dash (U+2013) e em dash (U+2014),
#: escapados para nao deixar caractere ambiguo no fonte.
_LETTER_PREFIX = re.compile("^([A-Z])\\s*[-\\u2013\\u2014:.)]")


@dataclass(frozen=True, slots=True)
class Exercise:
    """Um exercício dentro de um treino."""

    name: str
    reps: str | None = None
    load: str | None = None
    rest: str | None = None
    notes: str | None = None
    #: Exercícios da mesma série combinada (bi-set, tri-set) compartilham a chave.
    group: str | None = None


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
        """Nome do treino com a letra do dia na frente, sem duplicar.

        A letra só é omitida quando já aparece como prefixo isolado ("A - Peito").
        Um nome que apenas começa com a mesma letra ("Abdominal") continua
        recebendo o prefixo — do contrário o dia sumiria do título.
        """
        name = self.name.strip()
        if not self.letter:
            return name

        letter = self.letter.upper()
        match = _LETTER_PREFIX.match(name.upper())
        if name.upper() == letter or (match and match.group(1) == letter):
            return name
        return f"{self.letter} — {name}"


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    text: str
    checked: bool = False


@dataclass(frozen=True, slots=True)
class ChecklistNote:
    """Nota com checkboxes, pronta para ser enviada a qualquer destino."""

    title: str
    items: list[ChecklistItem]
    #: Identificador estável derivado do treino, usado para atualizar em vez de duplicar.
    external_id: str | None = None

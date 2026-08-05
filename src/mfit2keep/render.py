"""Transforma um :class:`Workout` na nota com checkboxes que vai para o destino.

O alvo é a tela de um smartwatch: uma linha por exercício, curta, com o nome
primeiro (é o que aparece quando o texto é truncado).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from mfit2keep.models import ChecklistItem, ChecklistNote, Exercise, Workout
from mfit2keep.muscles import DEFAULT_EMOJI, is_cardio, workout_emoji


class TitleStyle(StrEnum):
    """Que emoji abre o título da nota."""

    #: O mesmo halteres em todos os dias.
    CLASSICO = "classico"
    #: Um emoji por grupo muscular — o dia se reconhece sem ler.
    MUSCULOS = "musculos"
    #: Nenhum emoji, só o título.
    CLEAN = "clean"


class RepsMode(StrEnum):
    """O que fazer quando a prescrição vem em faixa ("3 a 4x de 12 a 15")."""

    #: Como o MFIT mandou.
    MFIT = "mfit"
    #: Sempre o piso — o combinado, o que cabe na tela.
    MIN = "min"
    #: Sempre o teto — para quem trata a faixa como meta.
    MAX = "max"


#: Número colado numa letra é unidade, não a ponta de uma faixa: em
#: "3x12 a 40kg" o 40 é a carga, e trocar o 12 por ele apagaria a prescrição.
#: Não vale para a contagem de séries, onde a letra colada é o "x" de "3 a 4x".
_NOT_A_UNIT = r"(?![^\W\d_])"
#: "12-10-8" é pirâmide: uma sequência de séries, não uma faixa. Tratar aquilo
#: como faixa apagaria um degrau do treino.
_NOT_A_SEQUENCE = r"(?!\s*[-\u2013\u2014]\s*\d)"


def _range(name: str, guard: str = "") -> str:
    """A segunda ponta de uma faixa: "a 4", "-15", "até 20".

    O "a" só conta quando vem um número depois — senão "3x12 abdominais"
    perderia a palavra. Alternativas mais longas primeiro, para "ate" não parar
    no "a". Os travessões vão escapados (``\\u2013``, ``\\u2014``) para não
    deixar caractere ambíguo no fonte, como no resto do projeto.
    """
    return (
        rf"(?:(?:\s*(?:até|ate|a)\s*(?P<{name}>\d++)"
        rf"|\s*[-\u2013\u2014]\s*(?P<{name}_traco>\d++))"
        rf"{_NOT_A_SEQUENCE}{guard})?"
    )


def _top_of(match: re.Match[str], name: str) -> str | None:
    """A ponta de cima, tenha ela vindo pelo "a" ou pelo travessão."""
    top: str | None = match[name] or match[f"{name}_traco"]
    return top


#: "3 a 4x de 12 a 15" → séries, repetições e o que vier depois ("3T", "ISO").
#: A barra fica de fora de propósito: "3x12/10/8" é drop-set (uma sequência de
#: séries), não faixa — encurtar aquilo seria apagar treino.
_SETS_AND_REPS = re.compile(
    rf"^\s*(?P<series>\d++){_range('series_top')}"
    rf"\s*[x\u00d7]\s*(?:de\s*)?"
    rf"(?P<reps>\d++){_range('reps_top', _NOT_A_UNIT)}(?P<extra>.*)$",
    re.IGNORECASE,
)

#: Aeróbio: "35", "35 a 40", "30,5" — número solto, que na ficha é tempo.
_DURATION = re.compile(
    rf"^\s*(?P<minutes>\d++(?:[.,]\d++)?){_range('minutes_top', _NOT_A_UNIT)}\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderOptions:
    #: Emoji do título — veja :class:`TitleStyle`.
    style: TitleStyle = TitleStyle.CLASSICO
    #: O que fazer com a faixa de repetições — veja :class:`RepsMode`.
    reps: RepsMode = RepsMode.MFIT
    #: Inclui a carga prescrita. No MFIT ela quase sempre vem "0" — e aí o
    #: parser a descarta, então a linha não ganha ruído por estar ligada.
    include_load: bool = True
    #: Inclui o intervalo de descanso.
    include_rest: bool = True
    #: Numera os exercícios (1., 2., ...) para achar o lugar na lista rápido.
    numbered: bool = True
    #: Corta a linha nesse tamanho; 0 desliga.
    max_line_length: int = 0


def watch_reps(exercise: Exercise, mode: RepsMode = RepsMode.MFIT) -> str | None:
    """Repetições como cabem no relógio, e o aeróbio sempre em minutos.

    A faixa é do professor, mas a linha é da tela: "3 a 4x de 12 a 15" ocupa o
    dobro de "3x12" e diz a mesma coisa para quem está no meio da série. Qual
    ponta vale é escolha de quem treina — daí o :class:`RepsMode`.

    Os minutos do aeróbio não são preferência: ali o campo de repetições traz
    tempo, e "35" sem unidade é só um número solto na tela.
    """
    if not exercise.reps:
        return exercise.reps

    # Aeróbio e faixa não são caminhos exclusivos: o circuito que o professor
    # catalogou como aeróbio (corda naval, burpee) ainda vem em séries, e ali a
    # ponta escolhida vale como em qualquer outro exercício. Escolher a ponta
    # antes é seguro porque os dois padrões são disjuntos — o de séries exige o
    # "x", o de duração exige o número sozinho —, então o " min" nunca se perde.
    picked = _pick_of_range(exercise.reps, mode)
    return _as_minutes(picked, mode) if is_cardio(exercise) else picked


def _pick_of_range(reps: str, mode: RepsMode) -> str:
    if mode is RepsMode.MFIT:
        return reps

    match = _SETS_AND_REPS.match(reps)
    if match is None:
        return reps

    series = _end(match["series"], _top_of(match, "series_top"), mode)
    repetitions = _end(match["reps"], _top_of(match, "reps_top"), mode)
    # ``extra`` sai inteiro e sem toque: "+ 20 ISO", "3T" e "halteres" são
    # instrução do treinador, e adivinhar o que significam sairia caro.
    return f"{series}x{repetitions}{match['extra']}"


def _as_minutes(reps: str, mode: RepsMode) -> str:
    """No aeróbio o campo de repetições é tempo: "35" quer dizer 35 minutos."""
    match = _DURATION.match(reps)
    if match is None:
        return reps
    if mode is RepsMode.MFIT:
        return f"{reps.strip()} min"
    return f"{_end(match['minutes'], _top_of(match, 'minutes_top'), mode)} min"


def _end(first: str, second: str | None, mode: RepsMode) -> str:
    """A ponta escolhida da faixa, tolerando quem escreveu na ordem inversa."""
    if second is None:
        return first
    low, high = sorted((first, second), key=lambda value: float(value.replace(",", ".")))
    return high if mode is RepsMode.MAX else low


def exercise_line(exercise: Exercise, options: RenderOptions) -> str:
    parts: list[str] = []
    if reps := watch_reps(exercise, options.reps):
        parts.append(reps)
    if options.include_load and exercise.load:
        parts.append(exercise.load)
    if options.include_rest and exercise.rest:
        parts.append(f"↺{exercise.rest}")

    line = f"{exercise.name} — {' · '.join(parts)}" if parts else exercise.name
    if exercise.notes:
        line = f"{line} ({exercise.notes})"
    if options.max_line_length and len(line) > options.max_line_length:
        line = line[: options.max_line_length - 1].rstrip() + "…"
    return line


def title_emoji(workout: Workout, style: TitleStyle) -> str:
    match style:
        case TitleStyle.CLEAN:
            return ""
        case TitleStyle.MUSCULOS:
            return workout_emoji(workout)
        case TitleStyle.CLASSICO:
            return DEFAULT_EMOJI


def note_title(workout: Workout, options: RenderOptions | None = None) -> str:
    options = options or RenderOptions()
    return f"{title_emoji(workout, options.style)} {workout.title}".strip()


def workout_to_note(workout: Workout, options: RenderOptions | None = None) -> ChecklistNote:
    options = options or RenderOptions()

    items: list[ChecklistItem] = []
    previous_group: str | None = None
    for position, exercise in enumerate(workout.exercises, start=1):
        text = exercise_line(exercise, options)
        if options.numbered:
            text = f"{position}. {text}"
        # Série combinada: marca a continuação para não parecer exercício solto.
        if exercise.group and exercise.group == previous_group:
            text = f"↳ {text}"
        previous_group = exercise.group
        items.append(ChecklistItem(text=text))

    return ChecklistNote(
        title=note_title(workout, options), items=items, external_id=f"mfit:{workout.id}"
    )


def routine_to_notes(
    workouts: list[Workout], options: RenderOptions | None = None
) -> list[ChecklistNote]:
    return [workout_to_note(workout, options) for workout in workouts]

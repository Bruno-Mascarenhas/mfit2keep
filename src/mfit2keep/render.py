"""Transforma um :class:`Workout` na nota com checkboxes que vai para o destino.

O alvo é a tela de um smartwatch: uma linha por exercício, curta, com o nome
primeiro (é o que aparece quando o texto é truncado).
"""

from dataclasses import dataclass

from .models import ChecklistItem, ChecklistNote, Exercise, Workout


@dataclass(frozen=True)
class RenderOptions:
    #: Prefixo do título da nota — serve de âncora para achar/atualizar depois.
    title_prefix: str = "🏋️"
    #: Inclui carga prescrita (quase sempre "0" no MFIT, daí vir desligado).
    include_load: bool = True
    #: Inclui o intervalo de descanso.
    include_rest: bool = True
    #: Numera os exercícios (1., 2., ...) para achar o lugar na lista rápido.
    numbered: bool = True
    #: Corta a linha nesse tamanho; 0 desliga.
    max_line_length: int = 0


def exercise_line(exercise: Exercise, options: RenderOptions) -> str:
    parts: list[str] = []
    if exercise.reps:
        parts.append(exercise.reps)
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

    title = f"{options.title_prefix} {workout.title}".strip()
    return ChecklistNote(title=title, items=items, external_id=f"mfit:{workout.id}")


def routine_to_notes(
    workouts: list[Workout], options: RenderOptions | None = None
) -> list[ChecklistNote]:
    return [workout_to_note(w, options) for w in workouts]

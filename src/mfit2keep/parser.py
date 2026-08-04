"""Traduz os payloads da API do MFIT para o modelo de domínio.

Formato observado na API (rotina 36318803):

    GET /v2/client/workout/?id=<rotinaId>
        {"id", "nome", "workouts": [{"id", "nome", "diaTipo", "obs", ...}]}

    GET /v2/client/workout/session?id=<diaId>
        {"id", "nome", "obs",
         "exercs": [{"id", "order", "type",
                     "exercises": [{"id", "name", "isCombinado",
                                    "series": [{"repeticao", "carga",
                                                "intervalText", "obs", ...}]}]}]}

Cada item de ``exercs`` é um *grupo*: com mais de um exercício dentro, trata-se
de série combinada (bi-set, tri-set).
"""

from typing import Any

from .models import Exercise, Workout

#: ``carga`` vem como "0" quando o professor não prescreveu peso.
_EMPTY_LOAD = {"", "0", "0.0", "-"}


def day_letter(dia_tipo: Any) -> str | None:
    """diaTipo 1..26 -> "A".."Z". Fora disso, sem letra."""
    try:
        index = int(dia_tipo)
    except TypeError, ValueError:
        return None
    return chr(ord("A") + index - 1) if 1 <= index <= 26 else None


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _load(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    if text.lower() in _EMPTY_LOAD:
        return None
    return f"{text}kg" if text.replace(",", ".").replace(".", "").isdigit() else text


def _rest(serie: dict[str, Any]) -> str | None:
    """Cardio vem com ``intervalText`` "0" — sem intervalo, não vale poluir a nota."""
    text = _clean(serie.get("intervalText"))
    if not text:
        seconds = serie.get("intervalSeconds") or serie.get("intervalo")
        text = str(int(seconds)) if seconds else None
    if not text or text in _EMPTY_LOAD:
        return None
    return f"{text}s" if text.isdigit() else text


def _reps(serie: dict[str, Any]) -> str | None:
    """``repeticao`` costuma já vir como "3x12 a 15"; cardio usa tempo/distância."""
    for key in ("repeticao", "tempo", "distancia", "pace", "velocidade"):
        if text := _clean(serie.get(key)):
            return text
    return None


def _join(parts: list[str | None], sep: str) -> str | None:
    seen = [p for p in parts if p]
    if not seen:
        return None
    # Séries idênticas (o caso comum) viram uma só entrada.
    unique = list(dict.fromkeys(seen))
    return sep.join(unique)


def _column(rows: list[tuple[str | None, ...]], index: int) -> str | None:
    """Formata uma coluna das séries preservando a leitura posicional.

    Deduplicar cada campo por conta própria desalinha a ficha: com duas séries
    de repetições diferentes e a mesma carga, "12 / 10" ficaria ao lado de um
    único valor de carga sem dizer a qual série ele pertence. Aqui a coluna só
    encolhe quando é constante — aí mostrar uma vez é inequívoco. Do contrário
    ela mantém uma entrada por série, com "—" nos buracos.
    """
    values = [row[index] for row in rows]
    if not any(values):
        return None
    if len(set(values)) == 1:
        return values[0]
    return " / ".join(value or "—" for value in values)


def parse_exercise(raw: dict[str, Any], *, group: str | None = None) -> Exercise:
    series: list[dict[str, Any]] = raw.get("series") or []
    rows: list[tuple[str | None, ...]] = [
        (_reps(s), _load(s.get("carga")), _rest(s)) for s in series
    ]
    # Séries idênticas (o caso comum) viram uma linha só, tudo-ou-nada.
    if len(set(rows)) == 1:
        rows = rows[:1]

    return Exercise(
        name=_clean(raw.get("name")) or "Exercício sem nome",
        reps=_column(rows, 0),
        load=_column(rows, 1),
        rest=_column(rows, 2),
        notes=_join([_clean(s.get("obs")) for s in series], " · "),
        group=group,
    )


def parse_session(session: dict[str, Any], *, day: dict[str, Any] | None = None) -> Workout:
    """Converte o JSON de um dia de treino em :class:`Workout`."""
    day = day or {}
    groups: list[dict[str, Any]] = session.get("exercs") or []
    groups = sorted(groups, key=lambda g: g.get("order", 0))

    exercises: list[Exercise] = []
    for index, group in enumerate(groups):
        members: list[dict[str, Any]] = group.get("exercises") or []
        # Grupo com mais de um exercício = série combinada; marcamos para o render.
        key = f"g{index}" if len(members) > 1 else None
        members = sorted(members, key=lambda e: e.get("ordenacao", 0))
        exercises.extend(parse_exercise(member, group=key) for member in members)

    name = _clean(session.get("nome")) or _clean(day.get("nome")) or "Treino"
    return Workout(
        id=str(session.get("id") or day.get("id") or ""),
        name=name,
        letter=day_letter(day.get("diaTipo") if day else session.get("diaTipo")),
        description=_clean(session.get("obs")) or _clean(day.get("obs")),
        exercises=exercises,
    )


def parse_routine(routine: dict[str, Any], sessions: dict[str, dict[str, Any]]) -> list[Workout]:
    """Junta a rotina com as sessões já buscadas, preservando a ordem dos dias."""
    days: list[dict[str, Any]] = routine.get("workouts") or []
    days = sorted(days, key=lambda d: (d.get("diaTipo", 0), d.get("ordenacao", 0)))

    workouts: list[Workout] = []
    for day in days:
        session = sessions.get(str(day.get("id")))
        if session is None:
            continue
        workouts.append(parse_session(session, day=day))
    return workouts

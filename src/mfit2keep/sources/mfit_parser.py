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

from mfit2keep.models import Exercise, Workout

#: ``carga`` vem como "0" quando o professor não prescreveu peso.
_EMPTY_LOAD = {"", "0", "0.0", "-"}

#: Uma série vira uma linha (repetições, carga, intervalo); as colunas abaixo
#: dão nome aos índices para não precisar decorar a ordem da tupla.
type SeriesRow = tuple[str | None, str | None, str | None]
REPS_COLUMN = 0
LOAD_COLUMN = 1
REST_COLUMN = 2


def _as_whole_number(value: Any) -> str | None:
    """Número inteiro como texto, ou ``None`` se não for número."""
    try:
        return str(int(value))
    except TypeError, ValueError:
        return None


def _sort_key(value: Any) -> tuple[int, float]:
    """Ordena tolerando ``null`` e texto no campo de ordem.

    A API já mandou ``diaTipo`` nulo; comparar ``None`` com ``int`` derrubaria
    o sync inteiro, e a ordem dos dias não vale um comando abortado. O que não
    é número vai para o fim, mantendo a ordem relativa.
    """
    try:
        return (0, float(value))
    except TypeError, ValueError:
        return (1, 0.0)


def day_letter(dia_tipo: Any) -> str | None:
    """diaTipo 1..26 -> "A".."Z". Fora disso, sem letra."""
    try:
        index = int(dia_tipo)
    except TypeError, ValueError:
        return None
    return chr(ord("A") + index - 1) if 1 <= index <= 26 else None


def _clean(value: Any) -> str | None:
    """Normaliza texto da API para caber numa linha de checkbox.

    A quebra de linha some de propósito: no Markdown ela cortaria o item ao
    meio, e no Keep viraria um item novo sem checkbox — em ambos os casos a
    marcação do usuário se perderia na ressincronização seguinte.
    """
    if value is None:
        return None
    text = " ".join(str(value).split())
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
        # O campo devia ser numérico, mas a API já mandou texto ("1:30") —
        # nesse caso vale mais mostrar o que veio do que derrubar o sync.
        seconds = serie.get("intervalSeconds") or serie.get("intervalo")
        text = _as_whole_number(seconds) or _clean(seconds)
    if not text or text in _EMPTY_LOAD:
        return None
    return f"{text}s" if text.isdigit() else text


def _reps(serie: dict[str, Any]) -> str | None:
    """``repeticao`` costuma já vir como "3x12 a 15"; cardio usa tempo/distância."""
    for key in ("repeticao", "tempo", "distancia", "pace", "velocidade"):
        if text := _clean(serie.get(key)):
            return text
    return None


def _join(parts: list[str | None], separator: str) -> str | None:
    """Junta texto livre de várias séries, sem repetir o que é igual."""
    present = [part for part in parts if part]
    if not present:
        return None
    return separator.join(dict.fromkeys(present))


def _column(series_rows: list[SeriesRow], column: int) -> str | None:
    """Formata uma coluna das séries preservando a leitura posicional.

    Deduplicar cada campo por conta própria desalinha a ficha: com duas séries
    de repetições diferentes e a mesma carga, "12 / 10" ficaria ao lado de um
    único valor de carga sem dizer a qual série ele pertence. Aqui a coluna só
    encolhe quando é constante — aí mostrar uma vez é inequívoco. Do contrário
    ela mantém uma entrada por série, com "—" nos buracos.
    """
    values = [row[column] for row in series_rows]
    if not any(values):
        return None
    if len(set(values)) == 1:
        return values[0]
    return " / ".join(value or "—" for value in values)


def _muscle_group(raw_exercise: dict[str, Any]) -> str | None:
    """Grupo muscular do exercício, como o MFIT o classifica.

    ``exerciseGroup`` é a resposta boa ("Peitoral", "Dorsal", "Aeróbio"), mas
    às vezes ele descreve o material ("Elásticos e Faixas"). Quando ele falta,
    a categoria ainda salva o caso que mais importa: o aeróbio, cujo campo de
    repetições traz minutos.
    """
    raw_group = raw_exercise.get("exerciseGroup")
    if isinstance(raw_group, dict) and (name := _clean(raw_group.get("nome"))):
        return name

    raw_category = raw_exercise.get("exerciseCategory")
    if isinstance(raw_category, dict) and _clean(raw_category.get("name")) == "aerobic":
        return "Aeróbio"
    return None


def parse_exercise(raw_exercise: dict[str, Any], *, combined_group: str | None = None) -> Exercise:
    all_series: list[dict[str, Any]] = raw_exercise.get("series") or []
    series_rows: list[SeriesRow] = [
        (_reps(series), _load(series.get("carga")), _rest(series)) for series in all_series
    ]
    # Séries idênticas (o caso comum) viram uma linha só, tudo-ou-nada.
    if len(set(series_rows)) == 1:
        series_rows = series_rows[:1]

    return Exercise(
        name=_clean(raw_exercise.get("name")) or "Exercício sem nome",
        reps=_column(series_rows, REPS_COLUMN),
        load=_column(series_rows, LOAD_COLUMN),
        rest=_column(series_rows, REST_COLUMN),
        notes=_join([_clean(series.get("obs")) for series in all_series], " · "),
        group=combined_group,
        muscle_group=_muscle_group(raw_exercise),
    )


def parse_session(session: dict[str, Any], *, day: dict[str, Any] | None = None) -> Workout:
    """Converte o JSON de um dia de treino em :class:`Workout`."""
    day = day or {}
    raw_groups: list[dict[str, Any]] = session.get("exercs") or []
    raw_groups = sorted(raw_groups, key=lambda group: _sort_key(group.get("order", 0)))

    exercises: list[Exercise] = []
    for position, raw_group in enumerate(raw_groups):
        members: list[dict[str, Any]] = raw_group.get("exercises") or []
        # Grupo com mais de um exercício = série combinada; marcamos para o render.
        combined_group = f"g{position}" if len(members) > 1 else None
        members = sorted(members, key=lambda member: _sort_key(member.get("ordenacao", 0)))
        exercises.extend(
            parse_exercise(member, combined_group=combined_group) for member in members
        )

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
    days = sorted(
        days, key=lambda day: (_sort_key(day.get("diaTipo", 0)), _sort_key(day.get("ordenacao", 0)))
    )

    workouts: list[Workout] = []
    for day in days:
        session = sessions.get(str(day.get("id")))
        if session is None:
            continue
        workouts.append(parse_session(session, day=day))
    return workouts

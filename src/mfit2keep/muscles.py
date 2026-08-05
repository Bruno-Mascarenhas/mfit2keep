"""O que o treino trabalha — e o emoji que diz isso de relance.

Na lista do relógio o título é quase tudo que se vê. Com o mesmo 🏋️ em todos os
dias, achar o treino de hoje exige ler cada linha; com um emoji por grupo
muscular, o dia certo salta aos olhos antes da leitura.

O vocabulário é o português que a API do MFIT devolve, casado por radical e sem
acento: ``costa`` pega "Costas", ``abdomin`` pega "Abdominais". O mesmo mapa
serve para saber que um exercício é aeróbio — e que as "repetições" dele são,
na verdade, minutos.
"""

import re
import unicodedata
from collections import Counter

from mfit2keep.models import Exercise, Workout

#: Emoji de quem não casou com nada: é treino, só não sabemos de quê. É o
#: único do conjunto que depende do seletor de variação (U+FE0F) para sair
#: colorido — os outros são de Emoji 11.0 ou anterior, coloridos por padrão,
#: que é o piso seguro de qualquer Wear OS.
DEFAULT_EMOJI = "🏋️"
#: Aeróbio — o único grupo que também muda a unidade das repetições.
CARDIO_EMOJI = "🏃"
#: Dois bastam para "Peito e Tríceps"; o terceiro só rouba espaço da tela.
MAX_EMOJIS = 2

#: Emoji por grupo, com os radicais que o denunciam. A ordem aqui não importa:
#: quando o nome casa com mais de um grupo, quem manda é a posição no texto
#: ("Peito e Tríceps" sai 🐦💪, "Tríceps e Peito" sai 💪🐦).
_MUSCLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("💪", ("bicep", "tricep", "braco", "antebraco", "rosca", "supinacao")),
    # Costas de gorila, peito de pombo: a imagem é da academia, não da anatomia.
    ("🦍", ("costa", "dorsa", "remada", "puxada", "pulldown", "pullover", "trapezio")),
    (
        "🦵",
        (
            "perna",
            "inferior",
            "quadricep",
            "posterior",
            "isquiotibia",
            "coxa",
            "panturrilha",
            "gemeos",
            "agachamento",
            "leg",
            "aducao",
            "abducao",
            "adutor",
            "abdutor",
        ),
    ),
    ("🍑", ("gluteo", "quadril")),
    ("🙌", ("ombro", "deltoid", "elevacao lateral", "elevacao frontal")),
    ("🐦", ("peito", "supino", "crucifixo", "crossover")),
    ("🔥", ("abdomin", "abdome", "core", "prancha", "obliqu")),
    (
        CARDIO_EMOJI,
        (
            "aerobi",
            "cardio",
            "esteira",
            "corrida",
            "caminhada",
            "bike",
            "bicicleta",
            "spinning",
            "eliptico",
            "transport",
            "escada",
            "ergometr",
        ),
    ),
    ("🧘", ("alongamento", "mobilidade", "yoga", "pilates", "flexibilidade")),
)

#: Grupos que fecham o treino sem defini-lo: quase todo dia termina em abdômen
#: e esteira, então eles só viram o emoji do título quando não há mais nada.
_ACCESSORY = frozenset({"🔥", CARDIO_EMOJI})

#: ``\b`` na frente e radical solto atrás: "ombro" pega "Ombros", mas "leg" não
#: pode pegar o "leg" do meio de outra palavra.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (emoji, re.compile(r"\b(?:" + "|".join(map(re.escape, stems)) + r")"))
    for emoji, stems in _MUSCLES
)


#: Nomes em que o radical curto engana: o músculo da coxa também se chama
#: "bíceps" e o da panturrilha, "tríceps" — e nenhum dos dois é braço. Trocar
#: o nome inteiro antes de procurar é mais simples que dar prioridade a uns
#: radicais sobre outros.
_TRAPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:bi|tri)ceps\s+(?:femoral|sural|crural)\w*"), "coxa"),
    (re.compile(r"\bdeltoide\w*\s+posterior\w*"), "ombro"),
)


def _plain(text: str) -> str:
    """Minúsculas e sem acento — "Bíceps" e "biceps" têm que casar igual."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    for trap, meaning in _TRAPS:
        plain = trap.sub(meaning, plain)
    return plain


def _emojis_in(text: str) -> list[str]:
    """Emojis dos grupos citados no texto, na ordem em que aparecem."""
    plain = _plain(text)
    found: list[tuple[int, str]] = []
    for emoji, pattern in _PATTERNS:
        if (match := pattern.search(plain)) is not None:
            found.append((match.start(), emoji))
    found.sort()
    return list(dict.fromkeys(emoji for _, emoji in found))


def exercise_emoji(exercise: Exercise) -> str | None:
    """Grupo de um exercício, pelo que a fonte declarou ou pelo nome.

    O grupo declarado vem primeiro por ser mais confiável, mas nem sempre é
    muscular ("Elásticos e Faixas") — aí o nome resolve.
    """
    for text in (exercise.muscle_group, exercise.name):
        if text and (found := _emojis_in(text)):
            return found[0]
    return None


def is_cardio(exercise: Exercise) -> bool:
    """Aeróbio — nele o campo de repetições traz minutos, não repetições."""
    return exercise_emoji(exercise) == CARDIO_EMOJI


def workout_emoji(workout: Workout) -> str:
    """Emoji (ou dois) do título, a partir do nome do dia ou dos exercícios."""
    found = _emojis_in(workout.name) or _dominant(workout.exercises)
    return "".join(found[:MAX_EMOJIS]) or DEFAULT_EMOJI


def _dominant(exercises: list[Exercise]) -> list[str]:
    """Grupos que mais aparecem na ficha — o socorro para "Treino A".

    Abdômen e aeróbio ficam de fora enquanto houver grupo principal: eles
    aparecem em todo dia da rotina e não distinguem nada.
    """
    counted: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for position, exercise in enumerate(exercises):
        if (emoji := exercise_emoji(exercise)) is not None:
            counted[emoji] += 1
            first_seen.setdefault(emoji, position)

    ranked = [emoji for emoji in counted if emoji not in _ACCESSORY] or list(counted)
    ranked.sort(key=lambda emoji: (-counted[emoji], first_seen[emoji]))
    return ranked

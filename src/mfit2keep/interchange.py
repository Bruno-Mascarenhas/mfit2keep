"""Formato neutro de treino: JSON que não pertence a nenhum serviço.

É o pivô da arquitetura. Exportar para cá tira os treinos do MFIT sem levar
junto o formato do MFIT; importar daqui alimenta o app sem nenhuma conta.

Serve a três usos concretos:

* **sair do MFIT** — exporta uma vez e siga a vida com o arquivo;
* **outra fonte** — qualquer app ou planilha que gere este JSON já funciona,
  sem escrever código Python;
* **teste e depuração** — reproduzir um treino sem tocar a rede.

O formato é versionado: ler um arquivo de versão futura falha com mensagem
clara em vez de interpretar campo errado em silêncio.
"""

from dataclasses import replace
from typing import Any

from mfit2keep.models import Exercise, Workout

#: Sobe quando um campo muda de significado ou some. Campo novo e opcional não sobe.
FORMAT_VERSION = 1
FORMAT_NAME = "mfit2keep/workouts"


class InterchangeError(ValueError):
    """O JSON não está no formato de treino esperado."""


def workouts_to_dict(workouts: list[Workout]) -> dict[str, Any]:
    """Serializa os treinos no formato neutro."""
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "workouts": [_workout_to_dict(workout) for workout in workouts],
    }


def workouts_from_dict(payload: dict[str, Any]) -> list[Workout]:
    """Lê o formato neutro, recusando o que não reconhece."""
    if payload.get("format") != FORMAT_NAME:
        raise InterchangeError(
            f"Arquivo não é um export do mfit2keep (format={payload.get('format')!r})."
        )

    version = payload.get("version")
    if version != FORMAT_VERSION:
        raise InterchangeError(
            f"Formato versão {version}, esperada {FORMAT_VERSION}. "
            "Atualize o mfit2keep ou exporte de novo."
        )

    raw_workouts = payload.get("workouts")
    if not isinstance(raw_workouts, list):
        raise InterchangeError("Campo 'workouts' ausente ou não é uma lista.")

    treinos = [_workout_from_dict(raw) for raw in raw_workouts]
    return _with_unique_ids(treinos)


def _with_unique_ids(treinos: list[Workout]) -> list[Workout]:
    """Garante um id distinto por treino, inventando quando o arquivo não traz.

    O id vira a chave que liga o treino à nota no destino. Num arquivo escrito
    à mão o campo costuma faltar, e sem isto todos os treinos ficariam com o
    mesmo id — o destino trataria os cinco dias como um só e quatro sumiriam.

    A derivação é pelo nome, e não pela posição, para que reordenar os dias no
    arquivo não desfaça o vínculo com as notas já criadas.
    """
    usados: set[str] = set()
    resultado: list[Workout] = []

    for posicao, treino in enumerate(treinos):
        identificador = treino.id or _slug(treino.name) or f"treino-{posicao + 1}"
        if identificador in usados:
            # Dois treinos com o mesmo nome e sem id: só a posição os separa.
            identificador = f"{identificador}-{posicao + 1}"
        usados.add(identificador)
        resultado.append(
            treino if treino.id == identificador else replace(treino, id=identificador)
        )
    return resultado


def _slug(nome: str) -> str:
    return "-".join(nome.casefold().split())


def _workout_to_dict(workout: Workout) -> dict[str, Any]:
    return {
        "id": workout.id,
        "name": workout.name,
        "letter": workout.letter,
        "description": workout.description,
        "exercises": [_exercise_to_dict(exercise) for exercise in workout.exercises],
    }


def _exercise_to_dict(exercise: Exercise) -> dict[str, Any]:
    return {
        "name": exercise.name,
        "reps": exercise.reps,
        "load": exercise.load,
        "rest": exercise.rest,
        "notes": exercise.notes,
        "group": exercise.group,
        "muscle_group": exercise.muscle_group,
    }


def _workout_from_dict(raw: Any) -> Workout:
    if not isinstance(raw, dict):
        raise InterchangeError(f"Treino deveria ser um objeto, veio {type(raw).__name__}.")

    raw_exercises = raw.get("exercises") or []
    if not isinstance(raw_exercises, list):
        raise InterchangeError(f"'exercises' de {raw.get('name')!r} não é uma lista.")

    return Workout(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or "Treino"),
        letter=_optional_text(raw.get("letter")),
        description=_optional_text(raw.get("description")),
        exercises=[_exercise_from_dict(item) for item in raw_exercises],
    )


def _exercise_from_dict(raw: Any) -> Exercise:
    if not isinstance(raw, dict):
        raise InterchangeError(f"Exercício deveria ser um objeto, veio {type(raw).__name__}.")

    name = _optional_text(raw.get("name"))
    if not name:
        raise InterchangeError("Exercício sem nome.")

    return Exercise(
        name=name,
        reps=_optional_text(raw.get("reps")),
        load=_optional_text(raw.get("load")),
        rest=_optional_text(raw.get("rest")),
        notes=_optional_text(raw.get("notes")),
        group=_optional_text(raw.get("group")),
        muscle_group=_optional_text(raw.get("muscle_group")),
    )


def _optional_text(value: Any) -> str | None:
    """Aceita número e texto, recusa estrutura — o formato é de texto.

    A quebra de linha é achatada pelo mesmo motivo do parser do MFIT: no
    Markdown ela cortaria o item ao meio e no Keep viraria um item sem
    checkbox, perdendo a marcação do usuário na ressincronização.
    """
    if value is None:
        return None
    if isinstance(value, dict | list):
        raise InterchangeError(f"Esperava texto, veio {type(value).__name__}.")
    text = " ".join(str(value).split())
    return text or None

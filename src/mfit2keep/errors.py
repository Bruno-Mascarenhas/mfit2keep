"""Quais erros o app sabe explicar, e como separá-los de um defeito de verdade.

Mora num módulo próprio porque a CLI e o painel precisam da **mesma** lista e
da **mesma** política. Duplicada, ela divergia em silêncio: bastava um erro
novo ser tratado num lado e virar traceback no outro.
"""

from mfit2keep.config import ConfigError
from mfit2keep.destinations.local import LocalDestinationError
from mfit2keep.interchange import InterchangeError
from mfit2keep.keep_auth import KeepAuthError
from mfit2keep.secrets_store import SecretsError
from mfit2keep.sources.base import SourceError
from mfit2keep.sources.mfit_api import MfitError

#: Erro que o usuário pode resolver — vira mensagem, nunca traceback.
EXPECTED_ERRORS = (
    ConfigError,
    MfitError,
    KeepAuthError,
    LocalDestinationError,
    SourceError,
    InterchangeError,
    SecretsError,
)


def expected_from(group: BaseExceptionGroup) -> BaseException | None:
    """O erro previsto de dentro de um grupo, ou ``None`` se houver outra coisa.

    Os dias do treino são buscados em paralelo, então a exceção chega embrulhada
    num ``ExceptionGroup``. Só vale desembrulhar quando o grupo INTEIRO é
    previsto: um bug de verdade ou um Ctrl+C viajando junto não pode ser
    escondido atrás da mensagem amigável do vizinho.
    """
    expected, unexpected = group.split(EXPECTED_ERRORS)
    if unexpected is not None or expected is None:
        return None
    return _first_leaf(expected)


def _first_leaf(group: BaseExceptionGroup) -> BaseException:
    """Desce até a primeira exceção de verdade — grupos podem estar aninhados."""
    primeira = group.exceptions[0]
    return _first_leaf(primeira) if isinstance(primeira, BaseExceptionGroup) else primeira

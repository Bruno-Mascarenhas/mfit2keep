"""A política de erro: o que vira mensagem e o que precisa continuar subindo."""

import pytest

from mfit2keep.config import ConfigError
from mfit2keep.errors import EXPECTED_ERRORS, expected_from
from mfit2keep.sources.mfit_api import MfitError


def test_group_entirely_expected_is_unwrapped() -> None:
    grupo = ExceptionGroup("dias", [MfitError("token expirou")])

    previsto = expected_from(grupo)

    assert isinstance(previsto, MfitError)
    assert str(previsto) == "token expirou"


def test_several_expected_errors_yield_the_first() -> None:
    grupo = ExceptionGroup("dias", [MfitError("dia 2"), ConfigError("falta e-mail")])

    assert isinstance(expected_from(grupo), MfitError)


def test_nested_group_is_unwrapped_to_a_real_exception() -> None:
    grupo = ExceptionGroup("fora", [ExceptionGroup("dentro", [MfitError("expirou")])])

    previsto = expected_from(grupo)

    # Devolver um grupo faria a tela imprimir o repr do grupo como mensagem.
    assert not isinstance(previsto, BaseExceptionGroup)
    assert str(previsto) == "expirou"


def test_group_with_a_real_bug_is_not_unwrapped() -> None:
    grupo = ExceptionGroup("misto", [MfitError("previsto"), ValueError("bug de verdade")])

    # Esconder o defeito atrás da mensagem amigável do vizinho deixaria o bug
    # invisível para quem mantém o projeto.
    assert expected_from(grupo) is None


def test_group_with_only_unexpected_errors_is_not_unwrapped() -> None:
    assert expected_from(ExceptionGroup("bug", [KeyError("nome")])) is None


def test_keyboard_interrupt_travelling_along_is_not_unwrapped() -> None:
    grupo = BaseExceptionGroup("misto", [MfitError("previsto"), KeyboardInterrupt()])

    assert expected_from(grupo) is None


@pytest.mark.parametrize("erro", EXPECTED_ERRORS)
def test_every_expected_error_is_unwrappable(erro: type[Exception]) -> None:
    # Erro novo entra na tupla e passa a ser tratado nos dois lados de uma vez.
    assert expected_from(ExceptionGroup("x", [erro("mensagem")])) is not None

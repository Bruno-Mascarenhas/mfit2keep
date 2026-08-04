"""Como a CLI traduz erro em mensagem — e o que ela nunca pode esconder."""

import asyncio

import pytest
import typer

from mfit2keep.cli import _run
from mfit2keep.config import ConfigError
from mfit2keep.sources.mfit_api import MfitError


async def _raise(error: BaseException) -> None:
    raise error


async def _in_task_group(*errors: BaseException) -> None:
    """Reproduz o TaskGroup que busca os dias do treino em paralelo."""
    async with asyncio.TaskGroup() as group:
        for error in errors:
            group.create_task(_raise(error))


def test_expected_error_becomes_a_clean_exit() -> None:
    with pytest.raises(typer.Exit) as info:
        _run(_raise(MfitError("credencial inválida")))

    assert info.value.exit_code == 1


def test_expected_error_inside_a_task_group_is_unwrapped() -> None:
    # Sem desembrulhar, o usuário veria um traceback de ExceptionGroup.
    with pytest.raises(typer.Exit):
        _run(_in_task_group(MfitError("dia 2 não existe")))


def test_several_expected_errors_still_exit_cleanly() -> None:
    with pytest.raises(typer.Exit):
        _run(_in_task_group(MfitError("dia 2"), ConfigError("falta MFIT_EMAIL")))


def test_unexpected_error_is_never_swallowed() -> None:
    # Um KeyError é bug no parser: esconder atrás da mensagem amigável do MFIT
    # deixaria o usuário sem traceback e sem saber que existe defeito.
    with pytest.raises(BaseExceptionGroup) as info:
        _run(_in_task_group(MfitError("dia 2 não existe"), KeyError("nome")))

    assert info.group_contains(KeyError)


def test_keyboard_interrupt_is_never_swallowed() -> None:
    # O asyncio.run repropaga o Ctrl+C puro, sem embrulhar em grupo — o que
    # importa é que ele não vire "saída limpa" por causa do erro previsto ao lado.
    with pytest.raises(KeyboardInterrupt):
        _run(_in_task_group(MfitError("dia 2 não existe"), KeyboardInterrupt()))


def test_lone_unexpected_error_propagates() -> None:
    with pytest.raises(ZeroDivisionError):
        _run(_raise(ZeroDivisionError("bug")))

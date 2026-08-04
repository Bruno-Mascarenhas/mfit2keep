"""Interface de linha de comando."""

import asyncio
from collections.abc import Coroutine
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from . import keep_auth
from .config import PROJECT_ROOT, ConfigError, load_settings
from .destinations.base import MARKER, NoteDestination, NoteResult
from .destinations.local import LocalDestinationError, LocalMarkdownDestination
from .keep_auth import KeepAuthError
from .mfit import MfitClient, MfitError
from .models import Workout
from .render import RenderOptions
from .sync import build_notes, fetch_workouts, list_routines

app = typer.Typer(
    add_completion=False,
    help="Extrai treinos do MFIT Personal e gera notas com checkboxes.",
    no_args_is_help=True,
)
console = Console()

EXPECTED_ERRORS = (ConfigError, MfitError, KeepAuthError, LocalDestinationError)


class Destino(StrEnum):
    LOCAL = "local"
    KEEP = "keep"


RoutineId = Annotated[int, typer.Argument(help="ID da rotina (o número na URL do MFIT).")]
Numbered = Annotated[bool, typer.Option("--numerar/--sem-numerar")]
Rest = Annotated[bool, typer.Option("--intervalo/--sem-intervalo")]
Load = Annotated[bool, typer.Option("--carga/--sem-carga")]
Width = Annotated[int, typer.Option("--largura", help="Corta a linha; 0 = sem corte.")]


def _fail(exc: BaseException) -> NoReturn:
    console.print(f"[red]{exc}[/]")
    raise typer.Exit(code=1) from None


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Executa a corrotina e transforma erro esperado em mensagem limpa."""
    try:
        return asyncio.run(coro)
    except EXPECTED_ERRORS as exc:
        _fail(exc)
    except BaseExceptionGroup as group:
        # O TaskGroup que busca os dias em paralelo embrulha a exceção original;
        # sem desembrulhar, o usuário veria um traceback de ExceptionGroup.
        expected, _ = group.split(EXPECTED_ERRORS)
        if expected is None:
            raise
        _fail(expected.exceptions[0])


def _options(numbered: bool, rest: bool, load: bool, width: int) -> RenderOptions:
    return RenderOptions(
        numbered=numbered, include_rest=rest, include_load=load, max_line_length=width
    )


def _destination(destino: Destino, out_dir: Path) -> NoteDestination:
    if destino is Destino.KEEP:
        from .destinations.keep import KeepDestination

        return KeepDestination(keep_auth.load(load_settings()))
    return LocalMarkdownDestination(out_dir)


@app.command("rotinas")
def routines() -> None:
    """Lista as rotinas de treino da sua conta."""

    async def run() -> list[dict[str, Any]]:
        async with MfitClient(load_settings()) as client:
            return await list_routines(client)

    table = Table("ID", "Nome", "Início", "Fim", title="Rotinas no MFIT")
    for routine in _run(run()):
        table.add_row(
            str(routine.get("id", "")),
            str(routine.get("nome", "")),
            str(routine.get("dataInicio", "")),
            str(routine.get("dataFim", "")),
        )
    console.print(table)


@app.command("preview")
def preview(
    routine_id: RoutineId,
    numbered: Numbered = True,
    rest: Rest = True,
    load: Load = True,
    width: Width = 0,
) -> None:
    """Mostra no terminal exatamente o que iria para as notas."""

    async def run() -> list[Workout]:
        async with MfitClient(load_settings()) as client:
            return await fetch_workouts(client, routine_id)

    for note in build_notes(_run(run()), _options(numbered, rest, load, width)):
        console.print(f"\n[bold cyan]{note.title}[/]")
        for item in note.items:
            console.print(f"  [dim]☐[/] {item.text}")


@app.command("sync")
def sync_command(
    routine_id: RoutineId,
    destino: Annotated[Destino, typer.Option("--destino", "-d")] = Destino.LOCAL,
    out_dir: Annotated[Path, typer.Option("--saida", "-o", help="Só para --destino local.")] = (
        PROJECT_ROOT / "notas"
    ),
    numbered: Numbered = True,
    rest: Rest = True,
    load: Load = True,
    width: Width = 0,
) -> None:
    """Gera as notas com checkboxes a partir de uma rotina."""

    async def run() -> list[NoteResult]:
        async with MfitClient(load_settings()) as client:
            workouts = await fetch_workouts(client, routine_id)
        notes = build_notes(workouts, _options(numbered, rest, load, width))
        async with _destination(destino, out_dir) as destination:
            return await destination.upsert_all(notes)

    table = Table("Nota", "Ação", "Onde")
    for result in _run(run()):
        table.add_row(result.note_title, str(result.action), result.reference or "")
    console.print(table)


@app.command("limpar")
def purge_command(
    destino: Annotated[Destino, typer.Option("--destino", "-d")] = Destino.LOCAL,
    archive: Annotated[bool, typer.Option("--arquivar", help="Arquiva em vez de apagar.")] = False,
    yes: Annotated[bool, typer.Option("--sim", "-s", help="Não pedir confirmação.")] = False,
    out_dir: Annotated[Path, typer.Option("--saida", "-o", help="Só para --destino local.")] = (
        PROJECT_ROOT / "notas"
    ),
) -> None:
    """Apaga (ou arquiva) só as notas criadas por este app.

    A seleção é feita pelo label `mfit2keep` no Keep — ou pelo carimbo no
    rodapé, no destino local. Nota sem a marca nunca é tocada.
    """
    verb = "Arquivar" if archive else "Apagar"
    if not yes and not typer.confirm(f"{verb} as notas marcadas com '{MARKER}' em {destino}?"):
        console.print("[yellow]Cancelado.[/]")
        raise typer.Exit(code=0)

    async def run() -> list[NoteResult]:
        async with _destination(destino, out_dir) as destination:
            return await destination.purge(archive=archive)

    results = _run(run())
    if not results:
        console.print(f"[yellow]Nenhuma nota com a marca '{MARKER}'.[/]")
        return

    table = Table("Nota", "Ação", "Onde")
    for result in results:
        table.add_row(result.note_title, str(result.action), result.reference or "")
    console.print(table)


@app.command("keep-login")
def keep_login(
    email: Annotated[str | None, typer.Option("--email", help="Sua conta Google.")] = None,
) -> None:
    """Troca o cookie `oauth_token` do Google pelo master token e o guarda.

    Ritual manual, uma vez só — a API oficial do Keep não atende conta pessoal.
    """
    email = email or load_settings().google_email
    if not email:
        email = typer.prompt("Sua conta Google (e-mail)")

    console.print(
        "\n[bold]Passo a passo[/] (faça numa janela anônima do navegador):\n"
        "  1. Abra [cyan]https://accounts.google.com/EmbeddedSetup[/]\n"
        "  2. Faça login e clique em [bold]Eu concordo[/].\n"
        "     A página fica girando para sempre — é esperado.\n"
        "  3. F12 → Application → Cookies → [cyan]https://accounts.google.com[/]\n"
        "  4. Copie o valor do cookie [bold]oauth_token[/] (começa com [dim]oauth2_4/[/]).\n"
        "[yellow]O cookie é de uso único e vale poucos minutos — cole logo.[/]\n"
    )
    oauth_token = typer.prompt("Cole o oauth_token", hide_input=True).strip()

    if not oauth_token.startswith("oauth2_4/"):
        console.print(
            "[yellow]Aviso: o valor não começa com 'oauth2_4/'. "
            "Confira se copiou o cookie certo — vou tentar mesmo assim.[/]"
        )

    async def run() -> str:
        assert email is not None
        device_id = keep_auth.new_device_id()
        master = await keep_auth.exchange_oauth_token(email, oauth_token, device_id)
        return keep_auth.store(keep_auth.KeepCredentials(email, master, device_id))

    where = _run(run())
    console.print(f"\n[green]Master token guardado em: {where}[/]")
    console.print("Agora rode: [bold]mfit2keep sync <rotina> --destino keep[/]")


if __name__ == "__main__":
    app()

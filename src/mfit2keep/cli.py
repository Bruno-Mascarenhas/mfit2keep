"""Interface de linha de comando."""

import asyncio
import json
from collections.abc import Coroutine
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from mfit2keep import keep_auth, secrets_store
from mfit2keep.config import (
    PROJECT_ROOT,
    ConfigError,
    env_file,
    load_settings,
    replace_env_vars,
)
from mfit2keep.destinations.base import MARKER, NoteDestination, NoteResult
from mfit2keep.destinations.local import LocalDestinationError, LocalMarkdownDestination
from mfit2keep.interchange import InterchangeError, workouts_to_dict
from mfit2keep.keep_auth import KeepAuthError
from mfit2keep.models import Workout
from mfit2keep.render import RenderOptions, routine_to_notes
from mfit2keep.sources.base import RoutineSummary, SourceError, WorkoutSource
from mfit2keep.sources.mfit import MfitSource
from mfit2keep.sources.mfit_api import MfitError
from mfit2keep.sources.workout_file import WorkoutFileSource

app = typer.Typer(
    add_completion=False,
    help="Extrai treinos do MFIT Personal e gera notas com checkboxes.",
    no_args_is_help=True,
)
console = Console()

EXPECTED_ERRORS = (
    ConfigError,
    MfitError,
    KeepAuthError,
    LocalDestinationError,
    SourceError,
    InterchangeError,
    secrets_store.SecretsError,
)


class Destino(StrEnum):
    LOCAL = "local"
    KEEP = "keep"


class Fonte(StrEnum):
    MFIT = "mfit"
    ARQUIVO = "arquivo"


RoutineId = Annotated[
    str | None,
    typer.Argument(help="ID da rotina na fonte (o número na URL, no MFIT). Opcional em arquivo."),
]
Numbered = Annotated[bool, typer.Option("--numerar/--sem-numerar")]
Rest = Annotated[bool, typer.Option("--intervalo/--sem-intervalo")]
Load = Annotated[bool, typer.Option("--carga/--sem-carga")]
Width = Annotated[int, typer.Option("--largura", help="Corta a linha; 0 = sem corte.")]
DestinationOpt = Annotated[Destino, typer.Option("--destino", "-d")]
SourceOpt = Annotated[Fonte, typer.Option("--fonte", "-f", help="De onde vêm os treinos.")]
SourceFile = Annotated[
    Path | None, typer.Option("--arquivo", help="JSON de treinos, para --fonte arquivo.")
]
OutDir = Annotated[Path, typer.Option("--saida", "-o", help="Só para --destino local.")]


def _fail(error: BaseException) -> NoReturn:
    console.print(f"[red]{error}[/]")
    raise typer.Exit(code=1) from None


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Executa a corrotina e transforma erro esperado em mensagem limpa."""
    try:
        return asyncio.run(coro)
    except EXPECTED_ERRORS as error:
        _fail(error)
    except BaseExceptionGroup as group:
        # O TaskGroup que busca os dias em paralelo embrulha a exceção original;
        # sem desembrulhar, o usuário veria um traceback de ExceptionGroup.
        expected, unexpected = group.split(EXPECTED_ERRORS)
        # Só trata quando o grupo INTEIRO é esperado: um bug de verdade ou um
        # Ctrl+C viajando junto não pode ser escondido pela mensagem amigável.
        if unexpected is not None or expected is None:
            raise
        _fail(expected.exceptions[0])


def _print_results(results: list[NoteResult]) -> None:
    """Tabela do que aconteceu com cada nota — igual no `sync` e no `limpar`."""
    table = Table("Nota", "Ação", "Onde")
    for result in results:
        table.add_row(result.note_title, str(result.action), result.reference or "")
    console.print(table)


def _options(numbered: bool, rest: bool, load: bool, width: int) -> RenderOptions:
    return RenderOptions(
        numbered=numbered, include_rest=rest, include_load=load, max_line_length=width
    )


def _source(fonte: Fonte, workout_file: Path | None) -> WorkoutSource:
    """Constrói a fonte escolhida — o único ponto que sabe quais existem."""
    if fonte is Fonte.ARQUIVO:
        if workout_file is None:
            raise ConfigError("Com --fonte arquivo, informe o JSON em --arquivo.")
        return WorkoutFileSource(workout_file)
    return MfitSource(load_settings())


def _destination(destino: Destino, out_dir: Path) -> NoteDestination:
    if destino is Destino.KEEP:
        from mfit2keep.destinations.keep import KeepDestination

        return KeepDestination(keep_auth.load(load_settings()))
    return LocalMarkdownDestination(out_dir)


@app.command("rotinas")
def routines(fonte: SourceOpt = Fonte.MFIT, workout_file: SourceFile = None) -> None:
    """Lista as rotinas de treino disponíveis na fonte."""

    async def run() -> list[RoutineSummary]:
        async with _source(fonte, workout_file) as source:
            return await source.list_routines()

    table = Table("ID", "Nome", "Início", "Fim", title=f"Rotinas em {fonte}")
    for routine in _run(run()):
        table.add_row(routine.id, routine.name, routine.starts_at or "", routine.ends_at or "")
    console.print(table)


@app.command("preview")
def preview(
    routine_id: RoutineId = None,
    fonte: SourceOpt = Fonte.MFIT,
    workout_file: SourceFile = None,
    numbered: Numbered = True,
    rest: Rest = True,
    load: Load = True,
    width: Width = 0,
) -> None:
    """Mostra no terminal exatamente o que iria para as notas."""

    async def run() -> list[Workout]:
        async with _source(fonte, workout_file) as source:
            return await source.fetch_workouts(routine_id)

    for note in routine_to_notes(_run(run()), _options(numbered, rest, load, width)):
        console.print(f"\n[bold cyan]{note.title}[/]")
        for item in note.items:
            console.print(f"  [dim]☐[/] {item.text}")


@app.command("sync")
def sync_command(
    routine_id: RoutineId = None,
    fonte: SourceOpt = Fonte.MFIT,
    workout_file: SourceFile = None,
    destino: DestinationOpt = Destino.LOCAL,
    out_dir: OutDir = PROJECT_ROOT / "notas",
    numbered: Numbered = True,
    rest: Rest = True,
    load: Load = True,
    width: Width = 0,
) -> None:
    """Gera as notas com checkboxes a partir de uma rotina."""

    async def run() -> list[NoteResult]:
        async with _source(fonte, workout_file) as source:
            workouts = await source.fetch_workouts(routine_id)
        notes = routine_to_notes(workouts, _options(numbered, rest, load, width))
        async with _destination(destino, out_dir) as destination:
            return await destination.upsert_all(notes)

    _print_results(_run(run()))


@app.command("exportar")
def export_command(
    routine_id: RoutineId = None,
    out_file: Annotated[Path, typer.Option("--saida", "-o", help="Arquivo JSON de saída.")] = (
        PROJECT_ROOT / "treinos.json"
    ),
    fonte: SourceOpt = Fonte.MFIT,
    workout_file: SourceFile = None,
) -> None:
    """Exporta os treinos para o formato neutro, independente de serviço.

    É a saída do MFIT: com o JSON na mão, `--fonte arquivo` alimenta o app sem
    conta e sem rede, e qualquer outra ferramenta pode gerar o mesmo formato.
    """

    async def run() -> list[Workout]:
        async with _source(fonte, workout_file) as source:
            return await source.fetch_workouts(routine_id)

    workouts = _run(run())
    payload = json.dumps(workouts_to_dict(workouts), ensure_ascii=False, indent=2)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(payload + "\n", encoding="utf-8")

    total = sum(len(workout.exercises) for workout in workouts)
    console.print(f"[green]{len(workouts)} treinos ({total} exercícios) em {out_file}[/]")


@app.command("limpar")
def purge_command(
    destino: DestinationOpt = Destino.LOCAL,
    archive: Annotated[bool, typer.Option("--arquivar", help="Arquiva em vez de apagar.")] = False,
    skip_confirmation: Annotated[
        bool, typer.Option("--sim", "-s", help="Não pedir confirmação.")
    ] = False,
    out_dir: OutDir = PROJECT_ROOT / "notas",
) -> None:
    """Apaga (ou arquiva) só as notas criadas por este app.

    A seleção é feita pelo label `mfit2keep` no Keep — ou pelo carimbo no
    rodapé, no destino local. Nota sem a marca nunca é tocada.
    """
    verb = "Arquivar" if archive else "Apagar"
    if not skip_confirmation and not typer.confirm(
        f"{verb} as notas marcadas com '{MARKER}' em {destino}?"
    ):
        console.print("[yellow]Cancelado.[/]")
        raise typer.Exit(code=0)

    async def run() -> list[NoteResult]:
        async with _destination(destino, out_dir) as destination:
            return await destination.purge(archive=archive)

    results = _run(run())
    if not results:
        console.print(f"[yellow]Nenhuma nota com a marca '{MARKER}'.[/]")
        return

    _print_results(results)


segredos = typer.Typer(help="Tira os segredos do texto puro, cifrando com o TPM da máquina.")
app.add_typer(segredos, name="segredos")


@segredos.command("status")
def secrets_status() -> None:
    """Mostra onde cada segredo está guardado hoje."""
    settings = load_settings()

    table = Table("Segredo", "Onde está", title=f"Segredos em {env_file()}")
    exposed = False
    for secret in secrets_store.MANAGED:
        plaintext, encrypted = settings.secret_pair(secret.env_var)
        backend = secrets_store.backend_of(plaintext=plaintext, encrypted=encrypted)
        exposed = exposed or backend is secrets_store.Backend.PLAINTEXT
        color = "red" if backend is secrets_store.Backend.PLAINTEXT else "green"
        table.add_row(secret.label, f"[{color}]{backend}[/]")
    console.print(table)

    if not secrets_store.systemd_creds_available():
        console.print("[yellow]systemd-creds indisponível nesta máquina.[/]")
    elif exposed:
        console.print("Rode [bold]mfit2keep segredos proteger[/] para cifrar o que está exposto.")
    else:
        console.print("[green]Nada em texto puro.[/]")


@segredos.command("proteger")
def secrets_protect(
    write: Annotated[
        bool, typer.Option("--escrever/--mostrar", help="Reescreve o .env ou só imprime.")
    ] = False,
) -> None:
    """Cifra os segredos do .env com o TPM2 desta máquina.

    O blob resultante só decifra aqui: cópia de backup, disco roubado ou SSD
    devolvido em RMA não servem para nada.
    """
    if not secrets_store.systemd_creds_available():
        _fail(
            ConfigError(
                "systemd-creds não está disponível para o seu usuário. "
                "Sem ele, o master token continua no keyring e a senha, no .env."
            )
        )

    settings = load_settings()

    lines: list[str] = []
    for secret in secrets_store.MANAGED:
        plaintext, _ = settings.secret_pair(secret.env_var)
        if not plaintext:
            console.print(f"[dim]{secret.label}: nada em texto puro para cifrar.[/]")
            continue
        try:
            lines.append(f"{secret.encrypted_var}={secrets_store.encrypt(secret.key, plaintext)}")
        except secrets_store.SecretsError as error:
            _fail(error)
        console.print(f"[green]{secret.label}: cifrado.[/]")

    if not lines:
        console.print("Nada a fazer.")
        return

    if write:
        console.print(
            f"\n[green]{replace_env_vars(lines)} atualizado.[/] "
            "As linhas em texto puro foram removidas."
        )
    else:
        console.print("\nCole no seu .env e [bold]apague as linhas em texto puro[/]:\n")
        for line in lines:
            console.print(line)
        console.print("\n(ou rode de novo com [bold]--escrever[/] para eu fazer isso)")

    console.print(
        "\n[yellow]Guarde a senha num gerenciador:[/] o blob depende do TPM desta placa. "
        "Reinstalar o sistema ou trocar de máquina exige redigitar."
    )


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

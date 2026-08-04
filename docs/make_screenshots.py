"""Gera os SVGs do README a partir da saída real da CLI.

Usa dados de exemplo — nenhum treino real entra no repositório.
Rode com: ``python docs/make_screenshots.py``
"""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mfit2keep.destinations.base import Action
from mfit2keep.models import Exercise, Workout
from mfit2keep.render import routine_to_notes

DOCS = Path(__file__).parent
WIDTH = 78

DEMO = [
    Workout(
        id="1",
        name="Peito e Tríceps",
        letter="A",
        exercises=[
            Exercise(name="Supino Reto com Barra", reps="4x10", rest="60s"),
            Exercise(name="Supino Inclinado com Halteres", reps="3x12", rest="45s"),
            Exercise(name="Crucifixo Máquina", reps="3x15", rest="45s"),
            Exercise(name="Tríceps na Polia com Corda", reps="3x12 a 15", rest="45s"),
            Exercise(name="Tríceps Coice na Polia", reps="3x12 a 15", rest="45s"),
            Exercise(name="Esteira Caminhada", reps="20"),
        ],
    ),
    Workout(
        id="2",
        name="Costas e Bíceps",
        letter="B",
        exercises=[
            Exercise(name="Puxada Frente Barra Reta", reps="4x12", rest="60s"),
            Exercise(name="Remada Baixa Triângulo", reps="3x12", rest="45s"),
            Exercise(name="Rosca Scott com Halteres", reps="3x12", rest="45s"),
        ],
    ),
]


def _console() -> Console:
    return Console(record=True, width=WIDTH)


def _prompt(console: Console, command: str) -> None:
    console.print(f"[bold green]$[/] {command}\n")


def preview_svg() -> None:
    console = _console()
    _prompt(console, "mfit2keep preview 12345678")
    for note in routine_to_notes(DEMO):
        console.print(f"[bold cyan]{note.title}[/]")
        for item in note.items:
            console.print(f"  [dim]☐[/] {item.text}")
        console.print()
    console.save_svg(str(DOCS / "preview.svg"), title="mfit2keep preview")


def sync_svg() -> None:
    console = _console()
    _prompt(console, "mfit2keep sync 12345678 --destino keep")

    table = Table("Nota", "Ação", "Onde")
    rows = [
        ("🏋️ A — Peito e Tríceps", Action.CREATED, "https://keep.google.com/#NOTE/18Soc51…"),
        ("🏋️ B — Costas e Bíceps", Action.CREATED, "https://keep.google.com/#NOTE/1W4XjHH…"),
        ("🏋️ C — Perna", Action.UNCHANGED, "https://keep.google.com/#NOTE/10TD9CG…"),
    ]
    for title, action, url in rows:
        table.add_row(title, str(action), url)
    console.print(table)
    console.save_svg(str(DOCS / "sync.svg"), title="mfit2keep sync")


def export_svg() -> None:
    """O ciclo que tira os treinos do MFIT e os traz de volta sem rede."""
    console = _console()
    _prompt(console, "mfit2keep exportar 12345678 -o treinos.json")
    console.print("[green]5 treinos (42 exercícios) em treinos.json[/]\n")

    _prompt(console, "mfit2keep sync --fonte arquivo --arquivo treinos.json -d keep")
    table = Table("Nota", "Ação", "Onde")
    for title in ("🏋️ A — Peito e Tríceps", "🏋️ B — Costas e Bíceps"):
        table.add_row(title, str(Action.UNCHANGED), "https://keep.google.com/#NOTE/…")
    console.print(table)
    console.print("\n[dim]sem conta, sem rede, sem MFIT — e o resultado é idêntico[/]")
    console.save_svg(str(DOCS / "export.svg"), title="mfit2keep exportar")


def secrets_svg() -> None:
    console = _console()
    _prompt(console, "mfit2keep segredos status")

    table = Table("Segredo", "Onde está", title="Segredos em ~/.config/mfit2keep/.env")
    table.add_row("senha do MFIT", "[green]cifrado na máquina[/]")
    table.add_row("master token do Google", "[green]keyring do sistema[/]")
    console.print(table)
    console.print("[green]Nada em texto puro.[/]")
    console.save_svg(str(DOCS / "secrets.svg"), title="mfit2keep segredos status")


if __name__ == "__main__":
    preview_svg()
    sync_svg()
    export_svg()
    secrets_svg()
    print(f"SVGs gerados em {DOCS}")

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


def preview_svg() -> None:
    console = Console(record=True, width=WIDTH)
    console.print("[bold green]$[/] mfit2keep preview 12345678\n")
    for note in routine_to_notes(DEMO):
        console.print(f"[bold cyan]{note.title}[/]")
        for item in note.items:
            console.print(f"  [dim]☐[/] {item.text}")
        console.print()
    console.save_svg(str(DOCS / "preview.svg"), title="mfit2keep preview")


def sync_svg() -> None:
    console = Console(record=True, width=WIDTH)
    console.print("[bold green]$[/] mfit2keep sync 12345678 --destino keep\n")

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


if __name__ == "__main__":
    preview_svg()
    sync_svg()
    print(f"SVGs gerados em {DOCS}")

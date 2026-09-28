"""Render a sample CLI session to an SVG for the README (demo data)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

OUT = Path(__file__).resolve().parent.parent / "docs" / "cli-balances.svg"

console = Console(record=True, width=76)

console.print('[dim]$ tricount add "Fondue dinner" 96 --split Moritz,Anna,Ben,Chloé[/]')
console.print("[green]Added[/] · ski-trip  —  Fondue dinner 96.00 EUR (each owes 24.00)\n")

console.print("[dim]$ tricount balances[/]")
console.print("[bold]Ski Trip 2026[/] · balances (EUR)")
table = Table()
table.add_column("Member")
table.add_column("Balance", justify="right")
for name, value in [("Moritz", 84.20), ("Anna", 12.50), ("Ben", -46.30), ("Chloé", -50.40)]:
    colour = "green" if value > 0 else "red"
    table.add_row(name, f"[{colour}]{value:+.2f}[/]")
console.print(table)
console.print("\n[bold]Suggested payments[/]")
for frm, to, amt in [("Chloé", "Moritz", 50.40), ("Ben", "Moritz", 33.80), ("Ben", "Anna", 12.50)]:
    console.print(f"  [red]{frm}[/] pays [green]{to}[/] {amt:.2f} EUR")

OUT.parent.mkdir(parents=True, exist_ok=True)
console.save_svg(str(OUT), title="tricount — CLI")
print(f"wrote {OUT}")

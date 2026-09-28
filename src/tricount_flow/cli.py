"""``tricount`` command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import config as cfgmod
from .config import Config, ConfigError, extract_token
from .core import Core, CoreError, category_names
from .csvio import parse_csv

# Errors we can explain to the user rather than dumping a traceback.
USER_ERRORS = (CoreError, ConfigError)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Add expenses and view balances on a Tricount, from your laptop.",
)
console = Console()
err_console = Console(stderr=True)


def _fail(message: str) -> None:
    err_console.print(f"[bold red]Error:[/] {message}")
    raise typer.Exit(1)


def _core() -> Core:
    try:
        return Core()
    except ConfigError as exc:
        _fail(str(exc))
        raise  # unreachable; keeps type checkers happy


def _fmt(amount: float, currency: str) -> str:
    return f"{amount:.2f} {currency}"


def _emit_json(obj) -> None:
    typer.echo(json.dumps(obj, indent=2, ensure_ascii=False))


def _fetch_and_members(cfg: Config, link: str) -> tuple[object, list[str]]:
    """Validate a share link, fetch the tricount, return (tricount, member names)."""
    token = extract_token(link)  # raises ConfigError on a bad shape
    tc = Core(cfg).client.get_tricount(token)  # raises CoreError/ApiError
    members = [m.display_name for m in tc.members if m.status == "ACTIVE"]
    if not members:
        raise ConfigError("This tricount has no active members.")
    return tc, members


def _render_import(results) -> tuple[int, int]:
    table = Table()
    table.add_column("#", justify="right")
    table.add_column("Description")
    table.add_column("Amount", justify="right")
    table.add_column("Action")
    table.add_column("Result")
    for r in results:
        mark = "[green]✓[/]" if r.ok else "[red]✗[/]"
        amount = f"{r.amount:.2f}" if r.amount is not None else "-"
        table.add_row(str(r.line), r.description or "-", amount, r.action, f"{mark} {r.detail}")
    console.print(table)
    ok = sum(1 for r in results if r.ok)
    return ok, len(results) - ok


# --------------------------------------------------------------------------
@app.command()
def init() -> None:
    """Add a tricount from its share link (interactive).

    For scripting, use the non-interactive `tricount tricounts add` instead.
    """
    cfg = cfgmod.load()
    link = typer.prompt("Tricount share link (https://tricount.com/tXXXX)").strip()
    try:
        tc, members = _fetch_and_members(cfg, link)
    except USER_ERRORS as exc:
        _fail(str(exc))

    console.print(
        Panel.fit(
            f"[bold]{tc.title}[/]  ·  {tc.currency}\nMembers: {', '.join(members)}",
            title="Found tricount",
        )
    )

    console.print("\nWhich member are you? (default payer)")
    for idx, name in enumerate(members, 1):
        console.print(f"  [cyan]{idx}[/]. {name}")
    choice = typer.prompt("Number (or blank to skip)", default="", show_default=False).strip()
    me: str | None = None
    if choice:
        try:
            me = members[int(choice) - 1]
        except (ValueError, IndexError):
            _fail(f"'{choice}' is not one of the listed numbers.")

    default_name = _slug(tc.title) or "tricount"
    name = typer.prompt("Short alias for this tricount", default=default_name).strip()
    if name in cfg.tricounts and not typer.confirm(
        f"'{name}' already exists — overwrite?", default=False
    ):
        raise typer.Exit(0)

    was_first = cfg.default is None
    cfg.upsert(name, link, me)  # sets default automatically if it was the first
    if not was_first and typer.confirm(f"Make '{name}' the default tricount?", default=False):
        cfg.set_default(name)

    path = cfgmod.save(cfg)
    console.print(
        f"\n[green]Saved.[/] '{name}'"
        + (f" (you = {me})" if me else "")
        + (" [default]" if cfg.default == name else "")
        + f"\nConfig: {path}"
    )


@app.command()
def add(
    description: str = typer.Argument(..., help='What was bought, e.g. "Dinner".'),
    amount: float = typer.Argument(..., help="Total amount in the tricount currency, e.g. 45"),
    payer: str | None = typer.Option(None, "--payer", "-p", help="Who paid (default: you)."),
    split: str | None = typer.Option(
        None, "--split", "-s", help="Comma-separated members to split among (default: everyone)."
    ),
    category: str | None = typer.Option(None, "--category", "-c", help="Category name or label."),
    date: str | None = typer.Option(
        None, "--date", "-D", help="Date it occurred, e.g. 25.09 or 2026-09-25 (default: today)."
    ),
    for_: str | None = typer.Option(
        None, "--for", "-f", help="Which tricount (default: the default)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be added, but don't send it."
    ),
) -> None:
    """Add an expense."""
    core = _core()
    split_list = [s.strip() for s in split.split(",") if s.strip()] if split else None
    try:
        preview = core.add_expense(
            description=description,
            amount=amount,
            name=for_,
            payer=payer,
            split=split_list,
            category=category,
            date=date,
            dry_run=dry_run,
        )
    except USER_ERRORS as exc:
        _fail(str(exc))

    among = ", ".join(preview.split_among)
    body = (
        f"[bold]{preview.description}[/]  {_fmt(preview.amount, preview.currency)}\n"
        f"Date: {preview.date}\n"
        f"Paid by [cyan]{preview.payer}[/]\n"
        f"Split among {len(preview.split_among)}: {among}\n"
        f"Each owes: {_fmt(preview.per_person, preview.currency)}"
        + (f"\nCategory: {preview.category}" if preview.category else "")
    )
    if dry_run:
        console.print(Panel.fit(body, title=f"[yellow]DRY RUN[/] · {preview.tricount}"))
        console.print("[yellow]Not sent.[/] Re-run without --dry-run to add it.")
    else:
        console.print(Panel.fit(body, title=f"[green]Added[/] · {preview.tricount}"))


@app.command()
def reimburse(
    amount: float = typer.Argument(..., help="Amount paid back."),
    to: str = typer.Option(..., "--to", "-t", help="Who received the money."),
    frm: str | None = typer.Option(None, "--from", help="Who paid (default: you)."),
    for_: str | None = typer.Option(None, "--for", "-f", help="Which tricount."),
    description: str = typer.Option("Reimbursement", "--description", "-d"),
    date: str | None = typer.Option(
        None, "--date", "-D", help="Date it occurred, e.g. 25.09 (default: today)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview only."),
) -> None:
    """Record a reimbursement (one member paying another back)."""
    core = _core()
    try:
        preview = core.add_reimbursement(
            amount=amount,
            to=to,
            name=for_,
            frm=frm,
            description=description,
            date=date,
            dry_run=dry_run,
        )
    except USER_ERRORS as exc:
        _fail(str(exc))

    body = (
        f"[cyan]{preview.frm}[/] → [cyan]{preview.to}[/]  "
        f"{_fmt(preview.amount, preview.currency)}\n{preview.description}"
    )
    title = (
        "[yellow]DRY RUN[/] · " if dry_run else "[green]Reimbursement[/] · "
    ) + preview.tricount
    console.print(Panel.fit(body, title=title))
    if dry_run:
        console.print("[yellow]Not sent.[/] Re-run without --dry-run.")


@app.command()
def balances(
    for_: str | None = typer.Option(None, "--for", "-f", help="Which tricount."),
    json_: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show who owes whom."""
    core = _core()
    try:
        report = core.balances(for_)
    except USER_ERRORS as exc:
        _fail(str(exc))

    if json_:
        _emit_json(
            {
                "tricount": report.tricount,
                "title": report.title,
                "currency": report.currency,
                "balances": report.balances,
                "settlements": [
                    {"from": p.frm, "to": p.to, "amount": p.amount} for p in report.settlements
                ],
            }
        )
        return

    table = Table(title=f"{report.title} · balances ({report.currency})")
    table.add_column("Member")
    table.add_column("Balance", justify="right")
    for name, value in sorted(report.balances.items(), key=lambda kv: kv[1], reverse=True):
        colour = "green" if value > 0 else ("red" if value < 0 else "white")
        table.add_row(name, f"[{colour}]{value:+.2f}[/]")
    console.print(table)

    if report.settlements:
        console.print("\n[bold]Suggested payments[/]")
        for p in report.settlements:
            console.print(
                f"  [red]{p.frm}[/] pays [green]{p.to}[/] {_fmt(p.amount, report.currency)}"
            )
    else:
        console.print("\n[green]All settled up![/]")


@app.command(name="list")
def list_(
    number: int = typer.Option(10, "--number", "-n", help="How many recent expenses."),
    for_: str | None = typer.Option(None, "--for", "-f", help="Which tricount."),
    json_: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List recent expenses."""
    core = _core()
    try:
        rows = core.list_expenses(for_, limit=number)
    except USER_ERRORS as exc:
        _fail(str(exc))

    if json_:
        _emit_json(
            [
                {
                    "date": r.date,
                    "description": r.description,
                    "payer": r.payer,
                    "amount": r.amount,
                    "currency": r.currency,
                    "category": r.category,
                    "kind": r.kind,
                }
                for r in rows
            ]
        )
        return

    if not rows:
        console.print("No expenses yet.")
        return
    table = Table()
    table.add_column("Date")
    table.add_column("Description")
    table.add_column("Payer")
    table.add_column("Amount", justify="right")
    table.add_column("Category")
    for r in rows:
        desc = r.description + ("" if r.kind == "NORMAL" else f" [{r.kind.lower()}]")
        table.add_row(r.date, desc, r.payer, _fmt(r.amount, r.currency), r.category or "-")
    console.print(table)


@app.command(name="import")
def import_(
    file: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True, help="CSV file to import."
    ),
    for_: str | None = typer.Option(None, "--for", "-f", help="Which tricount."),
    payer: str | None = typer.Option(
        None, "--payer", "-p", help="Default payer for rows without one (default: you)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate and preview only; send nothing."
    ),
    json_: bool = typer.Option(False, "--json", help="Output results as JSON."),
) -> None:
    """Bulk-import expenses from a CSV file (see examples/expenses.csv for the format)."""
    parsed = parse_csv(file.read_text(encoding="utf-8", errors="replace"))
    if parsed.header_error:
        _fail(parsed.header_error)
    if not parsed.rows:
        _fail("No data rows found in the CSV.")

    core = _core()
    try:
        resolved = core.cfg.resolve_name(for_)
    except ConfigError as exc:
        _fail(str(exc))

    # Always validate first so the user sees what will happen before anything is sent.
    try:
        preview = core.import_expenses(parsed.rows, name=for_, default_payer=payer, dry_run=True)
    except USER_ERRORS as exc:
        _fail(str(exc))

    if dry_run:
        if json_:
            _emit_json(_import_json(preview))
            return
        console.print(f"[yellow]DRY RUN[/] · {resolved}")
        ok, fail = _render_import(preview)
        console.print(f"\n{ok} would import, {fail} would be skipped. [yellow]Nothing sent.[/]")
        return

    ok, fail = _render_import(preview)
    console.print(
        f"\n[bold]{ok}[/] to import into '{resolved}', [bold]{fail}[/] invalid (skipped)."
    )
    if ok == 0:
        _fail("Nothing valid to import.")
    if not yes and not typer.confirm(
        f"Import {ok} entr{'y' if ok == 1 else 'ies'} into '{resolved}'?", default=True
    ):
        raise typer.Exit(0)

    try:
        results = core.import_expenses(parsed.rows, name=for_, default_payer=payer, dry_run=False)
    except USER_ERRORS as exc:
        _fail(str(exc))

    if json_:
        _emit_json(_import_json(results))
        return
    ok, fail = _render_import(results)
    console.print(f"\n[green]Imported {ok}[/], {fail} skipped, into '{resolved}'.")


def _import_json(results) -> list[dict]:
    return [
        {
            "line": r.line,
            "description": r.description,
            "amount": r.amount,
            "action": r.action,
            "ok": r.ok,
            "detail": r.detail,
            "tx_id": r.tx_id,
        }
        for r in results
    ]


# --------------------------------------------------------------------------
# Multi-tricount management: `tricount tricounts ...`
# --------------------------------------------------------------------------
tricounts_app = typer.Typer(
    help="Manage your saved tricounts (aliases). Run with no subcommand to list.",
    invoke_without_command=True,
)
app.add_typer(tricounts_app, name="tricounts")


def _tricounts_payload(cfg: Config) -> list[dict]:
    out = []
    for alias, entry in cfg.tricounts.items():
        try:
            token = extract_token(entry.link)
        except ConfigError:
            token = None
        out.append(
            {
                "alias": alias,
                "me": entry.me,
                "link": entry.link,
                "token": token,
                "default": cfg.default == alias,
            }
        )
    return out


@tricounts_app.callback(invoke_without_command=True)
def tricounts_root(
    ctx: typer.Context,
    json_: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List saved tricounts (default action)."""
    if ctx.invoked_subcommand is not None:
        return
    cfg = cfgmod.load()
    if json_:
        _emit_json(_tricounts_payload(cfg))
        return
    if not cfg.tricounts:
        console.print("No tricounts configured yet. Run [cyan]tricount init[/].")
        return
    table = Table()
    table.add_column("Alias")
    table.add_column("You are")
    table.add_column("Link")
    table.add_column("Default", justify="center")
    for row in _tricounts_payload(cfg):
        table.add_row(row["alias"], row["me"] or "-", row["link"], "★" if row["default"] else "")
    console.print(table)


@tricounts_app.command("add")
def tricounts_add(
    link: str = typer.Argument(..., help="Share link, e.g. https://tricount.com/tXXXX"),
    alias: str | None = typer.Option(None, "--alias", "-a", help="Short id (default: from title)."),
    me: str | None = typer.Option(None, "--me", help="Which member you are (default payer)."),
    make_default: bool = typer.Option(False, "--default", help="Make this the default tricount."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing alias."),
    json_: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Add a tricount from a share link (non-interactive; for scripting)."""
    cfg = cfgmod.load()
    try:
        token = extract_token(link)
        tc, members = _fetch_and_members(cfg, link)
    except USER_ERRORS as exc:
        _fail(str(exc))

    alias = alias or _slug(tc.title) or "tricount"
    if alias in cfg.tricounts and not force:
        _fail(
            f"Alias '{alias}' already exists. Use --alias to pick another, or --force to overwrite."
        )
    if me is not None and me not in members:
        _fail(f"'{me}' is not a member of this tricount. Members: {', '.join(members)}.")

    dupes = cfg.aliases_for_token(token, exclude=alias)
    cfg.upsert(alias, link, me)
    if make_default:
        cfg.set_default(alias)
    path = cfgmod.save(cfg)

    if json_:
        _emit_json(
            {"ok": True, "alias": alias, "me": me, "default": cfg.default == alias, "token": token}
        )
        return
    console.print(
        f"[green]Added[/] '{alias}' — [bold]{tc.title}[/] ({tc.currency})"
        + (f", you = {me}" if me else "")
        + (" [default]" if cfg.default == alias else "")
    )
    if dupes:
        console.print(f"[yellow]Note:[/] same tricount is also saved as: {', '.join(dupes)}.")
    console.print(f"Config: {path}")


@tricounts_app.command("remove")
def tricounts_remove(
    alias: str = typer.Argument(..., help="Alias to remove."),
) -> None:
    """Remove a saved tricount (does not touch the tricount itself)."""
    cfg = cfgmod.load()
    try:
        cfg.remove(alias)
    except ConfigError as exc:
        _fail(str(exc))
    cfgmod.save(cfg)
    tail = f" New default: [cyan]{cfg.default}[/]." if cfg.default else " No tricounts left."
    console.print(f"[green]Removed[/] '{alias}'.{tail}")


@tricounts_app.command("rename")
def tricounts_rename(
    old: str = typer.Argument(..., help="Current alias."),
    new: str = typer.Argument(..., help="New alias."),
) -> None:
    """Rename a tricount alias."""
    cfg = cfgmod.load()
    try:
        cfg.rename(old, new)
    except ConfigError as exc:
        _fail(str(exc))
    cfgmod.save(cfg)
    console.print(f"[green]Renamed[/] '{old}' → '{new}'.")


@tricounts_app.command("set-default")
def tricounts_set_default(
    alias: str = typer.Argument(..., help="Alias to make the default."),
) -> None:
    """Set the default tricount."""
    cfg = cfgmod.load()
    try:
        cfg.set_default(alias)
    except ConfigError as exc:
        _fail(str(exc))
    cfgmod.save(cfg)
    console.print(f"[green]Default is now[/] '{alias}'.")


@tricounts_app.command("set-me")
def tricounts_set_me(
    alias: str = typer.Argument(..., help="Alias to update."),
    member: str = typer.Argument(..., help="Which member you are (default payer)."),
    no_validate: bool = typer.Option(
        False, "--no-validate", help="Skip checking the member exists."
    ),
) -> None:
    """Set which member you are in a tricount."""
    cfg = cfgmod.load()
    if alias not in cfg.tricounts:
        _fail(f"Unknown tricount '{alias}'.")
    if not no_validate:
        try:
            _, members = _fetch_and_members(cfg, cfg.tricounts[alias].link)
        except USER_ERRORS as exc:
            _fail(str(exc))
        if member not in members:
            _fail(
                f"'{member}' is not a member. Members: {', '.join(members)}. "
                "Use --no-validate to force."
            )
    cfg.set_me(alias, member)
    cfgmod.save(cfg)
    console.print(f"[green]Set[/] you = '{member}' for '{alias}'.")


@tricounts_app.command("show")
def tricounts_show(
    alias: str | None = typer.Argument(None, help="Alias (default: the default tricount)."),
    json_: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show a tricount's live details (title, currency, members)."""
    core = _core()
    try:
        info = core.info(alias)
    except USER_ERRORS as exc:
        _fail(str(exc))
    entry = core.cfg.tricounts[info["name"]]
    payload = {
        "alias": info["name"],
        "title": info["title"],
        "currency": info["currency"],
        "me": info["me"],
        "members": info["members"],
        "link": entry.link,
        "token": extract_token(entry.link),
        "default": core.cfg.default == info["name"],
    }
    if json_:
        _emit_json(payload)
        return
    console.print(
        Panel.fit(
            f"[bold]{payload['title']}[/]  ·  {payload['currency']}"
            + ("  [default]" if payload["default"] else "")
            + f"\nAlias: {payload['alias']}"
            + f"\nYou are: {payload['me'] or '(not set)'}"
            + f"\nMembers: {', '.join(payload['members'])}"
            + f"\nLink: {payload['link']}",
            title="Tricount",
        )
    )


@app.command()
def categories() -> None:
    """Show the built-in category names accepted by --category."""
    console.print(", ".join(category_names()))


@app.command()
def web(
    port: int = typer.Option(8787, "--port", "-P", help="Port to serve on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host/interface to bind."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open a browser."),
) -> None:
    """Launch the local web UI."""
    import threading
    import webbrowser

    import uvicorn

    from .web.app import create_app

    if not no_browser:
        url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    console.print(f"[green]Tricount web UI[/] on http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.strip().lower()).strip("-")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

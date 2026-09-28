"""Local web UI — a thin FastAPI front-end over :class:`tricount_flow.core.Core`."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from ..config import ConfigError
from ..core import ApiError, Core, CoreError, category_names
from ..csvio import parse_csv

HERE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))


class ExpenseIn(BaseModel):
    description: str
    amount: float
    payer: str | None = None
    split: list[str] | None = None
    category: str | None = None
    date: str | None = None


class ReimburseIn(BaseModel):
    amount: float
    to: str
    frm: str | None = None
    description: str = "Reimbursement"
    date: str | None = None


class ImportIn(BaseModel):
    csv: str
    dry_run: bool = True
    payer: str | None = None


def _guard(fn):
    try:
        return fn()
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_app(core: Core | None = None) -> FastAPI:
    app = FastAPI(title="Tricount Flow")
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    core = core if core is not None else Core()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        names = list(core.cfg.tricounts)
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {
                "tricounts": names,
                "default": core.cfg.default,
                "categories": category_names(),
                "has_config": bool(names),
            },
        )

    @app.get("/api/tricount/{name}")
    def info(name: str):
        return _guard(lambda: core.info(name))

    @app.get("/api/tricount/{name}/balances")
    def balances(name: str):
        report = _guard(lambda: core.balances(name))
        return {
            "title": report.title,
            "currency": report.currency,
            "balances": report.balances,
            "settlements": [
                {"frm": p.frm, "to": p.to, "amount": p.amount} for p in report.settlements
            ],
        }

    @app.get("/api/tricount/{name}/expenses")
    def expenses(name: str, n: int = 10):
        rows = _guard(lambda: core.list_expenses(name, limit=n))
        return [
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

    @app.post("/api/tricount/{name}/expense")
    def add_expense(name: str, body: ExpenseIn):
        preview = _guard(
            lambda: core.add_expense(
                name=name,
                description=body.description,
                amount=body.amount,
                payer=body.payer,
                split=body.split,
                category=body.category,
                date=body.date,
            )
        )
        return {"ok": True, "tx_id": preview.tx_id, "per_person": preview.per_person}

    @app.post("/api/tricount/{name}/reimburse")
    def add_reimbursement(name: str, body: ReimburseIn):
        preview = _guard(
            lambda: core.add_reimbursement(
                name=name,
                amount=body.amount,
                to=body.to,
                frm=body.frm,
                description=body.description,
                date=body.date,
            )
        )
        return {"ok": True, "tx_id": preview.tx_id}

    @app.post("/api/tricount/{name}/import")
    def import_csv(name: str, body: ImportIn):
        parsed = parse_csv(body.csv)
        if parsed.header_error:
            raise HTTPException(status_code=400, detail=parsed.header_error)
        if not parsed.rows:
            raise HTTPException(status_code=400, detail="No data rows found in the CSV.")
        results = _guard(
            lambda: core.import_expenses(
                parsed.rows, name=name, default_payer=body.payer, dry_run=body.dry_run
            )
        )
        ok = sum(1 for r in results if r.ok)
        return {
            "dry_run": body.dry_run,
            "summary": {"ok": ok, "failed": len(results) - ok},
            "results": [
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
            ],
        }

    return app

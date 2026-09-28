"""The only module that talks to the unofficial ``tricount-api``.

Everything the CLI and web UI need goes through :class:`Core`. Keeping all API
calls here means that if bunq changes the private API, this is the one file to fix.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime

import tricount as tapi

from . import config as cfgmod
from .config import Config, extract_token
from .csvio import ImportRow
from .settle import Payment, settle

CACHE_TTL = 60.0  # seconds

# Friendly names -> the library's Category enum.
_CATEGORY_ALIASES = {
    "food": "FOOD_AND_DRINK",
    "drink": "FOOD_AND_DRINK",
    "drinks": "FOOD_AND_DRINK",
    "restaurant": "FOOD_AND_DRINK",
    "food_and_drink": "FOOD_AND_DRINK",
    "grocery": "GROCERIES",
    "groceries": "GROCERIES",
    "supermarket": "GROCERIES",
    "transport": "TRANSPORT",
    "travel": "TRAVEL",
    "fun": "ENTERTAINMENT",
    "entertainment": "ENTERTAINMENT",
    "health": "HEALTHCARE",
    "healthcare": "HEALTHCARE",
    "insurance": "INSURANCE",
    "rent": "RENT_AND_UTILITIES",
    "utilities": "RENT_AND_UTILITIES",
    "rent_and_utilities": "RENT_AND_UTILITIES",
    "shopping": "SHOPPING",
    "other": "OTHER",
}


class CoreError(Exception):
    """A problem we can explain to the user (bad member name, no config, ...)."""


class ApiError(CoreError):
    """The unofficial API failed or returned something unexpected."""


def category_names() -> list[str]:
    return [c.name for c in tapi.Category]


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d.%m.",
    "%d.%m",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d/%m",
)


def parse_date(value: str | None) -> datetime | None:
    """Parse a user-supplied date into a datetime (noon local, to avoid TZ day-shift).

    Accepts ISO (``2026-09-25``) and day-first European forms (``25.09``,
    ``25.09.2026``, ``25/09``). A missing year defaults to the current year.
    Returns ``None`` for empty input (meaning "now").
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt and "%y" not in fmt:
            dt = dt.replace(year=_date.today().year)
        return dt.replace(hour=12, minute=0, second=0, microsecond=0)
    raise CoreError(f"Could not parse date '{value}'. Try DD.MM, DD.MM.YYYY, or YYYY-MM-DD.")


def resolve_category(value: str | None):
    """Map a user string to ``(Category | None, category_custom | None)``."""
    if not value:
        return None, None
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    names = {c.name.lower(): c for c in tapi.Category}
    if key in names:
        return names[key], None
    if key in _CATEGORY_ALIASES:
        return tapi.Category[_CATEGORY_ALIASES[key]], None
    # Not a known category -> use it as a free-form custom label.
    return None, value.strip()


@dataclass
class ExpensePreview:
    tricount: str
    description: str
    amount: float
    currency: str
    payer: str
    split_among: list[str]
    category: str | None
    date: str | None = None
    tx_id: int | None = None

    @property
    def per_person(self) -> float:
        return round(self.amount / len(self.split_among), 2) if self.split_among else 0.0


@dataclass
class ReimbursementPreview:
    tricount: str
    frm: str
    to: str
    amount: float
    currency: str
    description: str
    date: str | None = None
    tx_id: int | None = None


@dataclass
class ExpenseRow:
    date: str
    description: str
    payer: str
    amount: float
    currency: str
    category: str | None
    kind: str


@dataclass
class ImportResult:
    line: int
    description: str
    amount: float | None
    action: str  # "expense" | "reimbursement" | "skipped"
    ok: bool
    detail: str
    tx_id: int | None = None


@dataclass
class BalanceReport:
    tricount: str
    title: str
    currency: str
    balances: dict[str, float]
    settlements: list[Payment] = field(default_factory=list)


def _friendly(exc: Exception) -> str:
    return (
        f"Tricount's private (unofficial) API call failed: {exc}. "
        "It may be temporarily down, or the API may have changed — "
        "check for a newer `tricount-api` release."
    )


def _active_members(tc) -> list:
    # Member.status is a plain str; TransactionStatus is a str-mixin enum, so
    # both compare correctly against the literal "ACTIVE".
    return [m for m in tc.members if m.status == "ACTIVE"]


class Core:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg if cfg is not None else cfgmod.load()
        self._client = None
        self._cache: dict[str, tuple[float, object]] = {}

    # -- client & tricount resolution -----------------------------------
    @property
    def client(self):
        if self._client is None:
            self.cfg.credentials_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._client = tapi.load_client(str(self.cfg.credentials_path))
            except Exception as exc:  # noqa: BLE001 - surfaced as a friendly error
                raise ApiError(_friendly(exc)) from exc
        return self._client

    def resolve(self, name: str | None, *, for_write: bool = False, use_cache: bool = True):
        """Fetch a :class:`tricount.Tricount` by config name.

        Reads use ``get_tricount`` (no side effect); writes use ``join_tricount``
        which syncs the tricount so we're allowed to modify it.
        """
        resolved, entry = self.cfg.entry(name)
        token = extract_token(entry.link)
        if use_cache and not for_write:
            hit = self._cache.get(token)
            if hit and (time.monotonic() - hit[0]) < CACHE_TTL:
                return hit[1]
        try:
            tc = self.client.join_tricount(token) if for_write else self.client.get_tricount(token)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(_friendly(exc)) from exc
        self._cache[token] = (time.monotonic(), tc)
        return tc

    def _invalidate(self, tc) -> None:
        self._cache.pop(tc.public_identifier_token, None)

    # -- member helpers -------------------------------------------------
    def _member(self, tc, name: str):
        member = tc.get_member_by_name(name)
        if member is None:
            available = ", ".join(m.display_name for m in _active_members(tc))
            raise CoreError(f"No member named '{name}'. Members: {available}.")
        return member

    def members(self, name: str | None = None) -> list[str]:
        tc = self.resolve(name)
        return [m.display_name for m in _active_members(tc)]

    def info(self, name: str | None = None) -> dict:
        resolved, entry = self.cfg.entry(name)
        tc = self.resolve(name)
        return {
            "name": resolved,
            "title": tc.title,
            "currency": tc.currency,
            "members": [m.display_name for m in _active_members(tc)],
            "me": entry.me,
        }

    # -- writes ---------------------------------------------------------
    def add_expense(
        self,
        *,
        description: str,
        amount: float,
        name: str | None = None,
        payer: str | None = None,
        split: list[str] | None = None,
        category: str | None = None,
        date: str | None = None,
        dry_run: bool = False,
    ) -> ExpensePreview:
        if amount <= 0:
            raise CoreError("Amount must be a positive number.")
        when = parse_date(date)
        resolved, entry = self.cfg.entry(name)
        tc = self.resolve(name, for_write=True)

        payer_name = payer or entry.me
        if not payer_name:
            raise CoreError(
                "No payer given and no 'me' set for this tricount. "
                "Pass --payer or set it via `tricount init`."
            )
        payer_member = self._member(tc, payer_name)

        if split:
            split_members = [self._member(tc, s) for s in split]
        else:
            split_members = _active_members(tc)
        if not split_members:
            raise CoreError("Nobody to split among.")

        cat, cat_custom = resolve_category(category)
        preview = ExpensePreview(
            tricount=resolved,
            description=description,
            amount=float(amount),
            currency=tc.currency,
            payer=payer_member.display_name,
            split_among=[m.display_name for m in split_members],
            category=(cat.name if cat else cat_custom),
            date=(when or datetime.now()).strftime("%Y-%m-%d"),
        )
        if dry_run:
            return preview

        try:
            tx_id = self.client.create_transaction(
                tricount=tc,
                description=description,
                amount=float(amount),
                payer=payer_member,
                split_among=split_members,
                category=cat,
                category_custom=cat_custom,
                date=when,
            )
        except Exception as exc:  # noqa: BLE001
            raise ApiError(_friendly(exc)) from exc
        self._invalidate(tc)
        preview.tx_id = tx_id
        return preview

    def add_reimbursement(
        self,
        *,
        amount: float,
        to: str,
        name: str | None = None,
        frm: str | None = None,
        description: str = "Reimbursement",
        date: str | None = None,
        dry_run: bool = False,
    ) -> ReimbursementPreview:
        if amount <= 0:
            raise CoreError("Amount must be a positive number.")
        when = parse_date(date)
        resolved, entry = self.cfg.entry(name)
        tc = self.resolve(name, for_write=True)

        frm_name = frm or entry.me
        if not frm_name:
            raise CoreError(
                "No payer given and no 'me' set. Pass --from or set it via `tricount init`."
            )
        payer_member = self._member(tc, frm_name)
        receiver_member = self._member(tc, to)
        if payer_member.uuid == receiver_member.uuid:
            raise CoreError("Payer and receiver must be different people.")

        preview = ReimbursementPreview(
            tricount=resolved,
            frm=payer_member.display_name,
            to=receiver_member.display_name,
            amount=float(amount),
            currency=tc.currency,
            description=description,
            date=(when or datetime.now()).strftime("%Y-%m-%d"),
        )
        if dry_run:
            return preview

        try:
            tx_id = self.client.create_reimbursement(
                tricount=tc,
                payer=payer_member,
                receiver=receiver_member,
                amount=float(amount),
                description=description,
                date=when,
            )
        except Exception as exc:  # noqa: BLE001
            raise ApiError(_friendly(exc)) from exc
        self._invalidate(tc)
        preview.tx_id = tx_id
        return preview

    def import_expenses(
        self,
        rows: list[ImportRow],
        *,
        name: str | None = None,
        default_payer: str | None = None,
        dry_run: bool = False,
    ) -> list[ImportResult]:
        """Bulk-create transactions from parsed CSV rows (best-effort, per-row).

        A bad row is reported and skipped; the rest still import. With ``dry_run``
        every row is validated (members, dates, splits) but nothing is sent.
        """
        resolved, entry = self.cfg.entry(name)
        # Reads (dry-run) don't need to join; a real import does.
        tc = self.resolve(name, for_write=not dry_run)
        me = default_payer or entry.me

        results: list[ImportResult] = []
        created = False
        for row in rows:
            try:
                if row.error:
                    raise CoreError(row.error)

                payer_name = row.payer or me
                if not payer_name:
                    raise CoreError("no payer and no default 'me' set")
                payer_member = self._member(tc, payer_name)

                if row.type == "reimbursement":
                    if not row.to:
                        raise CoreError("reimbursement needs a 'to' member")
                    receiver = self._member(tc, row.to)
                    if receiver.uuid == payer_member.uuid:
                        raise CoreError("payer and receiver must differ")
                    detail = f"{payer_member.display_name} → {receiver.display_name}"
                    if not dry_run:
                        tx_id = self.client.create_reimbursement(
                            tricount=tc,
                            payer=payer_member,
                            receiver=receiver,
                            amount=float(row.amount),
                            description=row.description,
                            date=parse_date(row.date),
                        )
                        created = True
                    else:
                        tx_id = None
                    results.append(
                        ImportResult(
                            row.line,
                            row.description,
                            row.amount,
                            "reimbursement",
                            True,
                            detail,
                            tx_id,
                        )
                    )
                else:
                    split_members = (
                        [self._member(tc, s) for s in row.split]
                        if row.split
                        else _active_members(tc)
                    )
                    if not split_members:
                        raise CoreError("nobody to split among")
                    cat, cat_custom = resolve_category(row.category)
                    when = parse_date(row.date)
                    day = (when or datetime.now()).strftime("%Y-%m-%d")
                    detail = (
                        f"paid by {payer_member.display_name}, split {len(split_members)}, {day}"
                    )
                    if not dry_run:
                        tx_id = self.client.create_transaction(
                            tricount=tc,
                            description=row.description,
                            amount=float(row.amount),
                            payer=payer_member,
                            split_among=split_members,
                            category=cat,
                            category_custom=cat_custom,
                            date=when,
                        )
                        created = True
                    else:
                        tx_id = None
                    results.append(
                        ImportResult(
                            row.line, row.description, row.amount, "expense", True, detail, tx_id
                        )
                    )
            except CoreError as exc:
                results.append(
                    ImportResult(row.line, row.description, row.amount, "skipped", False, str(exc))
                )
            except Exception as exc:  # noqa: BLE001 - surface API failure per row
                results.append(
                    ImportResult(
                        row.line, row.description, row.amount, "skipped", False, _friendly(exc)
                    )
                )
        if created:
            self._invalidate(tc)
        return results

    # -- reads ----------------------------------------------------------
    def balances(self, name: str | None = None) -> BalanceReport:
        resolved, _ = self.cfg.entry(name)
        tc = self.resolve(name)
        try:
            raw = self.client.get_balances(tc)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(_friendly(exc)) from exc
        raw = {k: round(v, 2) for k, v in raw.items()}
        return BalanceReport(
            tricount=resolved,
            title=tc.title,
            currency=tc.currency,
            balances=raw,
            settlements=settle(raw),
        )

    def list_expenses(self, name: str | None = None, limit: int = 10) -> list[ExpenseRow]:
        tc = self.resolve(name)
        active = [t for t in tc.transactions if t.status == "ACTIVE"]
        active.sort(key=lambda t: t.date or "", reverse=True)
        rows: list[ExpenseRow] = []
        for tx in active[:limit]:
            payer = tc.get_member_by_uuid(tx.membership_uuid_owner)
            kind = str(getattr(tx.transaction_type, "name", tx.transaction_type))
            rows.append(
                ExpenseRow(
                    date=(tx.date or "")[:10],
                    description=tx.description,
                    payer=payer.display_name if payer else "?",
                    amount=abs(float(tx.amount.value)),
                    currency=tx.amount.currency or tc.currency,
                    category=tx.category_custom or tx.category,
                    kind=kind,
                )
            )
        return rows

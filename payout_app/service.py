"""
service.py - What the payout app does, step by step (no screens, no printing)
=============================================================================

WHAT THIS MODULE DOES
---------------------
The screens (payout_app/ui) and the commands (payout_cli.py) both need the
same few actions. They are kept here once, so a screen and a command can
never behave differently:

    Session()                     who is signed in, and the Google calls
    scan(session, folder, ...)    the daily run -> a ScanReport
    save_match(session, ...)      remember "this printed name is that master
                                  record" in the register's Matches tab
    cancel_invoice(session, ...)  mark an invoice Cancelled
    monthly_tool_matches()        the matches saved in the monthly tool on
                                  this PC, offered for copying (Brinda's PC)

Nothing here shows anything: every action returns plain data and raises
GoogleError (sign-in / internet / sharing) with a message for the user.

THE DAILY RUN (`scan`)
----------------------
    1. Read the masters sheet and check it. Any mistake stops the run:
       nothing is calculated from a wrong master.
    2. Read every PDF in the folder (the slow part; files not changed since
       the last scan in this session are not read again).
    3. Read the register. Put back any calculated cell changed by hand
       (register.verify); a line that cannot be verified stops the run.
    4. Work out the payout lines (engine.calculate) and what has to be
       written (register.plan).
    5. Read the Invoices tab once more just before writing. If another PC
       has posted in the meantime, the plan is made again on the fresh
       rows - so two PCs scanning at the same moment do not post an
       invoice twice.
    6. Write: new payout lines, corrected lines, invoice states, log.
A TRIAL RUN does everything except writing.

CANCELLING AN INVOICE
---------------------
The invoice's row in the Invoices tab gets the state "Cancelled" and the
reason; scans then leave it alone. Its payout lines that are NOT paid get
Status "Cancelled". Lines already paid are left exactly as they are - the
money has gone out - and are reported back so someone can decide what to
do about them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from app.data.paths import database_path
from payout_app import engine, masters_sheet, register, settings
from payout_app.google_api import GoogleError, SheetsClient, sign_in, who
from payout_app.register import I, P


class Session:
    """The signed-in person and the Google connection, made on first use."""

    def __init__(self, client=None, user: str = ""):
        self._client, self._user = client, user
        self.pdf_cache: dict = {}        # engine.read_files cache (this session)

    @property
    def client(self):
        if self._client is None:
            creds = sign_in()
            self._client = SheetsClient(creds)
            self._user = self._user or who(creds)
        return self._client

    @property
    def user(self) -> str:
        _ = self.client
        return self._user

    def forget(self) -> None:
        """After signing out: connect again on the next use."""
        self._client, self._user = None, ""

    @staticmethod
    def masters_id() -> str:
        sheet = settings.get("masters_sheet_id")
        if not sheet:
            raise GoogleError("The masters sheet is not set on this PC yet (Set-up).")
        return sheet

    @staticmethod
    def register_id() -> str:
        sheet = settings.get("register_sheet_id")
        if not sheet:
            raise GoogleError("The payout register is not set on this PC yet (Set-up).")
        return sheet


@dataclass
class ScanReport:
    """Everything one scan found and did."""
    dry_run: bool = False
    stopped: str = ""                    # why nothing was posted ("" = ran through)
    problems: list[str] = field(default_factory=list)      # the reasons, in detail
    notes: list[str] = field(default_factory=list)         # masters / matches notes
    restored: list[str] = field(default_factory=list)      # hand edits put back
    warnings: list[str] = field(default_factory=list)
    posted: list[dict] = field(default_factory=list)       # new payout lines
    corrected: int = 0                                     # lines changed (re-issues)
    review: list[engine.InvoiceResult] = field(default_factory=list)
    issues: list[engine.ReviewIssue] = field(default_factory=list)
    choices: dict[str, list[str]] = field(default_factory=dict)
    not_used: list[engine.InvoiceResult] = field(default_factory=list)
    tally: dict[str, int] = field(default_factory=dict)
    masters_read_at: str = ""
    masters_from_copy: bool = False

    @property
    def posted_total(self) -> float:
        return round(sum(line["amount"] for line in self.posted), 2)


def _line_dict(row: list) -> dict:
    return dict(line_id=row[P["Line ID"]], invoice_no=row[P["Invoice no"]],
                type=row[P["Type"]], payee=row[P["Payee"]], amount=row[P["Amount"]],
                working=row[P["Working"]], customer=row[P["Customer"]], car=row[P["Car"]])


def scan(session: Session, folder: str | Path, dry_run: bool = False,
         start: date | None = None,
         progress: Callable[[int, int, str], None] | None = None,
         now: Callable[[], datetime] = datetime.now) -> ScanReport:
    """The daily run (see module notes)."""
    report = ScanReport(dry_run=dry_run)
    folder = Path(folder)
    if not folder.is_dir():
        report.stopped = f"“{folder}” is not a folder."
        return report
    client, user = session.client, session.user
    masters_id, register_id = session.masters_id(), session.register_id()
    moment = now()

    # 1. masters
    masters = masters_sheet.refresh(lambda: client.read_tabs(masters_id))
    report.masters_read_at, report.masters_from_copy = masters.read_at, masters.from_cache
    if masters.from_cache:
        report.notes += masters.notes[:1]
    if not masters.ok:
        report.stopped = (f"The masters sheet has {len(masters.problems)} problem(s). "
                          "Nothing was calculated.")
        report.problems = list(masters.problems)
        return report

    # 2. the PDFs
    files = engine.read_files(sorted(folder.glob("*.pdf")), progress, session.pdf_cache)

    # 3. the register, hand edits put back
    tabs = client.read_tabs(register_id)
    payouts = tabs.get(register.PAYOUTS) or [list(register.PAYOUT_HEADERS)]
    invoices = tabs.get(register.INVOICES) or [list(register.INVOICE_HEADERS)]
    check = register.verify(payouts, user, moment)
    report.warnings += check.warnings
    if check.problems:
        report.stopped = ("The register has lines that cannot be verified. Nothing "
                          "was posted - please look at these rows.")
        report.problems = list(check.problems)
        return report
    for row, cells in check.payout_updates:
        payouts[row - 1][:len(cells)] = cells
    report.restored = [f"{e[3]}: “{e[4]}” put back to “{e[5]}”" for e in check.log]
    if check.payout_updates and not dry_run:
        client.update_rows(register_id, [(register.PAYOUTS, r, c)
                                         for r, c in check.payout_updates])
        client.append_rows(register_id, register.LOG, check.log)

    # 4. calculate and plan
    outcome = engine.calculate(masters.masters, files,
                               register.matches_from(tabs.get(register.MATCHES) or []))
    report.notes += outcome.notes
    todo = register.plan(payouts, invoices, outcome, user, moment, start)

    # 5. has another PC posted meanwhile?
    if not dry_run and todo.has_writes:
        fresh = client.read_tabs(register_id)
        fresh_invoices = fresh.get(register.INVOICES) or invoices
        if len(fresh_invoices) != len(invoices):
            payouts = fresh.get(register.PAYOUTS) or payouts
            invoices = fresh_invoices
            todo = register.plan(payouts, invoices, outcome, user, moment, start)

    # 6. write
    if not dry_run:
        client.append_rows(register_id, register.PAYOUTS, todo.payout_appends)
        client.update_rows(register_id,
                           [(register.PAYOUTS, r, c) for r, c in todo.payout_updates]
                           + [(register.INVOICES, r, c) for r, c in todo.invoice_updates])
        client.append_rows(register_id, register.INVOICES, todo.invoice_appends)
        client.append_rows(register_id, register.LOG, todo.log)

    report.posted = [_line_dict(r) for r in todo.payout_appends]
    report.corrected = len(todo.payout_updates)
    report.warnings += todo.warnings
    report.tally = todo.tally
    # In review = not posted, not cancelled, not before the start date.
    held = _held_numbers(invoices, todo, outcome, start)
    report.review = [r for r in outcome.of(engine.REVIEW) if r.invoice_no in held]
    report.issues = [engine.ReviewIssue(i.kind, i.printed, i.message,
                                        [n for n in i.invoices if n in held], i.suggestions)
                     for i in outcome.issues if any(n in held for n in i.invoices)]
    report.choices = outcome.choices
    report.not_used = outcome.of(engine.NOT_USED)
    return report


def _held_numbers(invoice_rows: list[list], todo: register.Plan,
                  outcome: engine.Outcome, start: date | None) -> set[str]:
    """Invoice numbers that are in review after this scan."""
    state = {register._s(register._cell(r, I["Invoice no"])):
             register._s(register._cell(r, I["State"])) for r in invoice_rows[1:]}
    for _, row in todo.invoice_updates:
        state[row[I["Invoice no"]]] = row[I["State"]]
    for row in todo.invoice_appends:
        state[row[I["Invoice no"]]] = row[I["State"]]
    held = set()
    for res in outcome.of(engine.REVIEW):
        if start and res.invoice_date and res.invoice_date < start:
            continue
        if state.get(res.invoice_no, register.IN_REVIEW) == register.IN_REVIEW:
            held.add(res.invoice_no)
    return held


# ---------------------------------------------------------------------------
# Review actions
# ---------------------------------------------------------------------------
def save_match(session: Session, kind: str, printed: str, target: str,
               now: Callable[[], datetime] = datetime.now) -> None:
    """
    Remember that `printed` (as on the invoices) is the master record
    `target` (or "Others"). A match already saved for the same kind and
    printed text is replaced. Logged.
    """
    kind, printed, target = kind.strip(), " ".join(printed.split()), target.strip()
    if kind not in register.MATCH_KINDS or not printed or not target:
        raise GoogleError("Choose what the name should be matched to.")
    client, register_id, moment = session.client, session.register_id(), now()
    rows = client.read_tabs(register_id).get(register.MATCHES) or []
    row = [kind, printed, target, session.user, register.stamp(moment)]
    same = next((n for n, r in enumerate(rows[1:], start=2)
                 if register._s(register._cell(r, 0)).lower() == kind.lower()
                 and register._s(register._cell(r, 1)).lower() == printed.lower()), None)
    old = register._s(register._cell(rows[same - 1], 2)) if same else ""
    if same:
        client.update_rows(register_id, [(register.MATCHES, same, row)])
    else:
        client.append_rows(register_id, register.MATCHES, [row])
    client.append_rows(register_id, register.LOG, [[
        register.stamp(moment), session.user, "Match saved",
        f"{kind}: {printed}", old, target]])


def cancel_invoice(session: Session, invoice_no: str, reason: str,
                   now: Callable[[], datetime] = datetime.now) -> list[str]:
    """
    Mark an invoice Cancelled (see module notes). Returns the IDs of its
    lines that were already paid and therefore left as they are.
    """
    reason = " ".join(reason.split())
    if not reason:
        raise GoogleError("Please give the reason for cancelling the invoice.")
    client, register_id, moment = session.client, session.register_id(), now()
    tabs = client.read_tabs(register_id)
    invoices = tabs.get(register.INVOICES) or []
    payouts = tabs.get(register.PAYOUTS) or []
    at = next((n for n, r in enumerate(invoices[1:], start=2)
               if register._s(register._cell(r, I["Invoice no"])) == invoice_no), None)
    if at is None:
        raise GoogleError(f"Invoice {invoice_no} is not in the register yet - "
                          "scan the folder first.")
    row = list(invoices[at - 1]) + [""] * len(register.INVOICE_HEADERS)
    row = row[:len(register.INVOICE_HEADERS)]
    old_state = row[I["State"]]
    row[I["State"]], row[I["Reason"]] = register.CANCELLED, reason
    updates = [(register.INVOICES, at, row)]
    log = [[register.stamp(moment), session.user, "Invoice cancelled", invoice_no,
            str(old_state), reason]]
    paid: list[str] = []
    for n, line in enumerate(payouts[1:], start=2):
        if register._s(register._cell(line, P["Invoice no"])) != invoice_no:
            continue
        status = register._s(register._cell(line, P["Status"]))
        line_id = register._s(register._cell(line, P["Line ID"]))
        if status == register.PAID:
            paid.append(line_id)
        elif status != register.CANCELLED:
            cells = list(line) + [""] * len(register.PAYOUT_HEADERS)
            cells = cells[:len(register.PAYOUT_HEADERS)]
            cells[P["Status"]] = register.CANCELLED
            cells[P["Remarks"]] = f"Invoice cancelled: {reason}"
            updates.append((register.PAYOUTS, n, cells))
            log.append([register.stamp(moment), session.user, "Line cancelled",
                        line_id, status, register.CANCELLED])
    client.update_rows(register_id, updates)
    client.append_rows(register_id, register.LOG, log)
    return paid


# ---------------------------------------------------------------------------
# Matches saved in the monthly tool on this PC
# ---------------------------------------------------------------------------
def monthly_tool_matches(path: str | Path | None = None) -> list[dict]:
    """
    The "applies to every invoice" matches saved on the monthly tool's Scan
    review on THIS PC, as dicts kind / printed / target, ready for
    save_match. Only matches whose target still exists are returned; a
    match to "Others" has the target "Others". The printed text is the
    monthly tool's stored form of the name (lower case), which matches the
    same invoices. Empty when the monthly tool has no database here (a
    staff PC). The monthly tool's database is only read.
    """
    path = Path(path) if path else database_path()
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        aliases = conn.execute(
            "SELECT kind, raw_key, target_id FROM match_aliases ORDER BY kind, raw_key"
        ).fetchall()
        names = {
            "product": {r["id"]: r["name"] for r in conn.execute(
                "SELECT id, name FROM products")},
            "executive": {r["id"]: f"{r['name']} ({r['phone']})" for r in conn.execute(
                "SELECT id, name, phone FROM executives")},
            "car": {r["id"]: " ".join(p for p in (r["make"], r["model"]) if p)
                    for r in conn.execute("SELECT id, make, model FROM cars")},
        }
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    kinds = {"product": "Item", "executive": "Salesperson", "car": "Car"}
    out = []
    for a in aliases:
        if a["kind"] not in kinds or not a["raw_key"]:
            continue
        if a["target_id"] == 0 and a["kind"] != "product":
            target = engine.OTHERS
        else:
            target = names[a["kind"]].get(a["target_id"], "")
        if target:
            out.append(dict(kind=kinds[a["kind"]], printed=a["raw_key"], target=target))
    return out

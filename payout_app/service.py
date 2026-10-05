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
    read_register(session)        payout lines + log, for the Payouts and
                                  History screens
    record_payment(session, ...)  mark lines Paid, with reference / proof
    reopen_payment(session, ...)  undo a recorded payment, with a reason
    set_hold(session, ...)        put lines on hold / release them
    create_proofs_folder(session) the shared Drive folder for proofs (owner)
    clear_register(session, word) start the register afresh (owner)
    find_duplicates(session)      extra copies of the sheets made in testing
    trash_duplicates(session, ids) move chosen extras to Drive's trash

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

PAYMENTS AND PROOFS (v0.17.0)
-----------------------------
`record_payment` marks one or more lines Paid in ONE go - staff often pay a
person for several invoices with a single transfer, so one reference and
one proof may cover many lines. The rules:
    * a REFERENCE or a PROOF is required (Brinda, 05-10-2026);
    * the paid date cannot be in the future;
    * only Pending or Hold lines can be paid. The register is read again
      first, and if any chosen line has meanwhile been paid or cancelled
      (by the other PC), NOTHING is recorded and the lines are named;
    * the proof (a photo, screenshot or PDF, up to 10 MB) is uploaded to
      the shared proofs folder under a name that says what it is -
      "2026-10-05_GPay_UTR123_Kumaran.jpg" - and its link is written on
      every line it covers;
    * only the payment columns are written; every line is logged.
A payment is CORRECTED by reopening it (`reopen_payment`, reason
required): the payment cells are cleared, the line is Pending again and
what it held is kept in the Log. The uploaded proof is not deleted.

THE PROOFS FOLDER (Brinda's choice A, 05-10-2026)
-------------------------------------------------
One Google Drive folder, "Drive N Style Payout Proofs", owned by the
automation account and shared with the staff as Editor - so proofs never
depend on a staff member's own Drive. The owner creates it once from
Set-up; its id is kept in the register's "Setup" tab, so every PC finds it
without being told.

HOUSEKEEPING, FOR THE OWNER (v0.17.1)
-------------------------------------
While the app was being tried out the register filled with trial lines,
test payments and September's invoices, and a few extra sheets were made.
Brinda asked (05-10-2026) for a clean start before go-live:

`clear_register` empties the Payouts, Invoices and Log tabs (headings
stay). Matches, Setup and Summary are kept. Because this cannot be undone
in the sheet:
    * only the OWNER of the register may do it (staff are refused);
    * the word CLEAR must be typed;
    * a BACKUP COPY of the whole register is made first in the owner's
      Drive, named "... - backup dd-mm-yyyy hh.mm", and the first line of
      the fresh Log says who cleared it, when, and where the backup is.
Every PDF then counts as new again, so set the start date on Set-up to
the go-live date before the next scan.

`find_duplicates` lists the owner's own files that carry the exact name of
the masters sheet, the register or the proofs folder, and marks those this
PC uses. `trash_duplicates` moves chosen ones to Drive's TRASH (kept 30
days by Google) - never one that is in use. Backups have another name and
are never listed.

CANCELLING AN INVOICE
---------------------
The invoice's row in the Invoices tab gets the state "Cancelled" and the
reason; scans then leave it alone. Its payout lines that are NOT paid get
Status "Cancelled". Lines already paid are left exactly as they are - the
money has gone out - and are reported back so someone can decide what to
do about them.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from app.data.paths import database_path
from payout_app import engine, masters_sheet, register, settings
from payout_app.google_api import DriveClient, GoogleError, SheetsClient, sign_in, who
from payout_app.register import I, P

PROOF_TYPES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf")
PROOF_MAX_BYTES = 10 * 1024 * 1024


class Session:
    """The signed-in person and the Google connection, made on first use."""

    def __init__(self, client=None, user: str = "", drive=None):
        self._client, self._user, self._drive = client, user, drive
        self._creds = None
        self.pdf_cache: dict = {}        # engine.read_files cache (this session)

    @property
    def client(self):
        if self._client is None:
            self._creds = sign_in()
            self._client = SheetsClient(self._creds)
            self._user = self._user or who(self._creds)
        return self._client

    @property
    def drive(self):
        """Google Drive, for the proofs (made on first use)."""
        if self._drive is None:
            _ = self.client
            self._drive = DriveClient(self._creds or sign_in())
        return self._drive

    @property
    def user(self) -> str:
        _ = self.client
        return self._user

    def forget(self) -> None:
        """After signing out: connect again on the next use."""
        self._client, self._user, self._drive, self._creds = None, "", None, None

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


# ---------------------------------------------------------------------------
# Payments (v0.17.0)
# ---------------------------------------------------------------------------
@dataclass
class RegisterView:
    """What the Payouts and History screens show."""
    lines: list[dict] = field(default_factory=list)       # register.payout_lines
    log: list[list] = field(default_factory=list)         # newest first
    proofs_folder: str = ""                               # its id ("" = not set up)


def read_register(session: Session) -> RegisterView:
    tabs = session.client.read_tabs(session.register_id())
    log = [r + [""] * (len(register.LOG_HEADERS) - len(r))
           for r in (tabs.get(register.LOG) or [])[1:] if any(str(c).strip() for c in r)]
    return RegisterView(register.payout_lines(tabs.get(register.PAYOUTS) or []),
                        list(reversed(log)),
                        register.setup_value(tabs.get(register.SETUP), register.PROOFS_KEY))


def proof_name(paid_date: date, mode: str, reference: str, payees: list[str],
               extension: str) -> str:
    """
    A file name that says what the proof is:
    "2026-10-05_GPay_UTR123_Kumaran.jpg". Several payees -> "3-payees";
    labour (no payee) -> "Labour". Characters Windows / Drive dislike go.
    """
    names = sorted({p for p in payees if p})
    who_for = names[0] if len(names) == 1 else (f"{len(names)}-payees" if names else "Labour")
    parts = [paid_date.strftime("%Y-%m-%d"), mode, reference, who_for]
    clean = [re.sub(r"[^A-Za-z0-9.-]+", "-", p).strip("-") for p in parts if p]
    return "_".join(c for c in clean if c)[:120] + extension.lower()


def _check_proof(path: str | Path) -> Path:
    path = Path(path)
    if not path.is_file():
        raise GoogleError(f"The proof file “{path}” was not found.")
    if path.suffix.lower() not in PROOF_TYPES:
        raise GoogleError("The proof must be a picture or a PDF "
                          f"({', '.join(t.lstrip('.') for t in PROOF_TYPES)}).")
    if path.stat().st_size > PROOF_MAX_BYTES:
        raise GoogleError("The proof file is larger than 10 MB. Please use a smaller "
                          "picture or PDF.")
    return path


def _fresh_lines(session: Session, line_ids: list[str]) -> tuple[list[dict], dict]:
    """The chosen lines as they are in the register NOW, and all the tabs."""
    tabs = session.client.read_tabs(session.register_id())
    by_id = {l["line_id"]: l for l in register.payout_lines(tabs.get(register.PAYOUTS) or [])}
    missing = [i for i in line_ids if i not in by_id]
    if missing:
        raise GoogleError("These lines are no longer in the register: "
                          + ", ".join(missing) + ". Refresh and try again.")
    return [by_id[i] for i in line_ids], tabs


def record_payment(session: Session, line_ids: list[str], paid_date: date, mode: str,
                   reference: str = "", proof_path: str | Path = "", remarks: str = "",
                   now: Callable[[], datetime] = datetime.now) -> str:
    """
    Mark the lines Paid (see module notes). Returns the proof's link ("" if
    none was given). Raises GoogleError - and records nothing - when a rule
    is not met.
    """
    line_ids = list(dict.fromkeys(line_ids))
    mode, reference = " ".join(mode.split()), " ".join(reference.split())
    remarks, moment = " ".join(remarks.split()), now()
    if not line_ids:
        raise GoogleError("Tick the lines that were paid first.")
    if not mode:
        raise GoogleError("Choose how it was paid (Cash, GPay ...).")
    if not reference and not proof_path:
        raise GoogleError("A payment needs a reference number or a proof.")
    if paid_date > moment.date():
        raise GoogleError("The paid date cannot be in the future.")
    proof = _check_proof(proof_path) if proof_path else None

    lines, tabs = _fresh_lines(session, line_ids)
    not_open = [f"{l['line_id']} ({l['status']})" for l in lines
                if l["status"] not in (register.PENDING, register.HOLD)]
    if not_open:
        raise GoogleError("Nothing was recorded. These lines are not waiting for "
                          "payment any more: " + ", ".join(not_open) + ".")
    link = ""
    if proof is not None:
        folder = register.setup_value(tabs.get(register.SETUP), register.PROOFS_KEY)
        if not folder:
            raise GoogleError("The proofs folder is not set up yet. It is created once "
                              "on Set-up, on the owner's PC.")
        link = session.drive.upload(
            proof, proof_name(paid_date, mode, reference, [l["payee"] for l in lines],
                              proof.suffix), folder)
    cells = register.payment_cells(register.PAID, paid_date, mode, reference, link,
                                   remarks, session.user, moment)
    session.client.update_ranges(session.register_id(), [
        (register.PAYOUTS, register.payment_range(l["row"]), [cells]) for l in lines])
    paid = dict(status=register.PAID, paid_date=paid_date, mode=mode,
                reference=reference, proof=link)
    session.client.append_rows(session.register_id(), register.LOG, [
        [register.stamp(moment), session.user, "Payment recorded", l["line_id"],
         l["status"], register.payment_summary(paid)] for l in lines])
    return link


def reopen_payment(session: Session, line_ids: list[str], reason: str,
                   now: Callable[[], datetime] = datetime.now) -> None:
    """Undo recorded payments: the lines are Pending again; logged with the reason."""
    reason, moment = " ".join(reason.split()), now()
    if not line_ids:
        raise GoogleError("Tick the paid lines to reopen first.")
    if not reason:
        raise GoogleError("Please give the reason for reopening the payment.")
    lines, _ = _fresh_lines(session, list(dict.fromkeys(line_ids)))
    not_paid = [f"{l['line_id']} ({l['status']})" for l in lines
                if l["status"] != register.PAID]
    if not_paid:
        raise GoogleError("Only paid lines can be reopened. Not paid: "
                          + ", ".join(not_paid) + ".")
    cells = register.payment_cells(register.PENDING, remarks=f"Reopened: {reason}",
                                   who=session.user, now=moment)
    session.client.update_ranges(session.register_id(), [
        (register.PAYOUTS, register.payment_range(l["row"]), [cells]) for l in lines])
    session.client.append_rows(session.register_id(), register.LOG, [
        [register.stamp(moment), session.user, "Payment reopened", l["line_id"],
         register.payment_summary(l), f"Pending - {reason}"] for l in lines])


def set_hold(session: Session, line_ids: list[str], hold: bool, reason: str = "",
             now: Callable[[], datetime] = datetime.now) -> None:
    """Put Pending lines on Hold (reason required), or release held lines."""
    reason, moment = " ".join(reason.split()), now()
    if not line_ids:
        raise GoogleError("Tick the lines first.")
    if hold and not reason:
        raise GoogleError("Please give the reason for holding the payment.")
    lines, _ = _fresh_lines(session, list(dict.fromkeys(line_ids)))
    wanted = register.PENDING if hold else register.HOLD
    wrong = [f"{l['line_id']} ({l['status']})" for l in lines if l["status"] != wanted]
    if wrong:
        raise GoogleError(("Only pending lines can be put on hold: " if hold else
                           "Only held lines can be released: ") + ", ".join(wrong) + ".")
    new = register.HOLD if hold else register.PENDING
    cells = register.payment_cells(new, remarks=f"On hold: {reason}" if hold else "",
                                   who=session.user, now=moment)
    session.client.update_ranges(session.register_id(), [
        (register.PAYOUTS, register.payment_range(l["row"]), [cells]) for l in lines])
    session.client.append_rows(session.register_id(), register.LOG, [
        [register.stamp(moment), session.user,
         "Put on hold" if hold else "Hold released", l["line_id"], l["status"],
         f"{new} - {reason}" if reason else new] for l in lines])


def create_proofs_folder(session: Session,
                         now: Callable[[], datetime] = datetime.now) -> tuple[str, str]:
    """
    Make the shared proofs folder in the signed-in person's Drive (do this
    as the owner account) and note it in the register's Setup tab. If the
    register already names a folder that can be opened, that one is kept.
    Returns (folder name, link).
    """
    client, register_id = session.client, session.register_id()
    tabs = client.read_tabs(register_id)
    known = register.setup_value(tabs.get(register.SETUP), register.PROOFS_KEY)
    link = "https://drive.google.com/drive/folders/{}"
    if known:
        return session.drive.folder_name(known), link.format(known)
    folder_id, url = session.drive.create_folder(register.PROOFS_FOLDER_NAME)
    setup = tabs.get(register.SETUP)
    if setup is None:              # a register made before v0.17.0
        client.add_tab(register_id, register.SETUP,
                       [list(register.SETUP_HEADERS), [register.PROOFS_KEY, folder_id]])
    else:
        at = next((n for n, r in enumerate(setup[1:], start=2)
                   if register._s(register._cell(r, 0)).lower()
                   == register.PROOFS_KEY.lower()), None)
        if at:
            client.update_rows(register_id, [(register.SETUP, at,
                                              [register.PROOFS_KEY, folder_id])])
        else:
            client.append_rows(register_id, register.SETUP,
                               [[register.PROOFS_KEY, folder_id]])
    client.append_rows(register_id, register.LOG, [[
        register.stamp(now()), session.user, "Proofs folder created",
        register.PROOFS_FOLDER_NAME, "", url]])
    return register.PROOFS_FOLDER_NAME, url


# ---------------------------------------------------------------------------
# Housekeeping for the owner (v0.17.1)
# ---------------------------------------------------------------------------
CLEAR_WORD = "CLEAR"
CLEARED_TABS = (register.PAYOUTS, register.INVOICES, register.LOG)
FOLDER_TYPE = "application/vnd.google-apps.folder"


def clear_register(session: Session, typed: str,
                   now: Callable[[], datetime] = datetime.now) -> tuple[str, dict]:
    """
    Start the register afresh (see module notes). `typed` must be CLEAR.
    Returns (link of the backup copy, how many rows were removed per tab).
    """
    if typed.strip() != CLEAR_WORD:
        raise GoogleError(f"Nothing was cleared - type {CLEAR_WORD} to confirm.")
    client, register_id, moment = session.client, session.register_id(), now()
    if not session.drive.owned_by_me(register_id):
        raise GoogleError("Only the owner of the payout register can clear it. Sign in "
                          "as the owner account on Set-up.")
    tabs = client.read_tabs(register_id)
    removed = {tab: max(len([r for r in (tabs.get(tab) or [])[1:]
                             if any(str(c).strip() for c in r)]), 0)
               for tab in CLEARED_TABS}
    backup = session.drive.copy(
        register_id, f"{register.SHEET_TITLE} - backup {moment:%d-%m-%Y %H.%M}")
    client.clear_rows(register_id, list(CLEARED_TABS))
    client.append_rows(register_id, register.LOG, [[
        register.stamp(moment), session.user, "Register cleared",
        f"{removed[register.PAYOUTS]} payout line(s), "
        f"{removed[register.INVOICES]} invoice(s), {removed[register.LOG]} log entries",
        "", f"Backup: {backup}"]])
    session.pdf_cache.clear()
    return backup, removed


def find_duplicates(session: Session) -> list[dict]:
    """
    The signed-in person's own files named like the masters sheet, the
    register or the proofs folder (see module notes), oldest first:
    id, name, kind (Sheet / Folder), created (dd-mm-yyyy hh:mm), link,
    in_use (True = this PC uses it - it cannot be trashed).
    """
    used = {settings.get("masters_sheet_id"), settings.get("register_sheet_id")}
    if settings.get("register_sheet_id"):
        tabs = session.client.read_tabs(session.register_id())
        used.add(register.setup_value(tabs.get(register.SETUP), register.PROOFS_KEY))
    used.discard("")
    names = [masters_sheet.SHEET_TITLE, register.SHEET_TITLE, register.PROOFS_FOLDER_NAME]
    out = []
    for f in session.drive.list_named(names):
        created = str(f.get("createdTime", ""))
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00")) \
                .astimezone().strftime("%d-%m-%Y %H:%M")
        except ValueError:
            pass
        out.append(dict(id=f["id"], name=f.get("name", ""),
                        kind="Folder" if f.get("mimeType") == FOLDER_TYPE else "Sheet",
                        created=created, link=f.get("webViewLink", ""),
                        in_use=f["id"] in used))
    return out


def trash_duplicates(session: Session, files: list[dict],
                     now: Callable[[], datetime] = datetime.now) -> int:
    """
    Move the chosen files (dicts from find_duplicates) to Drive's trash.
    The list is fetched again first: a file that is in use, or that is no
    longer among the duplicates, is refused and nothing is trashed.
    """
    if not files:
        raise GoogleError("Tick the files to move to the trash first.")
    current = {f["id"]: f for f in find_duplicates(session)}
    wrong = [f["name"] for f in files
             if f["id"] not in current or current[f["id"]]["in_use"]]
    if wrong:
        raise GoogleError("Nothing was moved. A chosen file is in use on this PC or "
                          "is no longer in the list - press Find again.")
    for f in files:
        session.drive.trash(f["id"])
    if settings.get("register_sheet_id"):
        moment = now()
        session.client.append_rows(session.register_id(), register.LOG, [
            [register.stamp(moment), session.user, "Duplicate moved to trash",
             f"{current[f['id']]['kind']}: {f['name']}", current[f["id"]]["link"], ""]
            for f in files])
    return len(files)

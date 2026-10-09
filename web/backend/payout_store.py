"""
payout_store.py - The daily payout register, kept in the database (v0.27.0)
===========================================================================

WHAT THIS MODULE DOES
---------------------
On the desktop the payout app posted its lines to a Google Sheet. On the
web the register is two database tables (payout_lines, payout_invoices).
This module is the bridge. It does three things and decides NOTHING about
money or posting itself:

    1. hands the register to the payout app's own rules as the same rows
       the Google Sheet held, and writes back what they decide
           payout_app/engine.py     what each invoice's lines are
           payout_app/register.py   post once / in review / re-issued /
                                    adjustment lines / cancelled
    2. records payments by the rules of payout_app/service.py, word for
       word: Paid needs a reference or a proof; only Pending or Hold lines
       can be paid; a Paid line is changed only by reopening it with a
       reason; Hold needs a reason; nothing is overwritten silently
    3. writes every change to the audit log (master "payouts") with the
       e-mail of the signed-in person

WHAT IS SIMPLER THAN ON THE DESKTOP
    * No "Check" seal to verify: nobody can type into a database column,
      so a calculated amount cannot be changed by hand.
    * No two-PC race: the server does the posting, inside one database
      transaction, and line_id / invoice_no are UNIQUE.

THE MASTERS AND THE SAVED MATCHES ARE SHARED WITH THE MONTHLY TOOL
(Brinda, 09-10-2026). A scan works on a throw-away copy of the database
held in memory (`working_copy`): the real masters, the saved name matches,
the single-invoice choices and the accepted totals differences - but not
the monthly tool's invoices, because engine.calculate stores the scanned
invoices beside the masters while it works. So:
    * a name fixed on the monthly Scan review is known to the daily scan,
      and a name fixed on the daily Review is known to the monthly tool;
    * a scan can never disturb a month read into the monthly tool.

RATES: each line is posted with the rate in force on the invoice date and
keeps it. An invoice already Posted is never calculated again, so a master
changed later does not alter a posted line (register.plan).

START DATE: invoices dated before it are left alone ("no back-posting").
Kept in the meta table as payout_start_date; 01-10-2026 until changed.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from app.data.invoices_repo import OTHERS_CHOICE, OTHERS_ID, InvoicesRepo
from app.data.masters_repo import MastersRepo
from payout_app import engine, register
from payout_app.register import I, P

DEFAULT_START = date(2026, 10, 1)          # go-live (Brinda, 09-10-2026)
START_KEY = "payout_start_date"
MASTER = "payouts"                         # the name used in the audit log
SOURCE = "Daily payouts"


class PayoutError(Exception):
    """A plain-language reason nothing was recorded."""


def _clean(text: str) -> str:
    return " ".join(str(text or "").split())


def working_copy(conn: sqlite3.Connection, user: str) -> MastersRepo:
    """
    A copy of the database in memory for ONE calculation: masters and saved
    matches as they are now, without the monthly tool's invoices (see the
    module notes). Thrown away after the scan.
    """
    memory = sqlite3.connect(":memory:")
    conn.backup(memory)
    memory.row_factory = sqlite3.Row
    memory.execute("PRAGMA foreign_keys = ON")
    with memory:
        for table in ("invoice_checks", "invoice_lines", "invoices", "scan_files", "scan_runs"):
            memory.execute(f"DELETE FROM {table}")
    return MastersRepo(memory, user=user)


class PayoutStore:
    """The register in the open database connection `conn`, for `user`."""

    def __init__(self, conn: sqlite3.Connection, user: str):
        self.conn, self.user = conn, user
        self.masters = MastersRepo(conn, user=user)

    # ---- the register as rows (row 1 = headings, as in the sheet) ---------------
    def _rows(self, table: str, headers: list[str]) -> tuple[list[int], list[list]]:
        ids, rows = [], [list(headers)]
        for r in self.conn.execute(f"SELECT id, cells FROM {table} ORDER BY id"):
            ids.append(r["id"])
            rows.append(json.loads(r["cells"]))
        return ids, rows

    def payout_rows(self) -> tuple[list[int], list[list]]:
        return self._rows("payout_lines", register.PAYOUT_HEADERS)

    def invoice_rows(self) -> tuple[list[int], list[list]]:
        return self._rows("payout_invoices", register.INVOICE_HEADERS)

    def lines(self) -> list[dict]:
        """Every payout line as a dict (register.payout_lines), oldest first."""
        return register.payout_lines(self.payout_rows()[1])

    def invoices(self) -> list[dict]:
        out = []
        for row in self.invoice_rows()[1][1:]:
            cell = lambda name: register._cell(row, I[name])           # noqa: E731
            out.append({"invoice_no": register._s(cell("Invoice no")),
                        "invoice_date": register._day(cell("Invoice date")),
                        "customer": register._s(cell("Customer")),
                        "total": register._amount(cell("Total")),
                        "salesperson": register._s(cell("Salesperson")),
                        "file_name": register._s(cell("File name")),
                        "state": register._s(cell("State")),
                        "reason": register._s(cell("Reason")),
                        "scanned_by": register._s(cell("Scanned by")),
                        "scanned_at": register._s(cell("Scanned at"))})
        return out

    # ---- writing ------------------------------------------------------------------
    def _log(self, what: str, record: str, old: str = "", new: str = "") -> None:
        """One audit entry. Same transaction as the change it describes."""
        action = "Added" if what == "Posted" else "Deleted" if "cancelled" in what.lower() \
            else "Edited"
        self.masters._audit(MASTER, None, record, action, what, str(old), str(new), SOURCE)

    def _put_line(self, row_id: int | None, cells: list) -> None:
        cells = (list(cells) + [""] * len(register.PAYOUT_HEADERS))[:len(register.PAYOUT_HEADERS)]
        line_id, invoice = register._s(cells[P["Line ID"]]), register._s(cells[P["Invoice no"]])
        if row_id is None:
            self.conn.execute("INSERT INTO payout_lines(line_id, invoice_no, cells) "
                              "VALUES (?, ?, ?)", (line_id, invoice, json.dumps(cells)))
        else:
            self.conn.execute("UPDATE payout_lines SET line_id = ?, invoice_no = ?, cells = ? "
                              "WHERE id = ?", (line_id, invoice, json.dumps(cells), row_id))

    def _put_invoice(self, row_id: int | None, cells: list) -> None:
        number = register._s(cells[I["Invoice no"]])
        if row_id is None:
            self.conn.execute("INSERT INTO payout_invoices(invoice_no, cells) VALUES (?, ?)",
                              (number, json.dumps(list(cells))))
        else:
            self.conn.execute("UPDATE payout_invoices SET invoice_no = ?, cells = ? "
                              "WHERE id = ?", (number, json.dumps(list(cells)), row_id))

    # ---- settings --------------------------------------------------------------------
    def start_date(self) -> date:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (START_KEY,)).fetchone()
        return date.fromisoformat(row["value"]) if row else DEFAULT_START

    def set_start_date(self, day: date) -> None:
        old = self.start_date()
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                              (START_KEY, day.isoformat()))
            if old != day:
                self._log("Start date", "Register settings", f"{old:%d-%m-%Y}", f"{day:%d-%m-%Y}")

    # ---- the daily run -----------------------------------------------------------------
    def calculate(self, files: list) -> engine.Outcome:
        """Work the files out on a throw-away copy; nothing is written."""
        return engine.calculate(working_copy(self.conn, self.user), files, [])

    def scan(self, files: list, now: datetime | None = None) -> dict:
        """
        Post what the files give. `files` = engine.read_files' result:
        (file name, invoice or None, reason). Returns the report the Scan
        screen shows. One transaction: either everything of this scan is
        written, or nothing.
        """
        now = now or datetime.now()
        outcome = self.calculate(files)                  # the slow part, outside the lock
        self.conn.execute("BEGIN IMMEDIATE")             # one scan writes at a time
        try:
            line_ids, payout_rows = self.payout_rows()
            invoice_ids, invoice_rows = self.invoice_rows()
            todo = register.plan(payout_rows, invoice_rows, outcome, self.user, now,
                                 self.start_date())
            if todo.problems:
                raise PayoutError("Nothing was posted. " + " ".join(todo.problems))
            for row, cells in todo.payout_updates:        # row = sheet row; headings = 1
                self._put_line(line_ids[row - 2], cells)
            for cells in todo.payout_appends:
                self._put_line(None, cells)
            for row, cells in todo.invoice_updates:
                self._put_invoice(invoice_ids[row - 2], cells)
            for cells in todo.invoice_appends:
                self._put_invoice(None, cells)
            for _, _, what, record, old, new in todo.log:
                self._log(what, record, old, new)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        posted = register.payout_lines([register.PAYOUT_HEADERS] + todo.payout_appends)
        # "In review" on the screen = what the REGISTER now holds as In
        # review. An invoice the scan left alone (before the start date,
        # cancelled) is not shown as waiting, even if it could not be
        # calculated.
        waiting = self.waiting_numbers()
        return {
            "tally": todo.tally, "posted": posted,
            "posted_total": round(sum(l["amount"] for l in posted), 2),
            "corrected": len(todo.payout_updates),
            "review": [{"file_name": r.file_name, "invoice_no": r.invoice_no,
                        "reasons": r.reasons} for r in outcome.of(engine.REVIEW)
                       if r.invoice_no in waiting],
            "not_used": [{"file_name": r.file_name, "reasons": r.reasons}
                         for r in outcome.of(engine.NOT_USED)],
            "issues": issues_for_screen(outcome, waiting),
            "warnings": todo.warnings, "notes": outcome.notes}

    def waiting_numbers(self) -> set[str]:
        """Invoice numbers the register holds as In review."""
        return {i["invoice_no"] for i in self.invoices() if i["state"] == register.IN_REVIEW}

    # ---- Review: saved matches (shared with the monthly tool) ---------------------------
    def save_match(self, kind: str, printed: str, invoices: list[str], target_id: int) -> str:
        """
        "This printed name is that master record" - saved with the monthly
        tool's own functions, so it applies to both tools and is in the
        audit log as a Scan review fix. A name that is printed is saved for
        EVERY invoice showing it; a salesperson / vehicle that is not
        printed at all can only be chosen invoice by invoice.
        """
        repo, printed = InvoicesRepo(self.masters), _clean(printed)
        if kind == "Item":
            product = self.masters.get("products", target_id)
            if product is None or not printed:
                raise PayoutError("Choose a product from the list.")
            repo.map_product(printed, target_id)
            return f"“{printed}” will be read as {product['name']}."
        if kind not in ("Salesperson", "Car"):
            raise PayoutError("This entry cannot be matched to a master record.")
        master = "executives" if kind == "Salesperson" else "cars"
        row = None if target_id == OTHERS_ID else self.masters.get(master, target_id)
        if target_id != OTHERS_ID and row is None:
            raise PayoutError("Choose a " + ("sales executive" if kind == "Salesperson" else "car")
                              + " from the list.")
        name = OTHERS_CHOICE if target_id == OTHERS_ID else MastersRepo.display_name(master, row)
        save = repo.set_salesperson if kind == "Salesperson" else repo.set_car
        if printed:
            save("", printed, target_id, True)
            return f"{name} set for all invoices showing “{printed}”."
        if not invoices:
            raise PayoutError("Say which invoice this is for.")
        for number in invoices:
            save(number, "", target_id, False)
        return f"{name} set for invoice {', '.join(invoices)}."

    def accept_totals(self, invoice_no: str) -> str:
        InvoicesRepo(self.masters).acknowledge(invoice_no, "totals")
        return f"Invoice {invoice_no} accepted."

    # ---- cancelling an invoice (service.cancel_invoice) ----------------------------------
    def cancel_invoice(self, invoice_no: str, reason: str) -> list[str]:
        """Mark an invoice Cancelled; its unpaid lines are cancelled. Returns
        the IDs of lines already PAID, which are left exactly as they are."""
        reason = _clean(reason)
        if not reason:
            raise PayoutError("Please give the reason for cancelling the invoice.")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            invoice_ids, invoice_rows = self.invoice_rows()
            at = next((n for n, r in enumerate(invoice_rows[1:])
                       if register._s(register._cell(r, I["Invoice no"])) == invoice_no), None)
            if at is None:
                raise PayoutError(f"Invoice {invoice_no} is not in the register yet - "
                                  "scan it first.")
            row = (list(invoice_rows[at + 1]) + [""] * len(register.INVOICE_HEADERS))
            row = row[:len(register.INVOICE_HEADERS)]
            old_state = row[I["State"]]
            row[I["State"]], row[I["Reason"]] = register.CANCELLED, reason
            self._put_invoice(invoice_ids[at], row)
            self._log("Invoice cancelled", invoice_no, str(old_state), reason)
            paid = []
            line_ids, payout_rows = self.payout_rows()
            for row_id, line in zip(line_ids, payout_rows[1:]):
                if register._s(register._cell(line, P["Invoice no"])) != invoice_no:
                    continue
                status = register._s(register._cell(line, P["Status"]))
                lid = register._s(register._cell(line, P["Line ID"]))
                if status == register.PAID:
                    paid.append(lid)
                elif status != register.CANCELLED:
                    cells = (list(line) + [""] * len(register.PAYOUT_HEADERS))
                    cells = cells[:len(register.PAYOUT_HEADERS)]
                    cells[P["Status"]] = register.CANCELLED
                    cells[P["Remarks"]] = f"Invoice cancelled: {reason}"
                    self._put_line(row_id, cells)
                    self._log("Line cancelled", lid, status, register.CANCELLED)
            self.conn.commit()
            return paid
        except BaseException:
            self.conn.rollback()
            raise

    # ---- payments (service.record_payment / reopen_payment / set_hold) ------------------
    def _change_payment(self, line_ids: list[str], allowed: tuple, refusal: str,
                        cells_for, log_for) -> list[dict]:
        """
        Write the payment cells of the chosen lines - and ONLY those cells
        (Status ... Entered at), never a calculated one. The lines are read
        again inside the lock: if any of them is no longer in a state that
        allows the change, nothing at all is written.
        """
        line_ids = list(dict.fromkeys(line_ids))
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            ids, rows = self.payout_rows()
            by_id = {l["line_id"]: (ids[l["row"] - 2], rows[l["row"] - 1], l)
                     for l in register.payout_lines(rows)}
            missing = [i for i in line_ids if i not in by_id]
            if missing:
                raise PayoutError("These lines are no longer in the register: "
                                  + ", ".join(missing) + ". Refresh and try again.")
            wrong = [f"{i} ({by_id[i][2]['status']})" for i in line_ids
                     if by_id[i][2]["status"] not in allowed]
            if wrong:
                raise PayoutError(refusal + ", ".join(wrong) + ".")
            done = []
            for i in line_ids:
                row_id, row, line = by_id[i]
                cells = (list(row) + [""] * len(register.PAYOUT_HEADERS))
                cells = cells[:len(register.PAYOUT_HEADERS)]
                cells[register.PAYMENT_FIRST:register.PAYMENT_LAST + 1] = cells_for(line)
                self._put_line(row_id, cells)
                self._log(*log_for(line))
                done.append(line)
            self.conn.commit()
            return done
        except BaseException:
            self.conn.rollback()
            raise

    def check_payment(self, line_ids: list[str], paid_date: date, mode: str, reference: str,
                      has_proof: bool, now: datetime) -> None:
        """The rules that need no register (so a proof is not stored for a
        payment that would be refused anyway)."""
        if not line_ids:
            raise PayoutError("Tick the lines that were paid first.")
        if not _clean(mode):
            raise PayoutError("Choose how it was paid (Cash, GPay ...).")
        if not _clean(reference) and not has_proof:
            raise PayoutError("A payment needs a reference number or a proof.")
        if paid_date > now.date():
            raise PayoutError("The paid date cannot be in the future.")

    def record_payment(self, line_ids: list[str], paid_date: date, mode: str,
                       reference: str = "", proof: str = "", remarks: str = "",
                       now: datetime | None = None) -> list[dict]:
        """Mark lines Paid. `proof` = the stored proof's file name ("" = none)."""
        now = now or datetime.now()
        mode, reference, remarks = _clean(mode), _clean(reference), _clean(remarks)
        self.check_payment(line_ids, paid_date, mode, reference, bool(proof), now)
        cells = register.payment_cells(register.PAID, paid_date, mode, reference, proof,
                                       remarks, self.user, now)
        paid = dict(status=register.PAID, paid_date=paid_date, mode=mode,
                    reference=reference, proof=proof)
        return self._change_payment(
            line_ids, (register.PENDING, register.HOLD),
            "Nothing was recorded. These lines are not waiting for payment any more: ",
            lambda line: cells,
            lambda line: ("Payment recorded", line["line_id"], line["status"],
                          register.payment_summary(paid)))

    def reopen_payment(self, line_ids: list[str], reason: str,
                       now: datetime | None = None) -> list[dict]:
        now, reason = now or datetime.now(), _clean(reason)
        if not line_ids:
            raise PayoutError("Tick the paid lines to reopen first.")
        if not reason:
            raise PayoutError("Please give the reason for reopening the payment.")
        cells = register.payment_cells(register.PENDING, remarks=f"Reopened: {reason}",
                                       who=self.user, now=now)
        return self._change_payment(
            line_ids, (register.PAID,), "Only paid lines can be reopened. Not paid: ",
            lambda line: cells,
            lambda line: ("Payment reopened", line["line_id"],
                          register.payment_summary(line), f"Pending - {reason}"))

    def set_hold(self, line_ids: list[str], hold: bool, reason: str = "",
                 now: datetime | None = None) -> list[dict]:
        now, reason = now or datetime.now(), _clean(reason)
        if not line_ids:
            raise PayoutError("Tick the lines first.")
        if hold and not reason:
            raise PayoutError("Please give the reason for holding the payment.")
        new = register.HOLD if hold else register.PENDING
        cells = register.payment_cells(new, remarks=f"On hold: {reason}" if hold else "",
                                       who=self.user, now=now)
        return self._change_payment(
            line_ids, (register.PENDING,) if hold else (register.HOLD,),
            "Only pending lines can be put on hold: " if hold
            else "Only held lines can be released: ",
            lambda line: cells,
            lambda line: ("Put on hold" if hold else "Hold released", line["line_id"],
                          line["status"], f"{new} - {reason}" if reason else new))

    # ---- starting afresh (admin) -----------------------------------------------------------
    def clear(self) -> tuple[int, int]:
        """Empty the register (lines and invoices). The caller has made the
        backup and checked the word CLEAR. The audit log keeps everything."""
        with self.conn:
            lines = self.conn.execute("DELETE FROM payout_lines").rowcount
            invoices = self.conn.execute("DELETE FROM payout_invoices").rowcount
            self._log("Register cleared", "Payout register", f"{lines} line(s), "
                      f"{invoices} invoice(s)", "empty")
        return lines, invoices


def issues_for_screen(outcome: engine.Outcome, waiting: set[str]) -> list[dict]:
    """The things to decide, each with the WAITING invoices it holds up
    (an issue that only concerns invoices the register left alone is dropped)."""
    out = []
    for issue in outcome.issues:
        held = [n for n in issue.invoices if n in waiting]
        if held:
            out.append({"kind": issue.kind, "printed": issue.printed, "message": issue.message,
                        "invoices": held, "suggestions": issue.suggestions})
    return out

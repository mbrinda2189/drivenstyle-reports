"""
register.py - The payout register (a Google Sheet): layout, posting, checks
===========================================================================

WHAT THIS MODULE DOES
---------------------
The payout register is the second Google Sheet, "Drive N Style Payout
Register". The app posts the calculated lines to it and the staff record
there that each amount was paid. Like masters_sheet.py this module holds
NO Google code: it works on rows, decides what has to be written, and
payout_cli.py sends those writes through google_api.py.

    new_register_tabs()        the empty sheet: tabs and headings
    register_layout()          how its columns are formatted
    verify(payout_rows)        find calculated cells changed by hand
    plan(...)                  what one scan has to write (a `Plan`)
    matches_from(rows)         the saved matches for engine.calculate
    pending_by_payee(rows)     totals for the "status" command
    payout_lines(rows)         the Payouts tab as a list of lines (v0.17.0)
    payment_cells(...)         the cells written when a line is paid,
                               reopened, held or released

THE TABS
--------
Payouts   one row per payout line
          Calculated by the app (never typed):
              Line ID | Invoice no | Invoice date | Customer | Car | Type |
              Payee | Amount | Working | Calculated on
          Filled when the amount is paid:
              Status (Pending / Paid / Hold / Cancelled) | Paid date | Mode |
              Reference | Proof | Remarks | Entered by | Entered at
          Check   (hidden) the app's own sealed copy of the calculated cells
Invoices  one row per invoice the app has seen
              Invoice no | Invoice date | Customer | Total | Salesperson |
              File name | State | Reason | Lines | Scanned by | Scanned at |
              Print   (hidden: fingerprint of what the PDF says,
                      engine.invoice_print)
          State: Posted / In review / Re-issued / Cancelled
Matches   printed names matched to a master record (see engine.py)
              Kind | Printed on invoice | Master record | Added by | Added on
Log       every change the app makes: When | Who | What | Record | Old | New
Summary   pending and paid totals (formulas over Payouts)
Setup     settings every PC shares: Key | Value. So far "Proofs folder" -
          the Google Drive folder the payment proofs are uploaded to.

RECORDING A PAYMENT (v0.17.0)
-----------------------------
Only the payment columns of a line are ever written when it is paid
(Status ... Entered at, columns K to R) - never the calculated ones, so a
payment can not disturb an amount. The rules (enforced in service.py):
    * Paid needs a REFERENCE or a PROOF (Brinda, 05-10-2026);
    * only a Pending or Hold line can be paid;
    * a Paid line is changed by REOPENING it with a reason: its payment
      cells are cleared, the line is Pending again, and what it held goes
      to the Log. It is then recorded afresh. Nothing is overwritten
      silently;
    * Hold keeps a line out of the "to pay" list, with a reason.

POSTING RULES (`plan`)
----------------------
    * An invoice is posted ONCE. A file whose invoice is already Posted
      and says the same as before ("Print" unchanged) is left alone - it is
      NOT calculated again, so a master changed later never alters a
      posted line (Brinda, 05-10-2026).
    * An invoice that cannot be calculated is recorded as "In review" with
      the reasons and tried again on every scan until it can be posted.
    * RE-ISSUED invoice = the same invoice number whose PDF now says
      something else (edited in Zoho, saved again). Its lines are worked
      out afresh and compared with the posted ones:
          line not yet paid   -> the row is corrected in place
          line already Paid   -> the paid row is left as it is and an
                                 ADJUSTMENT line is added for the difference
                                 (ID ending -ADJ1, -ADJ2 ...). If the payee
                                 changed: a negative line for the old payee
                                 and a new line for the new payee.
          line no longer due  -> not paid: Status "Cancelled";
                                 paid: a negative adjustment line
      Everything is written to the Log, and the invoice shows "Re-issued".
    * An invoice marked "Cancelled" in the Invoices tab is never posted.
    * The tally always adds up:
          files = posted now + already posted + re-issued + in review
                  + cancelled + not used + before the start date

LINES CHANGED BY HAND (`verify`)
--------------------------------
Each staff member signs in to Google as themselves, so Google cannot stop
them from typing over a calculated amount in the browser (decided
05-10-2026, option A). Instead every payout row carries a hidden "Check"
cell: a sealed copy of the calculated cells, written by the app. On every
scan the visible cells are compared with it; a difference is put back to
the sealed value and written to the Log ("changed by hand - restored").
A row whose Check cell is missing or damaged cannot be restored and is
reported. The payment columns are the staff's and are never touched.
`verify` also reports a Line ID that appears twice, and (as a warning) a
line marked Paid with neither a reference nor a proof.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime

from app.utils import format_inr
from payout_app.engine import (
    INCENTIVE, INTERNAL, LABOUR, NOT_USED, READY, REVIEW, InvoiceResult, Outcome,
    PayoutLine)
from payout_app.masters_sheet import date_to_serial, parse_sheet_date

SHEET_TITLE = "Drive N Style Payout Register"
PAYOUTS, INVOICES, MATCHES, LOG, SUMMARY = "Payouts", "Invoices", "Matches", "Log", "Summary"
SETUP = "Setup"
SETUP_HEADERS = ["Key", "Value"]
PROOFS_KEY = "Proofs folder"
PROOFS_FOLDER_NAME = "Drive N Style Payout Proofs"

PAYOUT_HEADERS = ["Line ID", "Invoice no", "Invoice date", "Customer", "Car", "Type",
                  "Payee", "Amount", "Working", "Calculated on",
                  "Status", "Paid date", "Mode", "Reference", "Proof", "Remarks",
                  "Entered by", "Entered at", "Check"]
CALCULATED = PAYOUT_HEADERS[:9]            # sealed; "Calculated on" is not compared
P = {name: i for i, name in enumerate(PAYOUT_HEADERS)}
INVOICE_HEADERS = ["Invoice no", "Invoice date", "Customer", "Total", "Salesperson",
                   "File name", "State", "Reason", "Lines", "Scanned by", "Scanned at",
                   "Print"]
I = {name: i for i, name in enumerate(INVOICE_HEADERS)}
MATCH_HEADERS = ["Kind", "Printed on invoice", "Master record", "Added by", "Added on"]
LOG_HEADERS = ["When", "Who", "What", "Record", "Old value", "New value"]

PENDING, PAID, HOLD, CANCELLED = "Pending", "Paid", "Hold", "Cancelled"
STATUSES = (PENDING, PAID, HOLD, CANCELLED)
MODES = ("Cash", "GPay", "UPI", "Bank transfer", "Other")
POSTED, IN_REVIEW, REISSUED = "Posted", "In review", "Re-issued"
INVOICE_STATES = (POSTED, IN_REVIEW, REISSUED, CANCELLED)
MATCH_KINDS = ("Item", "Salesperson", "Car")


# ---------------------------------------------------------------------------
# The empty sheet
# ---------------------------------------------------------------------------
def new_register_tabs() -> dict[str, list[list]]:
    """Tabs and headings of a new register (Summary is filled separately)."""
    return {PAYOUTS: [list(PAYOUT_HEADERS)], INVOICES: [list(INVOICE_HEADERS)],
            MATCHES: [list(MATCH_HEADERS)], LOG: [list(LOG_HEADERS)],
            SETUP: [list(SETUP_HEADERS), [PROOFS_KEY, ""]],
            # 12 columns, so the Summary's tables have room to spread out
            SUMMARY: [["Summary"] + [""] * 11]}


def summary_formulas() -> list[list]:
    """
    The Summary tab: two live tables over the Payouts tab (Google Sheets
    QUERY formulas - they follow every new line and every payment).
    Columns used: C invoice date, F type, G payee, H amount, K status.
    """
    by_payee = ('=IFERROR(QUERY(Payouts!A2:R, "select F, G, sum(H) where A is not null '
                'group by F, G pivot K", 0), "No payout lines yet")')
    by_month = ('=IFERROR(QUERY(Payouts!A2:R, "select year(C), month(C)+1, F, sum(H) '
                'where A is not null group by year(C), month(C)+1, F pivot K", 0), '
                '"No payout lines yet")')
    return [["Pending and paid, by type and payee  (columns = Status)"], [""],
            [by_payee]] + [[""]] * 200 + \
           [["Pending and paid, by invoice month and type  (year | month | type)"], [""],
            [by_month]]


SUMMARY_SECOND_TABLE_ROW = 204     # where summary_formulas puts the second table


def register_layout() -> dict[str, list[dict]]:
    """Column formats (google_api.format_requests). Calculated columns show
    Google's "you are editing a protected cell" warning; Check is hidden."""
    def c(kind, choices=(), strict=True, **more):
        return {"kind": kind, "choices": tuple(choices), "strict": strict, **more}
    payouts = [c("text", warn=True), c("text", warn=True), c("date", warn=True),
               c("text", warn=True), c("text", warn=True), c("text", warn=True),
               c("text", warn=True), c("money", warn=True), c("text", warn=True),
               c("text", warn=True),
               c("choice", STATUSES), c("date"), c("choice", MODES, strict=False),
               c("text"), c("text"), c("text"), c("text"), c("text"),
               c("text", warn=True, hidden=True)]
    invoices = [c("text"), c("date"), c("text"), c("money"), c("text"), c("text"),
                c("choice", INVOICE_STATES), c("text"), c("plain"), c("text"),
                c("text"), c("text", hidden=True)]
    matches = [c("choice", MATCH_KINDS), c("text"), c("text"), c("text"), c("text")]
    return {PAYOUTS: payouts, INVOICES: invoices, MATCHES: matches,
            LOG: [c("text")] * len(LOG_HEADERS)}


# ---------------------------------------------------------------------------
# Small helpers on rows
# ---------------------------------------------------------------------------
def _cell(row: list, index: int):
    return row[index] if index < len(row) else ""


def _s(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _amount(value) -> float:
    try:
        return round(float(str(value).replace(",", "")), 2)
    except (TypeError, ValueError):
        return 0.0


def _day(value) -> str:
    """A date cell (serial number or text) as dd-mm-yyyy, '' if unreadable."""
    try:
        day = parse_sheet_date(value)
    except Exception:
        return _s(value)
    return day.strftime("%d-%m-%Y") if day else ""


def stamp(now: datetime) -> str:
    return now.strftime("%d-%m-%Y %H:%M")


# ---------------------------------------------------------------------------
# The sealed copy ("Check")
# ---------------------------------------------------------------------------
def _sealed_values(row: list) -> list[str]:
    """The calculated cells in a comparable form."""
    out = []
    for name in CALCULATED:
        value = _cell(row, P[name])
        if name == "Invoice date":
            out.append(_day(value))
        elif name == "Amount":
            out.append(f"{_amount(value):.2f}")
        else:
            out.append(_s(value))
    return out


def seal(row: list) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(_sealed_values(row), ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"{hashlib.sha1(body.encode('ascii')).hexdigest()[:8]}.{body}"


def unseal(text) -> list[str] | None:
    """The sealed values, or None if the Check cell is missing / damaged."""
    try:
        digest, body = str(text).split(".", 1)
        if hashlib.sha1(body.encode("ascii")).hexdigest()[:8] != digest:
            return None
        values = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
        return values if isinstance(values, list) and len(values) == len(CALCULATED) else None
    except Exception:
        return None


def payout_row(line: PayoutLine, now: datetime) -> list:
    """A new Payouts row for a calculated line (Status Pending)."""
    row = [line.line_id, line.invoice_no, date_to_serial(line.invoice_date),
           line.customer, line.car, line.type, line.payee, round(line.amount, 2),
           line.working, stamp(now), PENDING, "", "", "", "", "", "", "", ""]
    row[P["Check"]] = seal(row)
    return row


def _restored(values: list[str]) -> list:
    """Sealed values -> the cells as they are written (date and amount typed)."""
    cells = list(values)
    day = parse_sheet_date(values[P["Invoice date"]])
    cells[P["Invoice date"]] = date_to_serial(day) if day else values[P["Invoice date"]]
    cells[P["Amount"]] = _amount(values[P["Amount"]])
    return cells


# ---------------------------------------------------------------------------
# What a scan has to write
# ---------------------------------------------------------------------------
@dataclass
class Plan:
    """Writes for one scan. Row numbers are sheet rows (headings = row 1)."""
    payout_appends: list[list] = field(default_factory=list)
    payout_updates: list[tuple[int, list]] = field(default_factory=list)  # (row, cells from A)
    invoice_appends: list[list] = field(default_factory=list)
    invoice_updates: list[tuple[int, list]] = field(default_factory=list)
    log: list[list] = field(default_factory=list)
    tally: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)     # stop: nothing is posted
    warnings: list[str] = field(default_factory=list)

    @property
    def has_writes(self) -> bool:
        return bool(self.payout_appends or self.payout_updates or
                    self.invoice_appends or self.invoice_updates or self.log)

    def add_log(self, now: datetime, who: str, what: str, record: str,
                old: str = "", new: str = "") -> None:
        self.log.append([stamp(now), who, what, record, old, new])


def verify(payout_rows: list[list], who: str, now: datetime) -> Plan:
    """
    Compare every payout row with its sealed copy (see LINES CHANGED BY
    HAND above). Returns a Plan holding the restoring updates, their log
    entries, problems and warnings.
    """
    plan = Plan()
    seen: dict[str, int] = {}
    for n, row in enumerate(payout_rows[1:], start=2):
        if not any(_s(c) for c in row):
            continue
        sealed = unseal(_cell(row, P["Check"]))
        line = _s(_cell(row, P["Line ID"])) or f"row {n}"
        if sealed is None:
            plan.problems.append(
                f"Payouts, row {n} ({line}): the Check cell is missing or damaged, so "
                "this line cannot be verified. Was the row typed or pasted by hand?")
            continue
        line = sealed[P["Line ID"]]
        if line in seen:
            plan.problems.append(f"Payouts, rows {seen[line]} and {n}: the line "
                                 f"{line} is there twice.")
        seen[line] = n
        now_values = _sealed_values(row)
        if now_values != sealed:
            for name, old, new in zip(CALCULATED, sealed, now_values):
                if old != new:
                    plan.add_log(now, who, "Changed by hand - restored",
                                 f"{line}: {name}", new, old)
            plan.payout_updates.append((n, _restored(sealed)))
        status = _s(_cell(row, P["Status"]))
        if status == PAID and not _s(_cell(row, P["Reference"])) \
                and not _s(_cell(row, P["Proof"])):
            plan.warnings.append(f"Payouts, row {n} ({line}): marked Paid without a "
                                 "reference or a proof.")
    return plan


def _same_line(row: list, line: PayoutLine) -> bool:
    return (_s(_cell(row, P["Payee"])) == _s(line.payee)
            and abs(_amount(_cell(row, P["Amount"])) - round(line.amount, 2)) < 0.005)


def plan(payout_rows: list[list], invoice_rows: list[list], outcome: Outcome,
         who: str, now: datetime, start: date | None = None) -> Plan:
    """
    What this scan has to write (see POSTING RULES above).
    payout_rows / invoice_rows   the tabs as read (row 1 = headings), AFTER
                                 any restoring from `verify` has been applied
    start                        invoices dated before this are left alone
    """
    out = Plan()
    tally = dict.fromkeys(("files", "posted", "already posted", "re-issued",
                           "in review", "cancelled", "not used", "before start date"), 0)
    known = {_s(_cell(r, I["Invoice no"])): (n, r)
             for n, r in enumerate(invoice_rows[1:], start=2) if _s(_cell(r, 0))}
    lines_of: dict[str, list[tuple[int, list]]] = {}
    for n, r in enumerate(payout_rows[1:], start=2):
        if _s(_cell(r, P["Line ID"])):
            lines_of.setdefault(_s(_cell(r, P["Invoice no"])), []).append((n, r))

    def invoice_row(res: InvoiceResult, state: str, reason: str, count) -> list:
        return [res.invoice_no, date_to_serial(res.invoice_date), res.customer,
                round(res.total, 2), res.salesperson, res.file_name, state, reason,
                count, who, stamp(now), res.fingerprint]

    def record(res: InvoiceResult, state: str, reason: str, count) -> None:
        row = invoice_row(res, state, reason, count)
        if res.invoice_no in known:
            out.invoice_updates.append((known[res.invoice_no][0], row))
        else:
            out.invoice_appends.append(row)

    for res in outcome.results:
        tally["files"] += 1
        if res.state == NOT_USED:
            tally["not used"] += 1
            continue
        if start and res.invoice_date and res.invoice_date < start:
            tally["before start date"] += 1
            continue
        old = known.get(res.invoice_no)
        old_state = _s(_cell(old[1], I["State"])) if old else ""
        old_print = _s(_cell(old[1], I["Print"])) if old else ""
        new_print = res.fingerprint
        if old_state == CANCELLED:
            tally["cancelled"] += 1
            continue
        posted_before = old_state in (POSTED, REISSUED)
        if posted_before and old_print == new_print:
            tally["already posted"] += 1
            continue
        if res.state == REVIEW:
            tally["in review"] += 1
            reason = " ".join(res.reasons)
            if posted_before:
                # Re-issued, but the new version cannot be calculated: the
                # posted lines stay; the invoice waits in review.
                out.warnings.append(
                    f"{res.invoice_no} was posted, has been re-issued and now needs "
                    f"review: {reason} Its posted lines are unchanged for now.")
                continue
            if not old or _s(_cell(old[1], I["Reason"])) != _s(reason) \
                    or old_print != new_print:
                record(res, IN_REVIEW, reason, "")
            continue
        # READY
        if not posted_before:
            tally["posted"] += 1
            for line in res.lines:
                out.payout_appends.append(payout_row(line, now))
            record(res, POSTED, "", len(res.lines))
            out.add_log(now, who, "Posted", res.invoice_no, "",
                        f"{len(res.lines)} line(s), "
                        f"{format_inr(sum(l.amount for l in res.lines))}")
            continue
        tally["re-issued"] += 1
        _reissue(out, res, lines_of.get(res.invoice_no, []), who, now)
        record(res, REISSUED, "", len(res.lines))
    out.tally = tally
    return out


def _reissue(out: Plan, res: InvoiceResult, old_rows: list[tuple[int, list]],
             who: str, now: datetime) -> None:
    """Bring the posted lines of a re-issued invoice in line with the new ones."""
    base: dict[str, tuple[int, list]] = {}
    adjustments: dict[str, list[list]] = {}
    for n, row in old_rows:
        lid = _s(_cell(row, P["Line ID"]))
        if "-ADJ" in lid:
            adjustments.setdefault(lid.split("-ADJ")[0], []).append(row)
        else:
            base[lid] = (n, row)
    new = {l.line_id: l for l in res.lines}

    def adjustment(like: PayoutLine, payee: str, amount: float, why: str) -> None:
        count = len(adjustments.setdefault(like.line_id, [])) + 1
        line = PayoutLine(f"{like.line_id}-ADJ{count}", like.invoice_no, like.invoice_date,
                          like.customer, like.car, like.type, payee, round(amount, 2), why)
        row = payout_row(line, now)
        adjustments[like.line_id].append(row)
        out.payout_appends.append(row)
        out.add_log(now, who, "Re-issued invoice: adjustment line", line.line_id, "",
                    f"{payee or like.type}: {format_inr(amount)}")

    def due(lid: str, payee: str) -> float:
        """What the register already shows for this line and payee (not cancelled)."""
        rows = ([base[lid][1]] if lid in base else []) + adjustments.get(lid, [])
        return round(sum(_amount(_cell(r, P["Amount"])) for r in rows
                         if _s(_cell(r, P["Payee"])) == _s(payee)
                         and _s(_cell(r, P["Status"])) != CANCELLED), 2)

    for lid in sorted(set(base) | set(new)):
        line = new.get(lid)
        if lid not in base:                                   # a line that is new
            row = payout_row(line, now)
            out.payout_appends.append(row)
            out.add_log(now, who, "Re-issued invoice: new line", lid, "",
                        f"{line.payee or line.type}: {format_inr(line.amount)}")
            continue
        n, row = base[lid]
        paid = _s(_cell(row, P["Status"])) == PAID or any(
            _s(_cell(a, P["Status"])) == PAID for a in adjustments.get(lid, []))
        old_payee = _s(_cell(row, P["Payee"]))
        was = f"{old_payee or _s(_cell(row, P['Type']))}: " \
              f"{format_inr(_amount(_cell(row, P['Amount'])))}"
        if not paid and not adjustments.get(lid):
            if line is None:                                  # no longer due
                cells = list(row[:len(PAYOUT_HEADERS)])
                cells += [""] * (len(PAYOUT_HEADERS) - len(cells))
                cells[P["Status"]] = CANCELLED
                cells[P["Remarks"]] = "Invoice re-issued: no longer due"
                out.payout_updates.append((n, cells))
                out.add_log(now, who, "Re-issued invoice: line cancelled", lid, was, "")
            elif not _same_line(row, line):
                fresh = payout_row(line, now)
                cells = fresh[:P["Status"]] + list(row[P["Status"]:P["Check"]])
                cells += [""] * (P["Check"] - len(cells)) + [fresh[P["Check"]]]
                out.payout_updates.append((n, cells))
                out.add_log(now, who, "Re-issued invoice: line corrected", lid, was,
                            f"{line.payee or line.type}: {format_inr(line.amount)}")
            continue
        # Paid (or already adjusted): never touch the rows - add the difference.
        like = line or PayoutLine(lid, res.invoice_no, res.invoice_date, res.customer,
                                  _s(_cell(row, P["Car"])), _s(_cell(row, P["Type"])),
                                  old_payee, 0.0, "")
        new_payee = _s(line.payee) if line else old_payee
        new_amount = round(line.amount, 2) if line else 0.0
        if new_payee != old_payee:
            shown = due(lid, old_payee)
            if abs(shown) >= 0.005:
                adjustment(like, old_payee, -shown,
                           "Invoice re-issued: no longer due to this payee")
            diff = round(new_amount - due(lid, new_payee), 2)
            if abs(diff) >= 0.005:
                adjustment(like, new_payee, diff, "Invoice re-issued: " + (line.working if line else ""))
        else:
            diff = round(new_amount - due(lid, old_payee), 2)
            if abs(diff) >= 0.005:
                adjustment(like, old_payee, diff,
                           f"Invoice re-issued: now {format_inr(new_amount)}"
                           + (f" ({line.working})" if line else ""))


# ---------------------------------------------------------------------------
# Reading helpers for the commands
# ---------------------------------------------------------------------------
def matches_from(rows: list[list]) -> list[dict]:
    """The Matches tab as the list engine.calculate expects."""
    return [dict(kind=_s(_cell(r, 0)), printed=_s(_cell(r, 1)), target=_s(_cell(r, 2)))
            for r in rows[1:] if _s(_cell(r, 0)) and _s(_cell(r, 1))]


def pending_by_payee(payout_rows: list[list]) -> list[tuple[str, str, float, float]]:
    """(type, payee, pending, paid) totals, labour first then payees A-Z."""
    totals: dict[tuple[str, str], list[float]] = {}
    for r in payout_rows[1:]:
        if not _s(_cell(r, P["Line ID"])):
            continue
        status = _s(_cell(r, P["Status"]))
        if status == CANCELLED:
            continue
        key = (_s(_cell(r, P["Type"])), _s(_cell(r, P["Payee"])))
        slot = totals.setdefault(key, [0.0, 0.0])
        slot[1 if status == PAID else 0] += _amount(_cell(r, P["Amount"]))
    order = {LABOUR: 0, INCENTIVE: 1, INTERNAL: 2}
    return [(t, p, round(v[0], 2), round(v[1], 2))
            for (t, p), v in sorted(totals.items(),
                                    key=lambda kv: (order.get(kv[0][0], 9), kv[0][1].lower()))]


# ---------------------------------------------------------------------------
# Payments (v0.17.0)
# ---------------------------------------------------------------------------
PAYMENT_FIRST, PAYMENT_LAST = P["Status"], P["Entered at"]
PAYMENT_COLUMN = "K"                      # column letter of "Status"
assert PAYMENT_FIRST == 10                # K is the 11th column


def payout_lines(payout_rows: list[list]) -> list[dict]:
    """
    The Payouts tab as dicts, one per line, in sheet order. `row` is the
    sheet row number; dates are `date` objects (None if blank / unreadable).
    """
    def day(value):
        try:
            return parse_sheet_date(value)
        except Exception:
            return None

    out = []
    for n, r in enumerate(payout_rows[1:], start=2):
        if not _s(_cell(r, P["Line ID"])):
            continue
        out.append(dict(
            row=n, line_id=_s(_cell(r, P["Line ID"])),
            invoice_no=_s(_cell(r, P["Invoice no"])),
            invoice_date=day(_cell(r, P["Invoice date"])),
            customer=_s(_cell(r, P["Customer"])), car=_s(_cell(r, P["Car"])),
            type=_s(_cell(r, P["Type"])), payee=_s(_cell(r, P["Payee"])),
            amount=_amount(_cell(r, P["Amount"])), working=_s(_cell(r, P["Working"])),
            status=_s(_cell(r, P["Status"])) or PENDING,
            paid_date=day(_cell(r, P["Paid date"])), mode=_s(_cell(r, P["Mode"])),
            reference=_s(_cell(r, P["Reference"])), proof=_s(_cell(r, P["Proof"])),
            remarks=_s(_cell(r, P["Remarks"])),
            entered_by=_s(_cell(r, P["Entered by"])),
            entered_at=_s(_cell(r, P["Entered at"]))))
    return out


def payment_cells(status: str, paid_date: date | None = None, mode: str = "",
                  reference: str = "", proof: str = "", remarks: str = "",
                  who: str = "", now: datetime | None = None) -> list:
    """The eight payment cells of a line, Status ... Entered at (K to R)."""
    return [status, date_to_serial(paid_date) if paid_date else "", mode, reference,
            proof, remarks, who, stamp(now) if now else ""]


def payment_range(row: int) -> str:
    """Where a line's payment cells start: "K7" for sheet row 7."""
    return f"{PAYMENT_COLUMN}{row}"


def payment_summary(line: dict) -> str:
    """A paid line's payment in one line of text, for the Log."""
    parts = [line["status"]]
    if line.get("paid_date"):
        parts.append(line["paid_date"].strftime("%d-%m-%Y"))
    parts += [p for p in (line.get("mode"), line.get("reference"), line.get("proof")) if p]
    return " | ".join(parts)


def setup_value(setup_rows: list[list] | None, key: str) -> str:
    for r in (setup_rows or [])[1:]:
        if _s(_cell(r, 0)).lower() == key.lower():
            return _s(_cell(r, 1))
    return ""

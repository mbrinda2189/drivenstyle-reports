"""
engine.py - From invoice PDFs to labour and incentive payout lines
==================================================================

WHAT THIS MODULE DOES
---------------------
`calculate(masters, files, matches)` takes the masters read from the
masters sheet and the invoice PDFs of a folder, and returns one
`InvoiceResult` per file saying either

    posted-ready   the payout lines of the invoice (labour, spot incentive,
                   internal team), each with its amount and its working, or
    in review      why the invoice cannot be calculated yet (item not in
                   the Product master, salesperson or car not matched,
                   totals do not agree), or
    not used       another firm's invoice, a file that is not an invoice.

It changes nothing anywhere: no sheet is written here (register.py and
payout_cli.py do that), so the same call can be used for a trial run.

THE RULES ARE THE MONTHLY TOOL'S OWN
------------------------------------
Nothing is calculated here by new rules. The invoices are stored in a
temporary in-memory database through the monthly tool's own code
(InvoicesRepo.store_scan), matched by its matching rules
(InvoicesRepo.issues) and valued by its report code
(app/reports/data.build_month). So the daily payouts add up to the monthly
Labour and Spot incentive reports:

    Labour           Product master labour charge x quantity, for products
                     marked "Labour involved", at the rate in force on the
                     invoice date. The Rs. 1 "Labour Charges ..." lines on
                     the invoice are only markers and are ignored.
                     From v0.21.0 (client, 07-10-2026) the labour of an
                     invoice is posted as SEPARATE LINES by kind of work,
                     so each can be paid and proved on its own:
                         Labour - Floor mat    item name has "floor mat"
                         Labour - Sunfilm      item name has "sunfilm"
                         Labour - Other        any other item with labour
                     The kind is picked from the item name by the monthly
                     tool's own rule (reports/data.labour_group - Brinda,
                     07-10-2026: "floor mat" only, the same in both apps),
                     so the daily lines agree with the monthly "Labour
                     calculation" tables. An invoice with a mat and a
                     sunfilm has two labour lines. (Until v0.20.0: one
                     line "Labour" per invoice, ID ending -LAB; such lines
                     already in a register stay as they are.)
    Spot incentive   per item with an incentive group:
                         incentive x qty x min(1, billed / (bill value x qty))
                     plus the package incentive when every item of a
                     package is on the invoice (it replaces those items'
                     own incentives). ONE line per invoice, payable to the
                     invoice's sales executive. None for an executive
                     marked "Gets incentive = No".
    Internal team    the product's "Internal incentive" x quantity (car
                     PPF), in full, one line "Internal team".
    NO ROUNDING here (Brinda, 05-10-2026): the daily lines carry the exact
    amounts; rounding up to Rs. 10 stays a month-end figure.

"BILLED" FROM A PDF
-------------------
`billed` is the line's value after discount, including GST. A PDF does not
say which line carried how much GST, and it does not need to:
invoices_repo.billed_lines gives billed = amount x (1 - discount / value
the discount applies on) for every line. Each line is stored with exactly
that billed value (its GST share in proportion), so invoices with a mix of
taxed and untaxed lines are right too.

SAVED MATCHES
-------------
A printed name that is not in the masters ("Harish - Ho", an old item
name) keeps an invoice in review until someone says what it is. Those
choices are kept in the register's "Matches" tab (so every PC uses the
same ones) and passed in as `matches`:
    kind     Item / Salesperson / Car
    printed  the text as printed on the invoice
    target   the master record's name - product name; executive "Name
             (contact no)" or just the contact no; car "Make Model" or
             the model - or "Others" for a salesperson / car that is not
             in the master on purpose (incentive is still calculated,
             payable to "Others")
A match that cannot be applied (target not in the masters) is reported in
`Outcome.notes` and otherwise ignored.

WHAT NEEDS REVIEW, FOR THE REVIEW SCREEN (v0.16.0)
--------------------------------------------------
Besides the reasons on each invoice, `Outcome.issues` lists every thing
that needs a decision ONCE, with the invoices it holds up - "Vehicle NIOS
is not in the Car master (3 invoices)" is one issue, fixed by one saved
match. `Outcome.choices` gives the names that can be chosen for each kind
(every product, executive and car of the masters).

WORKING
-------
Every payout line carries a short text showing how the amount was reached,
e.g. "Underbody: 200 x 1 x min(1, 3,300.00 / 3,500)" - so anyone looking at
the register can check a figure without the app.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.data.inputs_repo import InputsRepo
from app.data.invoice_reader import InvoiceReadError, ParsedInvoice, read_invoice
from app.data.invoices_repo import (
    FIRM_GSTIN, OTHERS, OTHERS_ID, FileResult, InvoicesRepo, billed_lines,
    person_key, vehicle_key)
from app.data.masters_repo import MastersRepo, name_key, phone_key
from app.reports.data import LABOUR_GROUPS, build_month, labour_group
from app.utils import format_inr

LABOUR = "Labour"           # every labour type starts with this word; also the
                            # type of the single labour line posted until v0.20.0
INCENTIVE = "Spot incentive"
INTERNAL = "Internal team"
# Kind of work (reports/data.LABOUR_GROUPS) -> line type and line-ID ending.
LABOUR_TYPE = {group: f"{LABOUR} - {group}" for group in LABOUR_GROUPS}
LABOUR_SUFFIX = {"Floor mat": "LABM", "Sunfilm": "LABS", "Other": "LABO"}
LABOUR_TYPES = tuple(LABOUR_TYPE[group] for group in LABOUR_GROUPS)
LINE_TYPES = LABOUR_TYPES + (INCENTIVE, INTERNAL)
SUFFIX = {LABOUR: "LAB", INCENTIVE: "INC", INTERNAL: "INT",
          **{LABOUR_TYPE[g]: LABOUR_SUFFIX[g] for g in LABOUR_GROUPS}}


def is_labour(line_type: str) -> bool:
    """True for every labour line type, old ("Labour") and new."""
    return str(line_type).startswith(LABOUR)

READY = "ready"            # calculated; its lines can be posted
REVIEW = "review"          # cannot be calculated yet - see reasons
NOT_USED = "not used"      # not an invoice of this firm / unreadable


@dataclass
class PayoutLine:
    """One amount to be paid for one invoice."""
    line_id: str               # "DNS-226-2627-LAB" - unique in the register
    invoice_no: str
    invoice_date: date
    customer: str
    car: str
    type: str                  # Labour - <kind> / Spot incentive / Internal team
    payee: str                 # executive's name; "" for labour
    amount: float
    working: str


@dataclass
class InvoiceResult:
    """What became of one file."""
    file_name: str
    state: str                             # READY / REVIEW / NOT_USED
    invoice_no: str = ""
    invoice_date: date | None = None
    customer: str = ""
    total: float = 0.0
    salesperson: str = ""                  # as printed
    fingerprint: str = ""                  # what the PDF says (invoice_print)
    reasons: list[str] = field(default_factory=list)
    lines: list[PayoutLine] = field(default_factory=list)


@dataclass
class ReviewIssue:
    """One thing that keeps invoices in review."""
    kind: str                    # Item / Salesperson / Car / Totals
    printed: str                 # the text as printed on the invoice(s)
    message: str
    invoices: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)   # likely master records


@dataclass
class Outcome:
    results: list[InvoiceResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)     # e.g. unusable matches
    issues: list[ReviewIssue] = field(default_factory=list)
    choices: dict[str, list[str]] = field(default_factory=dict)  # kind -> names

    def of(self, state: str) -> list[InvoiceResult]:
        return [r for r in self.results if r.state == state]


def line_id(invoice_no: str, line_type: str) -> str:
    return f"{invoice_no}-{SUFFIX[line_type]}"


def invoice_print(inv: ParsedInvoice) -> str:
    """
    Fingerprint of what an invoice PDF says: number, date, salesperson,
    vehicle, discount, total and every line. The same invoice saved again
    gives the same print; any edit in Zoho changes it. The register keeps
    it to tell "the same invoice, already posted" from "re-issued".
    """
    parts = [inv.invoice_no, str(inv.invoice_date), inv.salesperson, inv.vehicle,
             f"{inv.discount:.2f}", f"{inv.total:.2f}"]
    parts += [f"{l.description}|{l.qty:g}|{l.amount:.2f}" for l in inv.lines]
    text = "\n".join(" ".join(str(p).split()).lower() for p in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Reading the files
# ---------------------------------------------------------------------------
def read_files(paths: list[str | Path], progress=None, cache: dict | None = None
               ) -> list[tuple[str, ParsedInvoice | None, str]]:
    """
    Read each PDF. Returns (file name, invoice or None, reason if not used).
    Another firm's invoice (different GSTIN) and files that are not readable
    invoices are "not used", with the reason in plain words.

    progress   called as progress(done, total, file name) after each file
    cache      a dict kept by the caller between scans: a file whose size
               and modified time are unchanged is not read again (reading
               is the slow part - about 12 files a second)
    """
    out = []
    paths = [Path(p) for p in paths]
    for i, path in enumerate(paths, start=1):
        key = stamp = None
        if cache is not None:
            try:
                stat = path.stat()
                key, stamp = str(path), (stat.st_size, stat.st_mtime_ns)
            except OSError:
                key = None
            if key and cache.get(key, (None,))[0] == stamp:
                out.append(cache[key][1])
                if progress:
                    progress(i, len(paths), path.name)
                continue
        out.append(_read_one(path))
        if key:
            cache[key] = (stamp, out[-1])
        if progress:
            progress(i, len(paths), path.name)
    return out


def _read_one(path: Path) -> tuple[str, ParsedInvoice | None, str]:
    """Read one PDF (see read_files)."""
    try:
        inv = read_invoice(path)
    except InvoiceReadError as exc:
        return path.name, None, f"Could not be read: {exc}."
    except Exception as exc:                          # damaged / locked file
        return path.name, None, f"Could not be read ({exc.__class__.__name__})."
    if inv.gstin and inv.gstin != FIRM_GSTIN:
        return path.name, None, f"Another firm's invoice (GSTIN {inv.gstin})."
    if inv.invoice_date is None:
        return path.name, None, "No invoice date found."
    return path.name, inv, ""


def _with_billed_values(inv: ParsedInvoice) -> ParsedInvoice:
    """
    Give every line its value after discount and its GST share so that
    value + GST = billed (see "BILLED" FROM A PDF above). InvoicesRepo then
    stores these figures as they are.
    """
    billed = billed_lines(inv)
    total = sum(billed) or 1.0
    for line, b in zip(inv.lines, billed):
        gst = round(inv.tax_total * b / total, 2)
        line.gst = gst
        line.net_value = round(b - gst, 2)
    return inv


# ---------------------------------------------------------------------------
# Saved matches
# ---------------------------------------------------------------------------
def _apply_matches(masters: MastersRepo, invoices: InvoicesRepo,
                   matches: list[dict], notes: list[str]) -> None:
    """Store the register's saved matches as the monthly tool's own aliases."""
    products = {name_key(p["name"]): p["id"] for p in masters.list_rows("products")}
    execs = masters.list_rows("executives")
    cars = masters.list_rows("cars")

    def executive_id(target: str) -> int | None:
        hits = [e["id"] for e in execs
                if name_key(MastersRepo.display_name("executives", e)) == name_key(target)
                or (phone_key(target) and phone_key(target) == phone_key(e["phone"]))]
        if not hits:
            hits = [e["id"] for e in execs if person_key(e["name"]) == person_key(target)]
        return hits[0] if len(hits) == 1 else None

    def car_id(target: str) -> int | None:
        key = vehicle_key(target)
        hits = [c["id"] for c in cars
                if key in (vehicle_key(c["make"] + c["model"]), vehicle_key(c["model"]))]
        return hits[0] if len(hits) == 1 else None

    for m in matches:
        kind = str(m.get("kind", "")).strip().lower()
        printed = str(m.get("printed", "")).strip()
        target = str(m.get("target", "")).strip()
        if not (kind and printed and target):
            continue
        others = name_key(target) == name_key(OTHERS)
        if kind == "item":
            tid = products.get(name_key(target))
            if tid is not None:
                invoices.map_product(printed, tid)
        elif kind == "salesperson":
            tid = OTHERS_ID if others else executive_id(target)
            if tid is not None:
                invoices.set_salesperson("", printed, tid, all_invoices=True)
        elif kind == "car":
            tid = OTHERS_ID if others else car_id(target)
            if tid is not None:
                invoices.set_car("", printed, tid, all_invoices=True)
        else:
            notes.append(f"Saved match “{printed}”: kind “{m.get('kind')}” is not "
                         "Item, Salesperson or Car.")
            continue
        if tid is None:
            notes.append(f"Saved match “{printed}” → “{target}” is not used: "
                         f"“{target}” is not in the masters (or fits several records).")


# ---------------------------------------------------------------------------
# Working texts
# ---------------------------------------------------------------------------
def _num(value: float) -> str:
    """500 -> "500"; 1.5 -> "1.5" (rates and quantities)."""
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _labour_working(lines) -> str:
    parts = [f"{l.product}: {_num(l.labour_rate)} x {_num(l.qty)}"
             for l in lines if l.labour]
    return "; ".join(parts)


def _incentive_working(inv) -> str:
    parts = []
    for l in inv.lines:
        base = l.bill_value * l.qty
        if l.incentive_group and base:
            parts.append(f"{l.incentive_group}: {_num(l.incentive_amount)} x {_num(l.qty)} "
                         f"x min(1, {format_inr(l.billed)} / {_num(base)})")
    k = inv.package
    if k and k.coupon_value and k.incentive:
        parts.append(f"{k.package} (package): {_num(k.incentive)} "
                     f"x min(1, {format_inr(k.billed)} / {_num(k.coupon_value)})")
    return "; ".join(parts)


def _internal_working(inv) -> str:
    return "; ".join(f"{l.product}: {_num(l.internal_incentive)} x {_num(l.qty)}"
                     for l in inv.lines if l.internal_incentive)


# ---------------------------------------------------------------------------
# The calculation
# ---------------------------------------------------------------------------
def calculate(masters: MastersRepo,
              files: list[tuple[str, ParsedInvoice | None, str]],
              matches: list[dict] | None = None) -> Outcome:
    """
    Work out the payout lines for the files read by `read_files`.
    `masters` is the MastersRepo from masters_sheet.load_tabs (an in-memory
    database); the invoices are stored beside the masters in it, so call
    this once per run with a fresh `masters`.
    """
    outcome = Outcome()
    invoices = InvoicesRepo(masters)
    inputs = InputsRepo(masters)
    _apply_matches(masters, invoices, matches or [], outcome.notes)

    by_month: dict[tuple[int, int], list[FileResult]] = {}
    by_number: dict[str, InvoiceResult] = {}
    for file_name, inv, reason in files:
        if inv is None:
            outcome.results.append(InvoiceResult(file_name, NOT_USED, reasons=[reason]))
            continue
        result = InvoiceResult(file_name, REVIEW, inv.invoice_no, inv.invoice_date,
                               inv.customer, inv.total, inv.salesperson,
                               fingerprint=invoice_print(inv))
        if inv.invoice_no in by_number:
            result.state = NOT_USED
            result.reasons = [f"Invoice {inv.invoice_no} is also in "
                              f"{by_number[inv.invoice_no].file_name}; that file was used."]
            outcome.results.append(result)
            continue
        by_number[inv.invoice_no] = result
        outcome.results.append(result)
        month = (inv.invoice_date.year, inv.invoice_date.month)
        by_month.setdefault(month, []).append(
            FileResult(file_name, "read", "", _with_billed_values(inv)))

    outcome.choices = {
        "Item": sorted(p["name"] for p in masters.list_rows("products") if p["active"]),
        "Salesperson": sorted(MastersRepo.display_name("executives", e)
                              for e in masters.list_rows("executives") if e["active"]),
        "Car": sorted(MastersRepo.display_name("cars", c)
                      for c in masters.list_rows("cars") if c["active"])}
    names = {"salesperson": ("Salesperson", "executives"), "car": ("Car", "cars")}

    for (year, month), results in sorted(by_month.items()):
        invoices.store_scan(year, month, "payout app", results)
        for issue in invoices.issues(year, month):
            if issue.status != "open":
                continue
            if issue.kind == "product":
                kind, suggestions = "Item", []
            elif issue.kind in names:
                kind, master = names[issue.kind]
                suggestions = [MastersRepo.display_name(master, masters.get(master, i))
                               for i in issue.options if masters.get(master, i)]
            else:
                kind, suggestions = "Totals", []
            same = next((x for x in outcome.issues if x.kind == kind and issue.printed
                         and name_key(x.printed) == name_key(issue.printed)), None)
            if same:                       # the same name in another month
                same.invoices += [n for n in issue.invoices if n not in same.invoices]
            else:
                outcome.issues.append(ReviewIssue(kind, issue.printed, issue.message,
                                                  list(issue.invoices), suggestions))
        data = build_month(masters, invoices, inputs, year, month)
        for left in data.left_out:
            by_number[left.invoice_no].reasons = list(dict.fromkeys(left.reasons))
        for inv in data.invoices:
            result = by_number[inv.invoice_no]
            result.state = READY
            common = dict(invoice_no=inv.invoice_no, invoice_date=inv.invoice_date,
                          customer=inv.customer, car=inv.printed_car or inv.car)
            for group in LABOUR_GROUPS:           # one labour line per kind of work
                work = [l for l in inv.lines
                        if l.labour and labour_group(l.product) == group]
                amount = round(sum(l.labour for l in work), 2)
                if amount > 0:
                    kind = LABOUR_TYPE[group]
                    result.lines.append(PayoutLine(
                        line_id(inv.invoice_no, kind), type=kind, payee="",
                        amount=amount, working=_labour_working(work), **common))
            if inv.incentive_payable > 0:
                payee = inv.executive
                if payee == OTHERS and inv.printed_executive:
                    payee = f"{OTHERS} ({inv.printed_executive})"
                result.lines.append(PayoutLine(
                    line_id(inv.invoice_no, INCENTIVE), type=INCENTIVE, payee=payee,
                    amount=inv.incentive_payable, working=_incentive_working(inv),
                    **common))
            if inv.internal_incentive > 0:
                result.lines.append(PayoutLine(
                    line_id(inv.invoice_no, INTERNAL), type=INTERNAL, payee=INTERNAL,
                    amount=inv.internal_incentive, working=_internal_working(inv),
                    **common))
    return outcome

"""
invoices_repo.py - Scanned invoices: storing, matching and Scan review
======================================================================

WHAT THIS MODULE DOES
---------------------
Takes the invoices read from Zoho's invoice export (invoice_export.py,
from v0.6.0) - or, in earlier versions, from the invoice PDFs
(invoice_reader.py) - and:

    0. classify_export(...) in invoice_export.py
           Reads the export and keeps the chosen month's invoices. Each
           invoice becomes one "file" entry below (its name is the invoice
           number), so everything that follows is the same for both.

    1. classify_file(path, year, month)          (PDFs - no longer on screen)
           Reads one PDF and decides what to do with it:
               read     - a Drive N Style invoice dated in the month
               skipped  - another month, another firm's GSTIN, or an
                          invoice number already seen in this scan
               error    - could not be read (reason given)
           Pure function, safe to run in a background thread.

    2. InvoicesRepo.store_scan(year, month, folder, results)
           Saves the month's invoices and file list in the database,
           replacing that month's previous scan. Fixes made earlier on Scan
           review are kept (they are stored separately, see below), so
           re-scanning never loses work.

    3. InvoicesRepo.issues(year, month)
           Works out what still needs attention, by matching the stored
           invoices against the CURRENT masters every time it is asked.
           Adding a product to the master, or fixing an issue, therefore
           takes effect at once, with no re-scan.
           An unknown item, salesperson or vehicle is listed ONCE with all
           the invoices showing it (salesperson / vehicle grouping from
           v0.6.1); ambiguous or missing names stay one row per invoice.

    4. Fixes from the Scan review screen (all logged in the audit log):
           map_product      an item name  -> a product    (remembered for
                                                           every invoice)
           set_salesperson  an invoice    -> an executive (just this
                            invoice, or every invoice showing the same
                            printed name)
           set_car          same, for the vehicle
           acknowledge      accept a totals difference (or, before v0.6.3, a
                            labour note)

    5. apply_zoho_categories()
           Products whose Category was never set by hand take Zoho's Item
           Type from the export (goods -> Product, service -> Service).
           Agreed with Brinda (v0.6.0, decision A): Items.xlsx has no
           category, and the HSN code alone is unreliable (many goods carry
           the service code 998729). Once someone changes a product's
           Category on the Masters screen or by import, Zoho no longer
           touches it. Every change is written to the audit log.

MATCHING RULES
--------------
Item      1. a remembered mapping for this item name
          2. a product with exactly this name (compared ignoring capitals,
             extra spaces and dash style)
          3. the SKU, if the invoice prints one
Labour    lines named "Labour Charges for ..." or "Labour - ..." (billed at
marker    Rs. 1) are markers that labour was done, not sales items.
          ("... + Labour Extra" in the middle of a name is a product.) They
          are stored but IGNORED in the reports (v0.6.3). The labour cost
          comes only from the product's labour charge in the Product
          master (Labour involved). Markers are never flagged.
Sales     "Kumaran - HO" is split into name "Kumaran" and branch "HO"; the
person    executive with that name AND branch is used. With no branch
          printed ("Nandha Kumar"), the name alone must match exactly one
          executive. None or several matches -> Scan review.
          Names are compared on letters and digits only, so "Udhayakumar"
          = "UDHAYA KUMAR" and "S.F. Naveen" = "SF Naveen". Branches are
          compared the same way, with the short forms the invoices use:
          "Head Office" = "HO", "KTG" = "Kothagiri" (BRANCH_ALIASES).
          (A per-invoice choice or a remembered name comes first.)
Car       the printed Vehicle ("PUNCH.EV", "CRETA") compared with the Car
          master's model (or make + model), ignoring capitals, spaces and
          punctuation. None or several matches -> Scan review.

AMOUNTS PER LINE (for the reports)
----------------------------------
From the EXPORT (v0.6.0): Zoho's own "Item Total" (after the line's share
of the discount, without GST) and "Item Tax Amount" are stored as they are
- see invoice_export.py. What follows applies to PDFs only.

Rates are tax inclusive and the discount is given on the whole invoice.
`allocate_lines()` splits the invoice into per-line figures:
    GST invoice (e.g. 18%)   value before GST = amount / 1.18
                             discount share   = invoice discount in
                                                proportion to that value
                             net value        = value - discount share
                             GST              = net value x 18%
    No GST shown             value = amount; discount shared the same way;
                             GST = 0 (whole amount is sales)
    Mixed GST rates          net value and GST shared in proportion to
                             the line amounts (the invoice does not say
                             which line had which rate)
Rounding stays on the invoice as a whole.

CHECKS ON EACH INVOICE
----------------------
Export:
    * line values (Item Total) + GST + Round Off = Total
    * the invoice-level columns agree on every line of the invoice
PDF:
    * line amounts add up to the Sub Total
    * Sub Total (before GST) - discount + GST + rounding = Total
Both:
    * quantity x rate = line amount
Differences above Rs. 1 are shown on Scan review so a misread can never
slip into the reports unnoticed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.data.invoice_reader import (
    InvoiceReadError, ParsedInvoice, read_invoice)
from app.data.masters_repo import MastersRepo, name_key

FIRM_GSTIN = "33AAOFD7793F1Z2"          # Drive N Style
TOLERANCE = 1.00                        # rupees allowed in the checks
# "Labour Charges for Sunfilm - Front", "Labour Charges PVC/...",
# "Labour - Seat Cover - Art Leather". Only at the START of the name.
LABOUR_MARKER_RE = re.compile(r"^\s*labou?r\s*(charges?\b|-)", re.IGNORECASE)
# Branch short forms on invoices -> the form used for comparing
# (compared after branch_key has removed spaces and punctuation).
BRANCH_ALIASES = {"headoffice": "ho", "ktg": "kothagiri"}
# Zoho "Item Type" -> Product master Category.
ZOHO_ITEM_TYPES = {"goods": "Product", "service": "Service"}
ZOHO_CATEGORY_SOURCE = "Invoice export (Zoho item type)"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def is_labour_marker(description: str) -> bool:
    """True for 'Labour Charges for ...' and 'Labour - ...' lines."""
    return bool(LABOUR_MARKER_RE.match(description or ""))


def split_salesperson(printed: str) -> tuple[str, str]:
    """'Kumaran - HO' -> ('Kumaran', 'HO'); 'Nandha Kumar' -> ('Nandha Kumar', '')."""
    m = re.match(r"^(.*?)\s*-\s*([^-]+?)\s*$", printed or "")
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2).strip()
    return (printed or "").strip(), ""


def person_key(text: str) -> str:
    """'UDHAYA KUMAR' / 'Udhayakumar' / 'S.F. Naveen' -> letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def branch_key(text: str) -> str:
    """'Head Office' / 'HO' -> 'ho'; 'KTG' / 'Kothagiri' -> 'kothagiri'."""
    key = person_key(text)
    return BRANCH_ALIASES.get(key, key)


def vehicle_key(text: str) -> str:
    """'PUNCH.EV' / 'Punch EV' -> 'punchev' (letters and digits only)."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


# ---------------------------------------------------------------------------
# Reading one file (background thread)
# ---------------------------------------------------------------------------
@dataclass
class FileResult:
    """Outcome of reading one PDF."""
    file_name: str
    status: str                        # read / skipped / error
    reason: str = ""
    invoice: ParsedInvoice | None = None


def classify_file(path: str | Path, year: int, month: int) -> FileResult:
    """Read one PDF and decide whether it belongs to this month's scan."""
    path = Path(path)
    try:
        inv = read_invoice(path)
    except InvoiceReadError as exc:
        return FileResult(path.name, "error", f"Could not be read: {exc}.")
    except Exception as exc:                        # damaged / locked file
        return FileResult(path.name, "error",
                          f"Could not be read ({exc.__class__.__name__}).")
    if inv.gstin and inv.gstin != FIRM_GSTIN:
        return FileResult(path.name, "skipped",
                          f"Another firm's invoice (GSTIN {inv.gstin}).", inv)
    if inv.invoice_date is None:
        return FileResult(path.name, "error", "No invoice date found.", inv)
    if (inv.invoice_date.year, inv.invoice_date.month) != (year, month):
        return FileResult(path.name, "skipped",
                          f"Dated {inv.invoice_date:%d-%m-%Y}, not in "
                          f"{month_label(year, month)}.", inv)
    return FileResult(path.name, "read", "", inv)


# ---------------------------------------------------------------------------
# Per-line amounts
# ---------------------------------------------------------------------------
def allocate_lines(amounts: list[float], tax_rate: float, discount: float,
                   tax_total: float, total: float, rounding: float
                   ) -> list[dict]:
    """
    Split an invoice into per-line figures (see module notes).
    Returns one dict per line: before_tax, discount, net, gst.
    """
    gross = sum(amounts) or 1.0
    out = []
    if tax_rate >= 0:
        factor = 1 + tax_rate / 100
        before = [a / factor for a in amounts]
        before_total = sum(before) or 1.0
        for b in before:
            share = discount * b / before_total
            net = b - share
            out.append(dict(before_tax=round(b, 2), discount=round(share, 2),
                            net=round(net, 2), gst=round(net * tax_rate / 100, 2)))
    else:                                        # mixed rates: proportional
        net_total = total - rounding - tax_total
        for a in amounts:
            w = a / gross
            out.append(dict(before_tax=round(a - tax_total * w, 2),
                            discount=round(discount * w, 2),
                            net=round(net_total * w, 2),
                            gst=round(tax_total * w, 2)))
    return out


def _export_shares(inv: ParsedInvoice) -> list[dict]:
    """
    Per-line figures for an invoice from the export: Zoho's values as they
    are. "Before tax" (the line before discount, without GST) is the tax
    inclusive amount less the line's GST share at the line's own rate; the
    discount share is what separates it from Zoho's Item Total.
    """
    out = []
    for l in inv.lines:
        net, gst = round(l.net_value or 0, 2), round(l.gst or 0, 2)
        rate = gst / net if net else 0.0
        before = round(l.amount / (1 + rate), 2) if l.amount else net
        out.append(dict(before_tax=before, discount=round(max(before - net, 0.0), 2),
                        net=net, gst=gst))
    return out


def check_totals(inv: ParsedInvoice) -> list[str]:
    """Differences between the printed figures (empty list = all agree)."""
    problems = []
    if inv.source == "export":
        return _check_export(inv)
    lines_sum = round(sum(l.amount for l in inv.lines), 2)
    if abs(lines_sum - inv.sub_total) > TOLERANCE:
        problems.append(f"Line amounts add up to {lines_sum:,.2f} but the "
                        f"Sub Total is {inv.sub_total:,.2f}.")
    if inv.tax_rate >= 0:
        before = inv.sub_total / (1 + inv.tax_rate / 100)
        expected = before - inv.discount + inv.tax_total + inv.rounding
    else:
        expected = inv.total                     # cannot rebuild: trust total
    if abs(expected - inv.total) > TOLERANCE:
        problems.append(f"Sub Total, discount and GST give {expected:,.2f} "
                        f"but the Total is {inv.total:,.2f}.")
    qty_rate = [l for l in inv.lines if l.qty and l.rate
                and abs(l.qty * l.rate - l.amount) > TOLERANCE]
    for l in qty_rate:
        problems.append(f"Line {l.line_no}: {l.qty:g} × {l.rate:,.2f} is not "
                        f"{l.amount:,.2f}.")
    return problems


def _check_export(inv: ParsedInvoice) -> list[str]:
    """Checks for an invoice from the export (see module notes)."""
    problems = []
    note = inv.extra.get("export_notes", "")
    if note:
        problems.append(note)
    net = round(sum(l.net_value or 0 for l in inv.lines), 2)
    gst = round(sum(l.gst or 0 for l in inv.lines), 2)
    expected = round(net + gst + inv.rounding, 2)
    if abs(expected - inv.total) > TOLERANCE:
        problems.append(f"Line values {net:,.2f} + GST {gst:,.2f} + round-off "
                        f"{inv.rounding:,.2f} give {expected:,.2f} but the Total "
                        f"is {inv.total:,.2f}.")
    return problems


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------
@dataclass
class Issue:
    """
    One thing on Scan review.

    kind      product / salesperson / car / labour / totals / file
    key       identifies the issue for fixes and acknowledgements
              (grouped salesperson / car issues: "name:<printed name>")
    invoices  invoice numbers affected (product issues and grouped
              salesperson / car issues can cover several)
    status    open / skipped (files not used)
    options   for salesperson / car: suggested ids (may be empty)
    """
    kind: str
    key: str
    message: str
    invoices: list[str] = field(default_factory=list)
    file_name: str = ""
    status: str = "open"
    printed: str = ""                       # the text as printed
    options: list[int] = field(default_factory=list)
    grouped: bool = False                   # one row for every invoice showing
                                            # this name (fix applies to all)
    reason: str = ""                        # salesperson / car: not_found /
                                            # branch / several / missing


# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------
class InvoicesRepo:
    """Scanned invoices in the same SQLite database as the masters."""

    def __init__(self, masters: MastersRepo):
        self.masters = masters
        self.conn: sqlite3.Connection = masters.conn

    # ==================================================================
    # Storing a scan
    # ==================================================================
    def store_scan(self, year: int, month: int, folder: str,
                   results: list[FileResult]) -> dict:
        """
        Replace the month's invoices with this scan. Invoice numbers seen
        twice keep the first file; the later one is listed as skipped.
        `folder` is the PDF folder, or (v0.6.0) the path of the export file;
        for the export each result is one invoice, named by its number.
        Returns counts: read, skipped, error.
        """
        key = month_key(year, month)
        now = datetime.now().isoformat(timespec="seconds")
        seen: dict[str, str] = {}
        counts = {"read": 0, "skipped": 0, "error": 0}
        with self.conn:
            self.conn.execute("DELETE FROM invoices WHERE month = ?", (key,))
            self.conn.execute("DELETE FROM scan_files WHERE month = ?", (key,))
            for r in results:
                status, reason = r.status, r.reason
                inv = r.invoice
                if status == "read" and inv.invoice_no in seen:
                    status = "skipped"
                    reason = (f"Invoice {inv.invoice_no} is also in "
                              f"{seen[inv.invoice_no]}; that file was used.")
                if status == "read":
                    seen[inv.invoice_no] = r.file_name
                    self._insert_invoice(key, inv, now)
                counts[status] += 1
                self.conn.execute(
                    "INSERT OR REPLACE INTO scan_files(month, file_name, status, "
                    "reason, invoice_no) VALUES (?, ?, ?, ?, ?)",
                    (key, r.file_name, status, reason,
                     inv.invoice_no if inv else ""))
            self.conn.execute(
                "INSERT OR REPLACE INTO scan_runs(month, folder, scanned_at, "
                "files) VALUES (?, ?, ?, ?)", (key, folder, now, len(results)))
        self.apply_zoho_categories()
        return counts

    def _insert_invoice(self, key: str, inv: ParsedInvoice, now: str) -> None:
        # An invoice number stored under another month (date corrected in
        # Zoho, re-issued PDF) is replaced by this one.
        self.conn.execute("DELETE FROM invoices WHERE invoice_no = ?", (inv.invoice_no,))
        cur = self.conn.execute(
            "INSERT INTO invoices(month, file_name, invoice_no, invoice_date, "
            "seller, gstin, customer, customer_type, salesperson, vehicle, vin, "
            "po_no, terms, place_of_supply, payment_mode, sub_total, discount, "
            "discount_base, taxes_json, tax_total, tax_rate, rounding, total, "
            "payment_made, balance_due, scanned_at, source, status, branch) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, inv.file_name, inv.invoice_no, inv.invoice_date.isoformat(),
             inv.seller, inv.gstin, inv.customer, inv.customer_type,
             inv.salesperson, inv.vehicle, inv.vin, inv.po_no, inv.terms,
             inv.place_of_supply, inv.payment_mode, inv.sub_total, inv.discount,
             inv.discount_base, json.dumps(inv.taxes), inv.tax_total,
             inv.tax_rate, inv.rounding, inv.total, inv.payment_made,
             inv.balance_due, now, inv.source, inv.status, inv.branch))
        invoice_id = cur.lastrowid
        if all(l.net_value is not None for l in inv.lines):
            shares = _export_shares(inv)
        else:
            shares = allocate_lines([l.amount for l in inv.lines], inv.tax_rate,
                                    inv.discount, inv.tax_total, inv.total,
                                    inv.rounding)
        for line, share in zip(inv.lines, shares):
            self.conn.execute(
                "INSERT INTO invoice_lines(invoice_id, line_no, description, sku, "
                "hsn_sac, qty, unit, rate, amount, is_labour_marker, before_tax, "
                "discount_share, net_value, gst, item_type) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (invoice_id, line.line_no, line.description, line.sku,
                 line.hsn_sac, line.qty, line.unit, line.rate, line.amount,
                 int(is_labour_marker(line.description)), share["before_tax"],
                 share["discount"], share["net"], share["gst"], line.item_type))
        for problem in check_totals(inv):
            self.conn.execute(
                "INSERT INTO invoice_checks(invoice_id, message) VALUES (?, ?)",
                (invoice_id, problem))

    # ==================================================================
    # Reading back
    # ==================================================================
    def scan_run(self, year: int, month: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM scan_runs WHERE month = ?",
                                (month_key(year, month),)).fetchone()
        return dict(row) if row else None

    def scan_files(self, year: int, month: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM scan_files WHERE month = ? ORDER BY file_name",
            (month_key(year, month),))]

    def invoices(self, year: int, month: int) -> list[dict]:
        """The month's invoices (oldest first) with matched names filled in."""
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM invoices WHERE month = ? ORDER BY invoice_date, invoice_no",
            (month_key(year, month),))]
        m = self._masters_snapshot()
        for inv in rows:
            inv["lines"] = [dict(l) for l in self.conn.execute(
                "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY line_no",
                (inv["id"],))]
            eid, _ = self._match_executive(inv, m)
            cid, _ = self._match_car(inv, m)
            inv["executive_id"], inv["car_id"] = eid, cid
            inv["executive"] = m["exec_label"].get(eid, "")
            inv["car"] = m["car_label"].get(cid, "")
            for line in inv["lines"]:
                line["product_id"] = (None if line["is_labour_marker"]
                                      else self._match_product(line, m))
                line["product"] = m["product_name"].get(line["product_id"], "")
        return rows

    # ==================================================================
    # Matching
    # ==================================================================
    def _masters_snapshot(self) -> dict:
        """Everything matching needs, read once per call."""
        products = self.masters.list_rows("products")
        execs = self.masters.list_rows("executives")
        cars = self.masters.list_rows("cars")
        aliases: dict[tuple[str, str], int] = {
            (r["kind"], r["raw_key"]): r["target_id"]
            for r in self.conn.execute("SELECT * FROM match_aliases")}
        overrides: dict[tuple[str, str], int] = {
            (r["invoice_no"], r["kind"]): r["target_id"]
            for r in self.conn.execute("SELECT * FROM invoice_overrides")}
        return dict(
            products={name_key(p["name"]): p["id"] for p in products},
            product_sku={p["sku"].lower(): p["id"] for p in products if p["sku"]},
            product_name={p["id"]: p["name"] for p in products},
            product_labour={p["id"]: p["has_labour"] for p in products},
            execs=execs, exec_ids={e["id"] for e in execs},
            exec_label={e["id"]: e["name"] + (f" – {e['branch']}" if e["branch"] else "")
                        for e in execs},
            cars=cars, car_ids={c["id"] for c in cars},
            car_label={c["id"]: MastersRepo.display_name("cars", c) for c in cars},
            aliases=aliases, overrides=overrides)

    def _match_product(self, line: dict, m: dict) -> int | None:
        key = name_key(line["description"])
        pid = m["aliases"].get(("product", key))
        if pid in m["product_name"]:
            return pid
        if key in m["products"]:
            return m["products"][key]
        sku = (line.get("sku") or "").lower()
        return m["product_sku"].get(sku) if sku else None

    def _match_executive(self, inv: dict, m: dict) -> tuple[int | None, tuple]:
        """(executive id or None, (reason, candidate ids))."""
        eid = m["overrides"].get((inv["invoice_no"], "executive"))
        if eid in m["exec_ids"]:
            return eid, ("", [])
        printed = (inv.get("salesperson") or "").strip()
        if not printed:
            return None, ("missing", [])
        eid = m["aliases"].get(("executive", name_key(printed)))
        if eid in m["exec_ids"]:
            return eid, ("", [])
        name, branch = split_salesperson(printed)
        by_name = [e for e in m["execs"] if person_key(e["name"]) == person_key(name)]
        if branch:
            both = [e for e in by_name if branch_key(e["branch"]) == branch_key(branch)]
            if len(both) == 1:
                return both[0]["id"], ("", [])
            if len(both) > 1:
                return None, ("several", [e["id"] for e in both])
        elif len(by_name) == 1:
            return by_name[0]["id"], ("", [])
        # The whole printed text as a name (e.g. a hyphenated name).
        whole = [e for e in m["execs"] if person_key(e["name"]) == person_key(printed)]
        if len(whole) == 1:
            return whole[0]["id"], ("", [])
        if len(by_name) > 1:
            return None, ("several", [e["id"] for e in by_name])
        return None, ("branch" if by_name else "not_found",
                      [e["id"] for e in by_name])

    def _match_car(self, inv: dict, m: dict) -> tuple[int | None, tuple]:
        cid = m["overrides"].get((inv["invoice_no"], "car"))
        if cid in m["car_ids"]:
            return cid, ("", [])
        printed = (inv.get("vehicle") or "").strip()
        if not printed:
            return None, ("missing", [])
        cid = m["aliases"].get(("car", vehicle_key(printed)))
        if cid in m["car_ids"]:
            return cid, ("", [])
        key = vehicle_key(printed)
        found = [c for c in m["cars"] if key in (vehicle_key(c["model"]),
                                                 vehicle_key(c["make"] + c["model"]))]
        if len(found) == 1:
            return found[0]["id"], ("", [])
        return None, ("several" if found else "not_found", [c["id"] for c in found])

    # ==================================================================
    # Issues
    # ==================================================================
    def issues(self, year: int, month: int) -> list[Issue]:
        """Everything on the month's invoices that still needs attention,
        followed by the files that were not used."""
        m = self._masters_snapshot()
        acks = {(r["invoice_no"], r["kind"]) for r in self.conn.execute(
            "SELECT invoice_no, kind FROM issue_acks")}
        out: list[Issue] = []
        unmatched: dict[str, Issue] = {}         # item name key -> issue
        grouped: dict[tuple[str, str], Issue] = {}   # (kind, printed key) -> issue

        for inv in self.conn.execute(
                "SELECT * FROM invoices WHERE month = ? ORDER BY invoice_no",
                (month_key(year, month),)).fetchall():
            inv = dict(inv)
            no = inv["invoice_no"]
            lines = [dict(l) for l in self.conn.execute(
                "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY line_no",
                (inv["id"],))]

            # --- items ------------------------------------------------------
            for line in lines:
                if line["is_labour_marker"]:
                    continue
                pid = self._match_product(line, m)
                if pid is None:
                    k = name_key(line["description"])
                    issue = unmatched.get(k)
                    if issue is None:
                        issue = Issue("product", k, "", printed=line["description"])
                        unmatched[k] = issue
                        out.append(issue)
                    if no not in issue.invoices:
                        issue.invoices.append(no)

            # --- salesperson ------------------------------------------------
            eid, (why, cands) = self._match_executive(inv, m)
            if eid is None:
                printed = inv["salesperson"]
                text = {"missing": "No salesperson printed on the invoice.",
                        "several": f"“{printed}” matches more than one sales executive.",
                        "branch": f"“{printed}”: no executive with that name at that branch.",
                        "not_found": f"Salesperson “{printed}” is not in the Sales "
                                     "executive master."}[why]
                self._add_person_issue(out, grouped, "salesperson", why, no, inv,
                                       printed, name_key(printed), text, cands)

            # --- car ----------------------------------------------------------
            cid, (why, cands) = self._match_car(inv, m)
            if cid is None:
                printed = inv["vehicle"]
                text = {"missing": "No vehicle printed on the invoice.",
                        "several": f"Vehicle “{printed}” matches more than one car.",
                        "not_found": f"Vehicle “{printed}” is not in the Car master."}[why]
                self._add_person_issue(out, grouped, "car", why, no, inv, printed,
                                       vehicle_key(printed), text, cands)

            # (Until v0.6.2 an invoice with a Rs. 1 labour line but no product
            # needing labour was flagged here. The client confirmed the Rs. 1
            # lines are to be ignored - labour comes from the product only -
            # so that check was removed in v0.6.3.)

            # --- totals checks --------------------------------------------------
            checks = [r["message"] for r in self.conn.execute(
                "SELECT message FROM invoice_checks WHERE invoice_id = ?", (inv["id"],))]
            if checks and (no, "totals") not in acks:
                out.append(Issue("totals", no, " ".join(checks), [no], inv["file_name"]))

        for issue in unmatched.values():
            n = len(issue.invoices)
            issue.message = (f"Item “{issue.printed}” is not in the Product master"
                             + (f" (on {n} invoices)." if n > 1 else "."))
        for issue in grouped.values():
            n = len(issue.invoices)
            if n > 1:
                issue.message = issue.message.rstrip(".") + f" (on {n} invoices)."

        for f in self.scan_files(year, month):
            if f["status"] != "read":
                out.append(Issue("file", f["file_name"], f["reason"],
                                 [f["invoice_no"]] if f["invoice_no"] else [],
                                 f["file_name"], status="skipped"))
        return out

    @staticmethod
    def _add_person_issue(out: list, grouped: dict, kind: str, why: str, no: str,
                          inv: dict, printed: str, raw_key: str, text: str,
                          cands: list[int]) -> None:
        """
        A salesperson / car issue. Names that are simply not found (or at
        another branch) are listed ONCE per printed name, with every invoice
        showing it (v0.6.1) - one choice then fixes them all. An ambiguous
        name ("several") or a missing one must be decided invoice by invoice,
        so those stay one row per invoice. Grouped issues have the key
        "name:<printed key>" and `grouped=True`.
        """
        if why in ("several", "missing") or not raw_key:
            out.append(Issue(kind, no, text, [no], inv["file_name"],
                             printed=printed, options=cands, reason=why))
            return
        issue = grouped.get((kind, raw_key))
        if issue is None:
            issue = Issue(kind, f"name:{raw_key}", text, [], inv["file_name"],
                          printed=printed, options=cands, grouped=True, reason=why)
            grouped[(kind, raw_key)] = issue
            out.append(issue)
        issue.invoices.append(no)

    # ==================================================================
    # Fixes (each one logged in the audit log)
    # ==================================================================
    def _log(self, record: str, field_label: str, new: str) -> None:
        self.masters._audit("scan", None, record, "Edited", field_label, "", new,
                            "Scan review")

    def map_product(self, printed: str, product_id: int) -> None:
        """Remember that this item name means this product (all invoices)."""
        name = self.masters.get("products", product_id)["name"]
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO match_aliases(kind, raw_key, target_id, "
                "created_at) VALUES ('product', ?, ?, ?)",
                (name_key(printed), product_id,
                 datetime.now().isoformat(timespec="seconds")))
            self._log(f"Item “{printed}”", "Product", name)
        self.apply_zoho_categories()          # the item's Zoho type now applies

    def set_salesperson(self, invoice_no: str, printed: str, executive_id: int,
                        all_invoices: bool) -> None:
        """Choose the executive for one invoice, or for every invoice
        printing the same salesperson text."""
        label = MastersRepo.display_name(
            "executives", self.masters.get("executives", executive_id))
        self._set_target("executive", invoice_no, name_key(printed), executive_id,
                         all_invoices, "Salesperson", printed, label)

    def set_car(self, invoice_no: str, printed: str, car_id: int,
                all_invoices: bool) -> None:
        label = MastersRepo.display_name("cars", self.masters.get("cars", car_id))
        self._set_target("car", invoice_no, vehicle_key(printed), car_id,
                         all_invoices, "Car", printed, label)

    def _set_target(self, kind: str, invoice_no: str, raw_key: str, target: int,
                    all_invoices: bool, field_label: str, printed: str,
                    label: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            if all_invoices and raw_key:
                self.conn.execute(
                    "INSERT OR REPLACE INTO match_aliases(kind, raw_key, target_id, "
                    "created_at) VALUES (?, ?, ?, ?)", (kind, raw_key, target, now))
                record = f"All invoices showing “{printed}”"
            else:
                self.conn.execute(
                    "INSERT OR REPLACE INTO invoice_overrides(invoice_no, kind, "
                    "target_id, created_at) VALUES (?, ?, ?, ?)",
                    (invoice_no, kind, target, now))
                record = f"Invoice {invoice_no}"
            self._log(record, field_label, label)

    def apply_zoho_categories(self) -> int:
        """
        Give products whose Category was never set by hand the category of
        Zoho's Item Type on the invoices (see module notes, item 5).

        "Set by hand" = the audit log has a Category change for the product
        from anywhere other than this step, or the product was added on the
        Masters screen (where the category is chosen). A product sold as
        both goods and service in Zoho is left alone. Returns the number of
        products changed.
        """
        seen: dict[int, set[str]] = {}
        m = self._masters_snapshot()
        for line in self.conn.execute(
                "SELECT description, sku, item_type FROM invoice_lines "
                "WHERE item_type <> '' AND is_labour_marker = 0").fetchall():
            pid = self._match_product(dict(line), m)
            category = ZOHO_ITEM_TYPES.get(line["item_type"])
            if pid is not None and category:
                seen.setdefault(pid, set()).add(category)
        if not seen:
            return 0
        by_hand = {r["record_id"] for r in self.conn.execute(
            "SELECT DISTINCT record_id FROM audit_log WHERE master = 'products' "
            "AND ((field = 'Category' AND source <> ?) "
            "     OR (action = 'Added' AND source = 'Masters screen'))",
            (ZOHO_CATEGORY_SOURCE,))}
        changed = 0
        with self.conn:
            for pid, cats in seen.items():
                if len(cats) != 1 or pid in by_hand:
                    continue
                product = self.masters.get("products", pid)
                new = next(iter(cats))
                if product is None or product["category"] == new:
                    continue
                self.conn.execute("UPDATE products SET category = ? WHERE id = ?",
                                  (new, pid))
                self.masters._audit("products", pid, product["name"], "Edited",
                                    "Category", product["category"], new,
                                    ZOHO_CATEGORY_SOURCE)
                changed += 1
        return changed

    def acknowledge(self, invoice_no: str, kind: str, note: str = "") -> None:
        """Accept a totals difference or a labour note for one invoice."""
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO issue_acks(invoice_no, kind, note, at) "
                "VALUES (?, ?, ?, ?)",
                (invoice_no, kind, note, datetime.now().isoformat(timespec="seconds")))
            self._log(f"Invoice {invoice_no}",
                      "Totals check" if kind == "totals" else "Labour check",
                      "Accepted as correct")
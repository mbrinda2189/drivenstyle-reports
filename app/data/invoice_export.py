"""
invoice_export.py - Read Zoho's invoice export (Invoice.csv / .xlsx)
====================================================================

WHAT THIS MODULE DOES
---------------------
From v0.6.0 the month's invoices come from Zoho Books' invoice EXPORT
(Sales > Invoices > Export), not from the invoice PDFs. The export is a
spreadsheet with ONE ROW PER INVOICE LINE and about 180 columns; the
invoice-level columns (number, date, salesperson, total ...) are repeated
on every line of the same invoice.

`read_export(path)` reads the file and returns an `ExportResult` holding
one `ParsedInvoice` per invoice number - the same object the PDF reader
(invoice_reader.py, kept in the code but no longer on the screen) produces,
so matching, Scan review and the reports work exactly as before.

`classify_export(path, year, month)` turns that into the FileResult list
that invoices_repo.store_scan saves, keeping only the chosen month.

THE COLUMNS USED (all others are ignored)
-----------------------------------------
    Invoice level (taken from the invoice's first line)
        Invoice Number, Invoice Date, Invoice Status, Customer Name,
        Sales person, CF.Vehicle, CF.VIN / Registration Number,
        CF.Customer Type, CF.Branch, CF.Invoice Type, PurchaseOrder,
        Place of Supply, Payment Terms Label, Due Date, SubTotal,
        Entity Discount Amount, Round Off, Total, Balance,
        Supplier Org Name, Supplier GST Registration Number
    Line level
        Item Name, SKU, HSN/SAC, Item Type (goods / service), Quantity,
        Usage unit, Item Price (tax inclusive), Item Total, Item Tax %,
        Item Tax Amount, CGST / SGST / IGST (+ their Rate % columns)

    Headings are compared ignoring capitals, spaces and punctuation, so
    "Invoice Number" and "invoice_number" are the same. The file must have
    at least Invoice Number, Invoice Date, Item Name and Item Total.

WHY THE EXPORT IS BETTER THAN THE PDF
-------------------------------------
Zoho already splits the invoice discount over the lines:

    Item Total        the line's value AFTER its share of the invoice
                      discount and EXCLUDING GST  -> "sales" in the reports
    Item Tax Amount   the GST on that line

This was checked against the tool's own PDF allocation to the paisa on
DNS-226-2627, DNS26-GST-0753 and DNS26-GST1-0770, so the figures are used
as they are - nothing has to be worked out or read from a page layout.

The check on every invoice becomes
    sum of Item Total + sum of Item Tax Amount + Round Off = Total
(a difference above Rs. 1 goes to Scan review, as before).

OTHER FIGURES
-------------
    payment_made    Total - Balance   (Overdue invoices have a balance)
    payment_mode    CF.Invoice Type (UPI / Cash / CHY). Used by report 11
                    only when the Payments Received export has nothing for
                    the invoice (agreed: the payments export stays the main
                    source).
    branch          CF.Branch - stored, not yet used in the reports (agreed:
                    reports keep the salesperson's branch from the Sales
                    executive master).
    item_type       Item Type per line; products whose Category was never
                    set by hand take it (see invoices_repo.apply_zoho_categories).

WHICH INVOICES ARE LEFT OUT
---------------------------
    other months    not listed at all - an export may cover a whole quarter;
                    the count is reported in the log
    Void / Draft    listed as skipped (a cancelled or unfinished invoice is
                    not a sale)
    another GSTIN   listed as skipped (not a Drive N Style invoice)
    Invoice columns that differ between the lines of one invoice (should
    never happen in a Zoho export) are noted as a totals check.

ERRORS
------
`ExportFileError` is raised with a plain reason when the file is not a
spreadsheet, cannot be opened, or is not a Zoho invoice export.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from app.data.invoice_reader import InvoiceLine, ParsedInvoice, _gst_rate, parse_date
from app.data.master_defs import header_key

SUPPORTED = (".csv", ".xlsx", ".xlsm")
REQUIRED = ("Invoice Number", "Invoice Date", "Item Name", "Item Total")
LEFT_OUT_STATUSES = {"void": "Void (cancelled) in Zoho.",
                     "draft": "Still a draft in Zoho - not issued."}
# Invoice-level columns that must be the same on every line of an invoice.
SAME_ON_EVERY_LINE = ("Invoice Date", "Sales person", "CF.Vehicle", "Total",
                      "Round Off", "Customer Name")


class ExportFileError(Exception):
    """The file is not a usable Zoho invoice export."""


@dataclass
class ExportResult:
    """Everything read from one export file."""
    file_name: str
    rows: int                                   # data rows (invoice lines)
    invoices: list[ParsedInvoice] = field(default_factory=list)
    notes: dict[str, list[str]] = field(default_factory=dict)  # invoice -> problems


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------
def _read_rows(path: Path) -> list[list]:
    """All rows of the CSV, or of the first sheet of the workbook."""
    ext = path.suffix.lower()
    if ext == ".xls":
        raise ExportFileError("Old-style .xls files cannot be read. Export the "
                              "invoices from Zoho as CSV or XLSX.")
    if ext not in SUPPORTED:
        raise ExportFileError("Choose Zoho's invoice export (.csv or .xlsx).")
    try:
        if ext == ".csv":
            for encoding in ("utf-8-sig", "cp1252"):
                try:
                    with open(path, newline="", encoding=encoding) as fh:
                        return [row for row in csv.reader(fh)]
                except UnicodeDecodeError:
                    continue
            raise ExportFileError("The CSV file's text encoding was not recognised.")
        wb = load_workbook(path, read_only=True, data_only=True)
        rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        wb.close()
        return rows
    except ExportFileError:
        raise
    except Exception as exc:                          # damaged / locked file
        raise ExportFileError(f"The file could not be opened: {exc}") from exc


def _text(value) -> str:
    """Cell as clean text ('33.0' from Excel becomes '33')."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).split())


def _number(value) -> float:
    """Cell as a number; blank or unreadable -> 0."""
    if isinstance(value, (int, float)):
        return float(value)
    text = _text(value).replace(",", "").replace("₹", "").replace("INR", "").strip()
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def _date(value) -> date | None:
    """2026-09-04 (Zoho), 04/09/2026, or an Excel date -> date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return parse_date(text)


def read_export(path: str | Path) -> ExportResult:
    """Read the export into one ParsedInvoice per invoice number."""
    path = Path(path)
    raw = _read_rows(path)
    if not raw:
        raise ExportFileError("The file is empty.")
    heads = [header_key(h or "") for h in raw[0]]
    col: dict[str, int] = {}
    for i, h in enumerate(heads):
        col.setdefault(h, i)                       # first column of that name
    missing = [c for c in REQUIRED if header_key(c) not in col]
    if missing:
        raise ExportFileError(
            "This does not look like Zoho's invoice export: the column"
            f"{'s' if len(missing) > 1 else ''} {', '.join(missing)} "
            f"{'are' if len(missing) > 1 else 'is'} missing.")

    result = ExportResult(path.name, 0)
    by_no: dict[str, ParsedInvoice] = {}
    first_row: dict[str, list] = {}

    for row in raw[1:]:
        def cell(name: str, _row=row):
            i = col.get(header_key(name))
            return _row[i] if i is not None and i < len(_row) else None

        no = _text(cell("Invoice Number"))
        if not no:
            continue                               # blank / footer row
        result.rows += 1
        inv = by_no.get(no)
        if inv is None:
            inv = _new_invoice(path.name, no, cell)
            by_no[no] = inv
            first_row[no] = row
            result.invoices.append(inv)
        else:
            for name in SAME_ON_EVERY_LINE:
                i = col.get(header_key(name))
                if i is not None and _text(first_row[no][i] if i < len(first_row[no]) else None) \
                        != _text(cell(name)):
                    result.notes.setdefault(no, []).append(
                        f"“{name}” differs between the lines of this invoice in the export.")
        _add_line(inv, cell)

    for inv in result.invoices:
        inv.tax_rate = _gst_rate(inv.taxes)
        inv.sub_total = round(sum(l.amount for l in inv.lines), 2)
    for no, notes in result.notes.items():
        result.notes[no] = list(dict.fromkeys(notes))     # each note once
    return result


def _new_invoice(file_name: str, no: str, cell) -> ParsedInvoice:
    """The invoice-level fields, from the invoice's first line."""
    total = _number(cell("Total"))
    balance = _number(cell("Balance"))
    return ParsedInvoice(
        file_name=file_name, source="export",
        seller=_text(cell("Supplier Org Name")),
        gstin=_text(cell("Supplier GST Registration Number")).upper(),
        invoice_no=no,
        invoice_date=_date(cell("Invoice Date")),
        terms=_text(cell("Payment Terms Label")),
        due_date=_date(cell("Due Date")),
        po_no=_text(cell("PurchaseOrder")),
        place_of_supply=_text(cell("Place of Supply")),
        salesperson=_text(cell("Sales person")),
        customer_type=_text(cell("CF.Customer Type")),
        vehicle=_text(cell("CF.Vehicle")),
        vin=_text(cell("CF.VIN / Registration Number")),
        payment_mode=_text(cell("CF.Invoice Type")),
        customer=_text(cell("Customer Name")),
        discount=round(_number(cell("Entity Discount Amount")), 2),
        rounding=round(_number(cell("Round Off")), 2),
        total=round(total, 2),
        payment_made=round(total - balance, 2),
        balance_due=round(balance, 2),
        status=_text(cell("Invoice Status")),
        branch=_text(cell("CF.Branch")),
    )


def _add_line(inv: ParsedInvoice, cell) -> None:
    """One export row -> one InvoiceLine, and its GST into the invoice's taxes."""
    qty = _number(cell("Quantity")) or 1.0
    price = _number(cell("Item Price"))
    net = round(_number(cell("Item Total")), 2)
    gst = round(_number(cell("Item Tax Amount")), 2)
    inv.lines.append(InvoiceLine(
        line_no=len(inv.lines) + 1,
        description=_text(cell("Item Name")),
        hsn_sac=_text(cell("HSN/SAC")),
        qty=qty, unit=_text(cell("Usage unit")), rate=price,
        amount=round(qty * price, 2),              # tax inclusive, before discount
        sku=_text(cell("SKU")),
        net_value=net, gst=gst,
        item_type=_text(cell("Item Type")).lower()))
    # Tax heads as the PDF reader names them ("CGST 9%"), so tax_rate works
    # the same way: CGST 9% + SGST 9% -> 18.
    for head in ("CGST", "SGST", "IGST"):
        amount = _number(cell(head))
        if amount:
            rate = _number(cell(f"{head} Rate %"))
            if not rate:                           # rate column missing
                total_rate = _number(cell("Item Tax %"))
                rate = total_rate if head == "IGST" else total_rate / 2
            key = f"{head} {rate:g}%"
            inv.taxes[key] = round(inv.taxes.get(key, 0.0) + amount, 2)
    if gst and not any(_number(cell(h)) for h in ("CGST", "SGST", "IGST")):
        # Only the total GST is given: split it half and half (intra-state).
        rate = _number(cell("Item Tax %"))
        for head in ("CGST", "SGST"):
            key = f"{head} {rate / 2:g}%"
            inv.taxes[key] = round(inv.taxes.get(key, 0.0) + gst / 2, 2)


# ---------------------------------------------------------------------------
# Keeping the chosen month
# ---------------------------------------------------------------------------
@dataclass
class ExportScan:
    """What classify_export found (see invoices_repo.store_scan)."""
    results: list                      # FileResult, one per invoice of the month
    other_months: int                  # invoices dated in other months (ignored)
    rows: int
    file_name: str


def classify_export(path: str | Path, year: int, month: int,
                    firm_gstin: str) -> ExportScan:
    """
    The export's invoices for the chosen month, as FileResult entries (the
    "file name" of each entry is the invoice number). Raises ExportFileError.
    """
    from app.data.invoices_repo import FileResult     # avoid a circular import

    exp = read_export(path)
    results, other = [], 0
    for inv in exp.invoices:
        if inv.invoice_date is None:
            results.append(FileResult(inv.invoice_no, "error",
                                      "No invoice date in the export.", inv))
            continue
        if (inv.invoice_date.year, inv.invoice_date.month) != (year, month):
            other += 1
            continue
        # Lines of one invoice that disagree become a totals check (Scan review).
        inv.extra["export_notes"] = " ".join(exp.notes.get(inv.invoice_no, []))
        status = inv.status.lower()
        if status in LEFT_OUT_STATUSES:
            results.append(FileResult(inv.invoice_no, "skipped",
                                      LEFT_OUT_STATUSES[status], inv))
        elif inv.gstin and inv.gstin != firm_gstin:
            results.append(FileResult(inv.invoice_no, "skipped",
                                      f"Another firm's invoice (GSTIN {inv.gstin}).", inv))
        else:
            results.append(FileResult(inv.invoice_no, "read", "", inv))
    return ExportScan(results, other, exp.rows, exp.file_name)

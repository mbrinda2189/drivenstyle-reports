"""
raised_prices.py - "Prices above fixed price" (v0.35.0)
=======================================================

WHY THIS REPORT
---------------
The client found that salespeople were typing an item ABOVE its fixed price
on the invoice and then giving a "discount", so the customer saw a big
discount that had mostly been added on first (estimate 515: prices raised
by Rs. 4,900, discount Rs. 4,400). From v0.35.0 the spot incentive is
measured against the fixed prices of the whole invoice, so this no longer
changes the incentive (reports/data.py, INCENTIVES). The client still wants
to SEE who does it - this report lists every such item.

WHAT IS LISTED
--------------
Every invoice line typed above its fixed price by more than Rs. 1 -
`MonthData.raised_prices()`. Fixed price per unit, GST-inclusive:
    the bill value of the item's incentive group (Incentive master), else
    the selling price (Product master), else nothing to compare with (the
    line is not listed).
Typed price = the line amount as printed on the invoice / qty (GST-inclusive,
before the invoice discount). Every item is listed, with or without an
incentive (Brinda, 16-11-2026).

WHERE IT APPEARS
----------------
    Excel     sheet "7b Prices above fixed price", written right after
              "7 Spot incentive" whenever that report is chosen:
                By salesperson                  invoices, items, total raised,
                                                discount shown on those invoices
                Every item typed above its fixed price   one row per line
    PDF       the INTERNAL TEAM PDF, straight after the Spot incentive
              (management PDF: not included). Eight columns at most, like
              every PDF table (pdf_book.py, LAYOUT).

"PAID VS FIXED" - THE LAST COLUMN
---------------------------------
For the invoice as a whole: what the customer paid minus the invoice's fixed
prices. Zero or more (+) = the "discount" was only on paper and the full
incentive was earned; below zero (-) = the customer really paid less than
the fixed prices, and the incentive was cut in that proportion.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from app.reports.data import MonthData
from app.reports.workbook import Col, _finish, section, table, title

SHEET = "7b Prices above fixed price"
PDF_SECTION = "Prices above fixed price"

NOTES = [
    "Every item typed on an invoice above its fixed price by more than Rs. 1.",
    "Fixed price per unit, including GST: the bill value of the item's incentive group "
    "(Incentive master), else its selling price (Product master).",
    "Typed price = the line amount on the invoice ÷ qty, including GST, before the invoice "
    "discount. Raised by = (typed price − fixed price) × qty.",
    "Paid vs fixed (whole invoice): what the customer paid minus the invoice's fixed prices. "
    "+ means the discount was only on paper (full incentive); − means the customer paid less "
    "than the fixed prices (incentive cut in proportion).",
]


def _summary_cols() -> list[Col]:
    return [
        Col("Salesperson", "executive", width=30),
        Col("Invoices", "invoices", "qty", 10, total="sum"),
        Col("Items raised", "items", "qty", 10, total="sum"),
        Col("Total raised by", "raised", "money", 15, total="sum"),
        Col("Discount shown on those invoices", "discount", "money", 17, total="sum"),
    ]


def _yes_no(rows: list[dict]) -> list[dict]:
    return [dict(r, incentive="Yes" if r["has_incentive"] else "No") for r in rows]


def raised_sheet(ws: Worksheet, d: MonthData) -> None:
    """Excel sheet "7b Prices above fixed price" (see module notes)."""
    rows = d.raised_prices()
    row = title(ws, "Prices typed above the fixed price", d.label, NOTES)
    row = section(ws, row, "By salesperson")
    t = table(ws, row, _summary_cols(), d.raised_by_executive(),
              empty_text="No item was typed above its fixed price this month.")
    row = section(ws, t["next"] + 1, "Every item typed above its fixed price")
    t = table(ws, row, [
        Col("Salesperson", "executive", width=26),
        Col("Invoice no", "invoice_no", width=17),
        Col("Date", "date", "date", 11),
        Col("Customer", "customer", width=24),
        Col("Item as billed", "product", width=36),
        Col("Qty", "qty", "qty", 6),
        Col("Typed price / unit", "typed_unit", "money", 13),
        Col("Fixed price / unit", "fixed_unit", "money", 13),
        Col("Fixed price from", "fixed_source", width=13),
        Col("Raised by", "raised", "money", 12, total="sum"),
        Col("Raised by %", "raised_pct", "pct", 10),
        Col("Item has incentive", "incentive", width=10),
        Col("Discount on invoice", "inv_discount", "money", 13),
        Col("Customer paid (invoice)", "inv_paid", "money", 14),
        Col("Fixed prices (invoice)", "inv_fixed", "money", 14),
        Col("Paid vs fixed (invoice)", "inv_over", "money", 14),
    ], _yes_no(rows), filters=True,
        empty_text="No item was typed above its fixed price this month.")
    _finish(ws, f"A{t['head'] + 1}" if rows else None)


def raised_pdf(ws: Worksheet, d: MonthData) -> None:
    """The same report for the internal team PDF: the summary by
    salesperson and every item, in at most eight columns."""
    rows = d.raised_prices()
    row = title(ws, "Prices typed above the fixed price", d.label, [
        "Items typed above their fixed price (bill value, else selling price - including GST) "
        "by more than Rs. 1. Paid vs fixed: the whole invoice - '+' means the discount was "
        "only on paper."])
    row = section(ws, row, "By salesperson")
    t = table(ws, row, _summary_cols(), d.raised_by_executive(),
              empty_text="No item was typed above its fixed price this month.")
    if rows:
        row = section(ws, t["next"], "Every item typed above its fixed price")
        table(ws, row, [
            Col("Item as billed", "product", width=40),
            Col("Invoice no", "invoice_no", width=16),
            Col("Salesperson", "executive", width=16),
            Col("Typed price / unit", "typed_unit", "money", 13),
            Col("Fixed price / unit", "fixed_unit", "money", 13),
            Col("Raised by", "raised", "money", 12, total="sum"),
            Col("Discount on invoice", "inv_discount", "money", 13),
            Col("Paid vs fixed (invoice)", "inv_over", "money", 13),
        ], rows)
    _finish(ws)

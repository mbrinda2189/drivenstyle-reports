"""
pdf_book.py - The "PDF version" of the reports (v0.10.0; one flowing
document without graphs from v0.10.3)
====================================================================

WHY A SEPARATE VERSION
----------------------
The Excel workbook is the working paper: every invoice, every line, every
formula. The PDF is what the owner reads and prints. Brinda asked for the
PDF to carry only the summary tables while the Excel workbook stays exactly
as it is, and then (04-10-2026) for: no graphs, no empty white space, page
numbers in the footer, and print large enough to read.

So the tool writes a second, temporary workbook laid out for reading -
this module - and Excel turns THAT into the PDF (pdf_export.py). The
temporary workbook is deleted afterwards.

WHAT IS IN THE PDF, in this order
---------------------------------
    Summary              executive summary WITHOUT "Points needing attention"
                         (the Cover block - "Monthly reports ... Notes" -
                         was dropped from the PDF in v0.10.5)
    Service vs product   summary table only
    Labour               "By product" table only
    Vehicle-wise         "By segment" table only
    Spot incentive       "By executive" only, highest payable first
    High-profit          top 10 products and top 10 services
    Indirect vs direct   as in the workbook
    Payment modes        by mode, by account deposited to
    Profit & loss        as in the workbook
    New-car penetration  as in the workbook (needs the delivery list)
    New-car vs other     "Where the month's business came from"
    Trend                only when two or more months are read (trend.py)
NOT in the PDF: invoice profitability, packages, executive-wise sales,
missed opportunity, RTO list vs invoices, consultant scorecard, not
included. They remain in the Excel workbook.

LAYOUT (v0.10.3)
----------------
* ONE continuous sheet: each section is first written on a sheet of its
  own (the same code as before), then copied one below the other onto a
  single "Report" sheet (formulas are shifted to their new rows). Excel
  starts a new page for every sheet, so separate sheets meant a page per
  section with most of it empty; one sheet lets the sections follow each
  other with no gaps.
* No forced page breaks: Excel moves to the next page only when a page is
  full, so no page is left partly empty. (A long table can therefore
  continue on the next page.)
* PRINT SIZE: A4 landscape, fitted to the page WIDTH only (never squeezed
  to one page high). No table is wider than eight columns and column
  widths are capped (FIRST_COL / OTHER_COL), so the sheet is about as wide
  as the page and the 10 pt text prints at (or very near) 10 pt. For this
  the New-car penetration table, 11 columns in Excel, is shown here as two
  tables with the same figures: DNS accessories, then OE accessories.
  (A Trend page with many months is wider and prints smaller.)
* Footer on every page: "Drive N Style - <month>" on the left and
  "Page x of y" on the right.
* No graphs. (The Excel Trend sheet keeps its charts.)

PERCENTAGES RUN DOWNWARDS (v0.10.5)
-----------------------------------
Where a table's point is a percentage, its rows are listed from the
highest to the lowest: share of sales (Service vs product, New-car vs
other), % of sales of the indirect cost heads (Indirect vs direct, Profit &
loss), % of invoice total (Payment modes) and penetration % (Summary and
New-car penetration, DNS tables), and - from v0.11.0 - margin %: the
Summary's top products / executives / branches and the High-profit top 10s
are still CHOSEN by gross profit but LISTED highest margin % first; New-car
vs other and the Summary's Costs table likewise. Tables without a
percentage keep their ranking by amount: spot incentive by incentive
payable, labour by labour cost, segments by sales.
The Excel workbook keeps its own order.

No Qt and no database code here.
"""

from __future__ import annotations

from collections import defaultdict
import re
from copy import copy
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.data.payments_io import Payment
from app.reports import rto_reports as rr
from app.reports.data import MonthData
from app.reports.trend import trend_sheet
from app.reports.workbook import (
    Col, _by_product, _finish, cost_split_sheet, exec_label, pnl_sheet,
    section, table, title)

MARGIN = '=IF({sales}{r}=0,"",{gp}{r}/{sales}{r})'
GP = "={sales}{r}-{cost}{r}-{labour}{r}"

FIRST_COL, OTHER_COL = 42, 14.5     # widest a column may be on the report sheet
GAP_ROWS = 2                        # blank rows between two sections


class Page:
    """Kept from v0.10.0 (when pages carried graphs): the next free row."""

    def __init__(self, ws: Worksheet, row: int):
        self.ws, self.row = ws, row

    def finish(self) -> None:
        _finish(self.ws)


def _bottom(ws: Worksheet) -> int:
    return ws.max_row + 3


# ---------------------------------------------------------------------------
# The sheets
# ---------------------------------------------------------------------------

def _category(ws, d):
    row = title(ws, "Service vs product profitability", d.label,
                ["Category comes from the Product master. Sales exclude GST."])
    groups: dict[str, dict] = {}
    for l in d.lines:
        g = groups.setdefault(l.category, dict(category=l.category, qty=0.0, sales=0.0,
                                               cost=0.0, labour=0.0))
        g["qty"] += l.qty
        for k in ("sales", "cost", "labour"):
            g[k] = round(g[k] + getattr(l, k), 2)
    rows = sorted(groups.values(), key=lambda g: -g["sales"])
    total = sum(g["sales"] for g in rows)
    for g in rows:
        g["share"] = g["sales"] / total if total else ""
    t = table(ws, row, [
        Col("Category", "category", width=22),
        Col("Qty", "qty", "qty", 10, total="sum"),
        Col("Sales", "sales", "money", 15, total="sum"),
        Col("Product cost", "cost", "money", 15, total="sum"),
        Col("Labour", "labour", "money", 13, total="sum"),
        Col("Gross profit", "gp", "money", 15, formula=GP, total="sum"),
        Col("Margin %", "margin", "pct", 11, formula=MARGIN, total=MARGIN),
        Col("Share of sales", "share", "pct", 12),
    ], rows)
    p = Page(ws, t["next"])
    p.finish()


def _labour(ws, d):
    row = title(ws, "Labour calculation", d.label,
                ["Labour cost = labour charge in the Product master × quantity, for products "
                 "marked 'Labour involved'."])
    groups: dict[str, dict] = {}
    for l in d.lines:
        if l.labour:
            g = groups.setdefault(l.product, dict(product=l.product, qty=0.0, labour=0.0))
            g["qty"] += l.qty
            g["labour"] = round(g["labour"] + l.labour, 2)
    rows = sorted(groups.values(), key=lambda g: -g["labour"])
    row = section(ws, row, "By product")
    t = table(ws, row, [
        Col("Product / service", "product", width=52),
        Col("Qty", "qty", "qty", 10, total="sum"),
        Col("Labour cost", "labour", "money", 16, total="sum"),
    ], rows, empty_text="No labour this month.")
    p = Page(ws, t["next"])
    p.finish()


def _vehicle(ws, d):
    row = title(ws, "Vehicle-wise average per car", d.label,
                ["Each invoice is one car. Segment comes from the Car master."])
    groups: dict[str, dict] = {}
    for i in d.invoices:
        g = groups.setdefault(i.segment or "(no segment)", dict(
            segment=i.segment or "(no segment)", cars=0, sales=0.0, cost=0.0, labour=0.0))
        g["cars"] += 1
        for k in ("sales", "cost", "labour"):
            g[k] = round(g[k] + getattr(i, k), 2)
    rows = sorted(groups.values(), key=lambda g: -g["sales"])
    avg = '=IF({cars}{r}=0,"",{sales}{r}/{cars}{r})'
    avg_gp = '=IF({cars}{r}=0,"",{gp}{r}/{cars}{r})'
    row = section(ws, row, "By segment")
    t = table(ws, row, [
        Col("Segment", "segment", width=26),
        Col("Cars", "cars", "qty", 8, total="sum"),
        Col("Sales", "sales", "money", 15, total="sum"),
        Col("Product cost", "cost", "money", 15, total="sum"),
        Col("Labour", "labour", "money", 13, total="sum"),
        Col("Gross profit", "gp", "money", 15, formula=GP, total="sum"),
        Col("Average sales per car", "avg", "money", 14, formula=avg, total=avg),
        Col("Average profit per car", "avg_gp", "money", 14, formula=avg_gp, total=avg_gp),
    ], rows)
    p = Page(ws, t["next"])
    p.finish()


def incentive_by_executive(d: MonthData) -> list[dict]:
    """Spot incentive per executive by the confirmed rule, highest payable first."""
    groups: dict[str, dict] = {}

    def add(name, full, payable):
        g = groups.setdefault(name, dict(executive=name, n=0, full=0.0, payable=0.0))
        g["n"] += 1
        g["full"] += full
        g["payable"] += payable

    for i in d.invoices:
        if not i.incentive_allowed:           # "Gets incentive = No" (v0.11.0)
            continue
        name = exec_label(i.executive, i.branch)
        for l in i.lines:
            base = l.bill_value * l.qty
            if l.incentive_group:
                full = l.incentive_amount * l.qty
                add(name, full, full * min(1.0, l.billed / base) if base else 0.0)
        k = i.package
        if k:
            add(name, k.incentive, k.incentive * min(1.0, k.billed / k.coupon_value)
                if k.coupon_value else 0.0)
    for g in groups.values():
        g["full"], g["payable"] = round(g["full"], 2), round(g["payable"], 2)
    return sorted(groups.values(), key=lambda g: (-g["payable"], g["executive"]))


def _incentive(ws, d):
    row = title(ws, "Spot incentive calculation", d.label, [
        "Rule: payable = incentive × qty × (amount billed ÷ (bill value × qty)), never more "
        "than the full incentive. Highest incentive payable first."]
        + (["No incentive for executives marked 'Gets incentive = No': "
            + ", ".join(d.no_incentive) + "."] if d.no_incentive else []))
    rows = incentive_by_executive(d)
    row = section(ws, row, "By executive")
    t = table(ws, row, [
        Col("Executive", "executive", width=34),
        Col("Lines", "n", "qty", 9, total="sum"),
        Col("Full incentive", "full", "money", 16, total="sum"),
        Col("Incentive payable", "payable", "money", 16, total="sum"),
        Col("Reduced by discounts", "reduced", "money", 16,
            formula="={full}{r}-{payable}{r}", total="sum"),
    ], rows, empty_text="No lines with an incentive group this month.")
    p = Page(ws, t["next"])
    p.finish()


def _high_profit(ws, d):
    th = d.threshold
    row = title(ws, "High-profit product sales", d.label,
                [f"Items with a margin of {th:g}% or more this month, highest gross profit "
                 "first: the top 10 products and the top 10 services."])
    good = []
    for r in _by_product(d.lines):
        r["_gp"] = round(r["sales"] - r["cost"] - r["labour"], 2)
        if r["sales"] > 0 and r["_gp"] / r["sales"] * 100 >= th - 1e-9:
            good.append(r)
    good.sort(key=lambda r: -r["_gp"])
    # the ten are chosen by gross profit, then listed highest margin % first (v0.11.0)
    by_margin = lambda r: (-(r["_gp"] / r["sales"]), -r["_gp"])
    cols = lambda first: [
        Col(first, "product", width=46),
        Col("Qty", "qty", "qty", 8, total="sum"),
        Col("Sales", "sales", "money", 15, total="sum"),
        Col("Product cost", "cost", "money", 15, total="sum"),
        Col("Labour", "labour", "money", 13, total="sum"),
        Col("Gross profit", "gp", "money", 15, formula=GP, total="sum"),
        Col("Margin %", "margin", "pct", 10, formula=MARGIN, total=MARGIN),
    ]
    p = Page(ws, row)
    for category, heading in (("Product", "Top 10 products"), ("Service", "Top 10 services")):
        rows = sorted([r for r in good if r["category"] == category][:10], key=by_margin)
        r0 = section(ws, p.row, heading)
        t = table(ws, r0, cols("Product" if category == "Product" else "Service"), rows,
                  empty_text=f"No {category.lower()} reached a {th:g}% margin this month.")
        p.row = t["next"]
    p.finish()




def _payments(ws, d, payments: list[Payment] | None):
    by_invoice: dict[str, list[Payment]] = defaultdict(list)
    for pay in payments or []:
        by_invoice[pay.invoice_no].append(pay)
    modes: dict[str, list] = defaultdict(lambda: [0, 0.0])        # mode -> [invoices, amount]
    accounts: dict[str, float] = defaultdict(float)
    pending_n, pending = 0, 0.0
    for i in d.invoices:
        got: dict[str, float] = defaultdict(float)
        for pay in by_invoice.get(i.invoice_no, []):
            got[pay.mode] += pay.amount
            if pay.deposit_to:
                accounts[pay.deposit_to] += pay.amount
        if not got and i.payment_mode and i.payment_made:
            got[i.payment_mode] = i.payment_made
        for m, a in got.items():
            modes[m][0] += a > 0
            modes[m][1] += a
        short = max(0.0, i.total - sum(got.values()))
        pending_n += short > 0
        pending += short
    total = sum(i.total for i in d.invoices)
    rows = [dict(mode=m, n=v[0], amount=round(v[1], 2)) for m, v in sorted(modes.items())]
    rows.append(dict(mode="Not received", n=pending_n, amount=round(pending, 2)))
    rows.sort(key=lambda r: -r["amount"])              # % of invoice total, highest first
    for r in rows:
        r["share"] = r["amount"] / total if total else ""
    source = ("Zoho payments export" if payments is not None else
              "payment mode printed on the invoices (no payments export chosen)")
    row = title(ws, "Payment mode analysis", d.label, [
        f"Source: {source}. All payments applied to the month's invoices are counted, "
        "whatever the payment date.",
        "'Not received' = invoice total less the payments found for it."])
    row = section(ws, row, "By mode")
    t = table(ws, row, [
        Col("Mode", "mode", width=28),
        Col("Invoices", "n", "qty", 11),
        Col("Amount", "amount", "money", 16, total="sum"),
        Col("% of invoice total", "share", "pct", 14),
    ], rows)
    p = Page(ws, t["next"])
    if accounts:
        r0 = section(ws, p.row, "By account deposited to (payments export)")
        t = table(ws, r0, [Col("Deposited to", "acc", width=28),
                           Col("Amount", "amount", "money", 16, total="sum")],
                  [dict(acc=a, amount=round(v, 2)) for a, v in sorted(accounts.items())])
        p.row = t["next"]
    p.finish()



def _penetration(ws, d, link):
    """New-car penetration as in the workbook, but as two narrower tables per
    grouping (DNS, then OE) so the print stays large - see LAYOUT."""
    row = title(ws, "New-car penetration", d.label, [
        "Source: the dealership's delivery (RTO) list. A car 'took DNS' when the list shows "
        "DNS accessories or an invoice is linked to it.",
        "OE = the car maker's accessories. 'OE listed, value blank' = named in the list "
        "without a value, so OE value is understated."])
    pen = '=IF({cars}{r}=0,"",{dns}{r}/{cars}{r})'
    per = '=IF({cars}{r}=0,"",{dns_value}{r}/{cars}{r})'
    for heading, key in (("location", lambda c: c.location),
                         ("model", lambda c: c.model_group)):
        rows = rr._group_rows(link, key)
        first = heading.capitalize()
        by_pen = sorted(rows, key=lambda g: -(g["dns"] / g["cars"] if g["cars"] else 0))
        row = section(ws, row, f"By {heading} - DNS accessories")
        t = table(ws, row, [
            Col(first, "name", width=24),
            Col("Cars delivered", "cars", "qty", 12, total="sum"),
            Col("Took DNS", "dns", "qty", 12, total="sum"),
            Col("Penetration %", "pen", "pct", 12, formula=pen, total=pen),
            Col("DNS value (list)", "dns_value", "money", 14, total="sum"),
            Col("DNS value per car delivered", "per", "money", 14, formula=per, total=per),
            Col("Invoiced (with GST)", "invoiced", "money", 14, total="sum"),
        ], by_pen)                                  # highest penetration % first
        row = section(ws, t["next"], f"By {heading} - OE accessories")
        t = table(ws, row, [
            Col(first, "name", width=24),
            Col("Cars delivered", "cars", "qty", 12, total="sum"),
            Col("Took OE", "oe", "qty", 12, total="sum"),
            Col("OE value (list)", "oe_value", "money", 14, total="sum"),
            Col("OE listed, value blank", "oe_blank", "qty", 14, total="sum"),
            Col("Neither OE nor DNS", "none", "qty", 14, total="sum"),
        ], rows)
        row = t["next"]
    _finish(ws)


def _source(ws, d, link):
    row = title(ws, "New-car vs other business", d.label, [
        "New-car business = invoices linked to a car in this month's delivery list. Other = "
        "every other invoice (walk-in, earlier deliveries, counter sales).",
        "Sales exclude GST. Gross profit = sales - product cost - labour."])
    row = section(ws, row, "Where the month's business came from")
    rows = [rr._business("New cars delivered this month", link.linked),
            rr._business("Other business", link.other)]
    margin = lambda r: (r["sales"] - r["cost"] - r["labour"]) / r["sales"] if r["sales"] else 0
    rows.sort(key=lambda r: -margin(r))                 # highest margin % first
    avg = '=IF({invoices}{r}=0,"",{sales}{r}/{invoices}{r})'
    t = table(ws, row, [
        Col("Business", "name", width=32),
        Col("Invoices", "invoices", "qty", 10, total="sum"),
        Col("Sales", "sales", "money", 15, total="sum"),
        Col("Product cost", "cost", "money", 15, total="sum"),
        Col("Labour", "labour", "money", 13, total="sum"),
        Col("Gross profit", "gp", "money", 15, formula=GP, total="sum"),
        Col("Margin %", "margin", "pct", 10, formula=MARGIN, total=MARGIN),
        Col("Average bill", "avg", "money", 14, formula=avg, total=avg),
    ], rows)
    p = Page(ws, t["next"])
    p.finish()


# ---------------------------------------------------------------------------
# One flowing sheet
# ---------------------------------------------------------------------------
def _used(ws: Worksheet) -> tuple[int, int]:
    """(last row, last column) holding a value."""
    cells = [c for row in ws.iter_rows() for c in row if c.value is not None]
    return (max(c.row for c in cells), max(c.column for c in cells)) if cells else (0, 0)


_CELL = re.compile(r"(\$?[A-Z]{1,3}\$?)(\d+)")


def shift_formula(formula: str, rows: int) -> str:
    """
    Move every cell reference in a formula down by `rows`, INCLUDING the
    fixed ones such as $B$7. A section is copied as one block, so everything
    it refers to moves with it. (v0.10.3 used a helper that leaves $-fixed
    references alone: "% of sales" in the PDF then divided by whatever cell
    happened to sit at the old row - e.g. sales showed 189.2% - fixed in
    v0.10.4.) Only cell references are touched, never text or numbers.
    """
    if not rows:
        return formula
    out = ["="]
    for token in Tokenizer(formula).items:
        value = token.value
        if token.type == "OPERAND" and token.subtype == "RANGE":
            value = _CELL.sub(lambda m: m.group(1) + str(int(m.group(2)) + rows), value)
        out.append(value)
    return "".join(out)


def _append(report: Worksheet, part: Worksheet, at: int) -> int:
    """
    Copy a section's sheet onto the report sheet starting at row `at`;
    returns the number of rows copied. Formulas are shifted to their new
    rows; fonts, fills, borders, number formats and row heights are kept;
    each column becomes as wide as the widest section needs (capped).
    """
    last_row, last_col = _used(part)
    shift = at - 1
    for row in part.iter_rows(min_row=1, max_row=last_row, max_col=last_col):
        for cell in row:
            if cell.value is None and not cell.has_style:
                continue
            target = report.cell(cell.row + shift, cell.column)
            value = cell.value
            if isinstance(value, str) and value.startswith("="):
                value = shift_formula(value, shift)
            target.value = value
            if cell.has_style:
                target._style = copy(cell._style)
            target.hyperlink = None
    for r in range(1, last_row + 1):
        height = part.row_dimensions[r].height
        if height:
            report.row_dimensions[r + shift].height = height
    for c in range(1, last_col + 1):
        letter = get_column_letter(c)
        cap = FIRST_COL if c == 1 else OTHER_COL
        want = min(cap, part.column_dimensions[letter].width or 0)
        if want > (report.column_dimensions[letter].width or 0):
            report.column_dimensions[letter].width = want
    return last_row


def write_pdf_workbook(data: MonthData, months: list[MonthData],
                       payments: list[Payment] | None, path: str | Path,
                       user: str = "", rto: list | None = None,
                       previous: MonthData | None = None,
                       rto_by_month: dict | None = None) -> Path:
    """Write the temporary workbook that Excel turns into the PDF."""
    link = rr.Linked(data, rto) if rto is not None else None
    wb = Workbook()
    report = wb.active
    report.title = "Report"
    plan = [("Summary", lambda ws: rr.summary_sheet(ws, data, previous, link, user,
                                                    attention=False, highest_first=True)),
            ("Service vs product", lambda ws: _category(ws, data)),
            ("Labour", lambda ws: _labour(ws, data)),
            ("Vehicle-wise", lambda ws: _vehicle(ws, data)),
            ("Spot incentive", lambda ws: _incentive(ws, data)),
            ("High-profit products", lambda ws: _high_profit(ws, data)),
            ("Indirect vs direct", lambda ws: cost_split_sheet(ws, data, largest_first=True)),
            ("Payment modes", lambda ws: _payments(ws, data, payments)),
            ("Profit & loss", lambda ws: pnl_sheet(ws, data, largest_first=True))]
    if link is not None:
        plan += [("New-car penetration", lambda ws: _penetration(ws, data, link)),
                 ("New-car vs other", lambda ws: _source(ws, data, link))]
    if len(months) >= 2:
        plan.append(("Trend", lambda ws: trend_sheet(ws, data, months, rto_by_month,
                                                     charts=False)))
    row = 1
    for name, writer in plan:
        part = wb.create_sheet(name)
        writer(part)
        rows = _append(report, part, row)
        row += rows + GAP_ROWS
        wb.remove(part)

    _finish(report)                                # A4 landscape, fit to width
    report.print_title_rows = None
    report.page_margins.left = report.page_margins.right = 1.0 / 2.54
    report.page_margins.top = 1.0 / 2.54
    report.page_margins.bottom = 1.6 / 2.54
    report.oddFooter.left.text = f"Drive N Style - {data.label}"
    report.oddFooter.center.text = ""
    report.oddFooter.right.text = "Page &P of &N"
    report.oddFooter.left.size = report.oddFooter.right.size = 9
    last_row, last_col = _used(report)
    report.print_area = f"A1:{get_column_letter(last_col)}{last_row}"
    wb.calculation.fullCalcOnLoad = True
    path = Path(path)
    wb.save(path)
    return path

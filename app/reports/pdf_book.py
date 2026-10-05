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

WHAT IS IN THE PDF, in this order (the client's note of 05-10-2026, v0.13.0)
----------------------------------------------------------------------------
     1. Profit & loss                          (first page)
     2. New-car business                       five lines (needs the list)
     3. Top 10 products / top 10 services by gross profit (high-profit items)
     4. Penetration by location                (needs the delivery list)
     5. OE accessories by location, by model   (needs the delivery list)
     6. Branches by gross profit
     7. Packages vs sales
     8. Labour calculation                     by product
     9. Vehicle-wise average per car           by segment
    10. Spot incentive                         by executive + "Internal team"
    11. Payment modes                          by mode, by account
Nothing else: no headline figures, no descriptions under the headings, no
"Prepared on" line, and none of the sections left off the note (executive
summary, service vs product, indirect vs direct, new-car vs other, DNS
penetration by model, trend). All of those remain in the Excel workbook.

LAYOUT (v0.10.3)
----------------
* ONE continuous sheet: each section is first written on a sheet of its
  own (the same code as before), then copied one below the other onto a
  single "Report" sheet (formulas are shifted to their new rows). Excel
  starts a new page for every sheet, so separate sheets meant a page per
  section with most of it empty; one sheet lets the sections follow each
  other with no gaps.
* A HEADING STAYS WITH ITS TABLE (v0.19.1): when a heading and the table
  under it do not fit in what is left of a page, they start the next page
  together (see _page_breaks). Otherwise sections simply follow on; only a
  table longer than a whole page continues across pages.
* PRINT SIZE: landscape at a FIXED size worked out from the column widths
  (about 86% - 10 pt text prints at roughly 8.6 pt), not Excel's "fit to
  width": with a fixed size the tool knows exactly how many rows a page
  holds (v0.19.2, see PAGE SIZE and _page_breaks). No table is wider than eight columns and column
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
are RANKED by profit margin % (v0.11.1, the client's request: the items
shown are the highest margins, ties broken by gross profit); New-car vs
other and the Summary's Costs table run highest first too. Tables without a
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
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.worksheet import Worksheet

from app.data.payments_io import Payment
from app.reports import rto_reports as rr
from app.reports.data import (
    LABOUR_GROUPS, MonthData, labour_group, round_up_10, segment_group)
from openpyxl.styles import PatternFill

from app.reports.workbook import (
    MONEY, NAVY, PCT, Col, _by_product, _finish, _font, exec_label, pnl_sheet,
    section, table, title)

HEAD_FONT = _font(True, "FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor=NAVY)

MARGIN = '=IF({sales}{r}=0,"",{gp}{r}/{sales}{r})'
GP = "={sales}{r}-{cost}{r}-{labour}{r}"

FIRST_COL, OTHER_COL = 42, 14.5     # widest a column may be on the report sheet
GAP_ROWS = 2                        # blank rows between two sections
MARGINS_CM = dict(left=1.0, right=1.0, top=1.0, bottom=1.6)
# PAGE SIZE. The sheet asks for A4, but Excel prints on the paper of the
# PC's default printer: Brinda's PDF of 05-10-2026 came out on US Letter.
# Letter is the narrower of the two (792 points across, landscape) and A4
# the shorter (595.3 points high), so the tool allows for the worse of each:
# the columns are sized to fit Letter and the rows are counted for A4.
PAPER_WIDTH = 792.0
PAPER_HEIGHT = 595.3
PAGE_POINTS = PAPER_HEIGHT - (MARGINS_CM["top"] + MARGINS_CM["bottom"]) / 2.54 * 72
PAGE_USE = 0.985                    # a whisker short, for rounding in Excel
# Excel prints columns about 6% wider than their on-screen pixels (measured
# on that PDF: 832 points printed for 786 on screen), and the print size is
# set two points below what just fits, so nothing spills onto a second page
# across.
EXCEL_WIDER = 832 / 786
SCALE_SAFETY = 2


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
    # v0.20.0: a table for floor mats, one for sunfilm (and "Other" only if
    # needed), each with its total, then the total labour of the month.
    cols = [
        Col("Product / service", "product", width=52),
        Col("Qty", "qty", "qty", 10, total="sum"),
        Col("Labour cost", "labour", "money", 16, total="sum"),
    ]
    shown = [(g, [r for r in rows if labour_group(r["product"]) == g]) for g in LABOUR_GROUPS]
    shown = [(g, rs) for g, rs in shown if rs]
    t = {"next": row}
    if not shown:
        t = table(ws, row, cols, [], empty_text="No labour this month.")
    for g, rs in shown:
        row = section(ws, t["next"], g)
        t = table(ws, row, cols, rs)
    if shown:
        row = section(ws, t["next"], "Total labour")
        t = table(ws, row, [
            Col("", "name", width=52),
            Col("Qty", "qty", "qty", 10, total="sum"),
            Col("Labour cost", "labour", "money", 16, total="sum"),
        ], [dict(name=g, qty=sum(r["qty"] for r in rs),
                 labour=round(sum(r["labour"] for r in rs), 2)) for g, rs in shown])
    p = Page(ws, t["next"])
    p.finish()


def _vehicle(ws, d):
    row = title(ws, "Vehicle-wise average per car", d.label,
                ["Each invoice is one car. Segment comes from the Car master."])
    groups: dict[str, dict] = {}
    for i in d.invoices:
        seg = segment_group(i.segment)      # v0.20.0: counter sale / no segment = Others
        g = groups.setdefault(seg, dict(
            segment=seg, cars=0, sales=0.0, cost=0.0, labour=0.0))
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
    for g in groups.values():      # payable: rounded up to the next Rs. 10 (v0.12.1)
        g["full"], g["payable"] = round(g["full"], 2), round_up_10(g["payable"])
    ranked = sorted(groups.values(), key=lambda g: (-g["payable"], g["executive"]))
    # v0.12.0: the internal team incentive as ONE separate last line
    internal = [l for l in d.lines if l.internal_incentive and l.qty]
    if internal:
        ranked.append(dict(executive="Internal team", n=len(internal),
                           full=d.internal_incentive, payable=d.internal_incentive))
    return ranked


def _incentive(ws, d):
    row = title(ws, "Spot incentive calculation", d.label, [
        "Rule: payable = incentive × qty × (amount billed ÷ (bill value × qty)), never more "
        "than the full incentive; each executive's total is rounded up to the next Rs. 10. "
        "Highest incentive payable first. 'Internal team' (last "
        "line) = the internal incentive per item sold, paid in full."]
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
                [f"Items with a margin of {th:g}% or more this month: the 10 products and "
                 "the 10 services with the highest profit margin %."])
    good = []
    for r in _by_product(d.lines):
        r["_gp"] = round(r["sales"] - r["cost"] - r["labour"], 2)
        if r["sales"] > 0 and r["_gp"] / r["sales"] * 100 >= th - 1e-9:
            good.append(r)
    # v0.13.0 (the client's note of 05-10-2026): the ten with the highest
    # GROSS PROFIT. (v0.11.1 ranked them by margin %, which put small
    # high-margin items ahead of the real earners.)
    good.sort(key=lambda r: -r["_gp"])
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
    for category, heading in (("Product", "Top 10 products by gross profit"),
                              ("Service", "Top 10 services by gross profit")):
        rows = [r for r in good if r["category"] == category][:10]
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


def _new_car(ws, d, link):
    """New-car business: the five lines the client asked for (v0.13.0)."""
    row = title(ws, "New-car business", d.label)
    cars = len(link.cars)
    took = sum(link.took_dns(c) for c in link.cars)
    listed = round(sum(c.dns_value for c in link.cars), 2)
    for c, (text, width) in enumerate((("Particulars", 42), ("", 14.5)), start=1):
        cell = ws.cell(row, c, text)
        cell.font, cell.fill = HEAD_FONT, HEAD_FILL
        ws.column_dimensions[get_column_letter(c)].width = width
    for label, value, fmt in (
            ("Cars delivered", cars, "0"),
            ("Cars fitted with DNS accessories", took, "0"),
            ("DNS penetration %", took / cars if cars else "", PCT),
            ("DNS value as per list", listed, MONEY),
            ("DNS value per car delivered", round(listed / cars, 2) if cars else 0.0, MONEY)):
        row += 1
        ws.cell(row, 1, label).font = _font()
        cell = ws.cell(row, 2, value)
        cell.font, cell.number_format = _font(True), fmt
    _finish(ws)


def _penetration_location(ws, d, link):
    """DNS penetration by location, highest penetration % first."""
    row = title(ws, "Penetration by location", d.label)
    pen = '=IF({cars}{r}=0,"",{dns}{r}/{cars}{r})'
    per = '=IF({cars}{r}=0,"",{dns_value}{r}/{cars}{r})'
    rows = sorted(rr._group_rows(link, lambda c: c.location),
                  key=lambda g: -(g["dns"] / g["cars"] if g["cars"] else 0))
    table(ws, row, [
        Col("Location", "name", width=24),
        Col("Cars delivered", "cars", "qty", 12, total="sum"),
        Col("Took DNS", "dns", "qty", 12, total="sum"),
        Col("Penetration %", "pen", "pct", 12, formula=pen, total=pen),
        Col("DNS value (list)", "dns_value", "money", 14, total="sum"),
        Col("DNS value per car delivered", "per", "money", 14, formula=per, total=per),
        Col("Invoiced (with GST)", "invoiced", "money", 14, total="sum"),
    ], rows)
    _finish(ws)


def _oe(ws, d, link):
    """OE (car maker's) accessories by location and by model."""
    row = title(ws, "OE accessories", d.label)
    for heading, key in (("location", lambda c: c.location),
                         ("model", lambda c: c.model_group)):
        row = section(ws, row, f"By {heading} - OE accessories")
        t = table(ws, row, [
            Col(heading.capitalize(), "name", width=24),
            Col("Cars delivered", "cars", "qty", 12, total="sum"),
            Col("Took OE", "oe", "qty", 12, total="sum"),
            Col("OE value (list)", "oe_value", "money", 14, total="sum"),
            Col("OE listed, value blank", "oe_blank", "qty", 14, total="sum"),
            Col("Neither OE nor DNS", "none", "qty", 14, total="sum"),
        ], rr._group_rows(link, key))
        row = t["next"]
    _finish(ws)


def _branches(ws, d):
    """Branches ranked by gross profit (v0.13.0)."""
    row = title(ws, "Branches by gross profit", d.label)
    groups: dict[str, dict] = {}
    for i in d.invoices:
        g = groups.setdefault(i.branch or "(no branch)", dict(
            branch=i.branch or "(no branch)", invoices=0, sales=0.0, cost=0.0, labour=0.0))
        g["invoices"] += 1
        for k in ("sales", "cost", "labour"):
            g[k] = round(g[k] + getattr(i, k), 2)
    rows = sorted(groups.values(), key=lambda g: -(g["sales"] - g["cost"] - g["labour"]))
    table(ws, row, [
        Col("Branch", "branch", width=26),
        Col("Invoices", "invoices", "qty", 10, total="sum"),
        Col("Sales", "sales", "money", 15, total="sum"),
        Col("Product cost", "cost", "money", 15, total="sum"),
        Col("Labour", "labour", "money", 13, total="sum"),
        Col("Gross profit", "gp", "money", 15, formula=GP, total="sum"),
        Col("Margin %", "margin", "pct", 10, formula=MARGIN, total=MARGIN),
    ], rows)
    _finish(ws)


def _packages_vs_sales(ws, d):
    """Package sales against the month's total sales (v0.13.0)."""
    row = title(ws, "Packages vs sales", d.label)
    groups: dict[str, dict] = {}
    for i in d.invoices:
        if i.package:
            g = groups.setdefault(i.package.package, dict(name=i.package.package, n=0,
                                                          sales=0.0))
            g["n"] += 1
            g["sales"] = round(g["sales"] + i.package.sales, 2)
    packs = sorted(groups.values(), key=lambda g: -g["sales"])
    in_packs = round(sum(g["sales"] for g in packs), 2)
    rows = packs + [dict(name="Other sales (not in a package)", n="",
                         sales=round(d.sales - in_packs, 2))]
    for g in rows:
        g["share"] = g["sales"] / d.sales if d.sales else ""
    table(ws, row, [
        Col("Package", "name", width=36),
        Col("Times sold", "n", "qty", 12, total="sum"),
        Col("Sales (excl. GST)", "sales", "money", 15, total="sum"),
        Col("% of total sales", "share", "pct", 14,
            total='=IF({sales}{r}=0,"",SUM({share}{first}:{share}{last}))'),
    ], rows, total_label="Total sales of the month")
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
    # v0.13.0 (the client): no descriptions under the headings. Every
    # section starts with its heading (row 1), the month (row 2) and then
    # the small grey note lines written by title() - font size 9 - from row
    # 3. Those note rows are left out; what follows moves up to close the
    # gap (and its formulas with it).
    notes = 0
    while part.cell(3 + notes, 1).value is not None \
            and part.cell(3 + notes, 1).font.sz == 9:
        notes += 1
    for row in part.iter_rows(min_row=1, max_row=last_row, max_col=last_col):
        for cell in row:
            if 3 <= cell.row < 3 + notes:
                continue
            if cell.value is None and not cell.has_style:
                continue
            shift = at - 1 - (notes if cell.row >= 3 + notes else 0)
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
        if height and not 3 <= r < 3 + notes:
            report.row_dimensions[r + at - 1 - (notes if r >= 3 + notes else 0)].height = height
    last_row -= notes
    for c in range(1, last_col + 1):
        letter = get_column_letter(c)
        cap = FIRST_COL if c == 1 else OTHER_COL
        want = min(cap, part.column_dimensions[letter].width or 0)
        if want > (report.column_dimensions[letter].width or 0):
            report.column_dimensions[letter].width = want
    return last_row


def _blocks(report: Worksheet, first: int, last: int) -> list[tuple[int, int]]:
    """
    Split one section (rows first..last of the report sheet) into the pieces
    that must stay together on a page: a heading with the table under it.
    A new piece starts at every sub-heading ("By location - OE accessories":
    bold, size 11); the section's own heading and month stay with its first
    table.
    """
    subs = [r for r in range(first + 2, last + 1)
            if report.cell(r, 1).value is not None
            and report.cell(r, 1).font.b and report.cell(r, 1).font.sz == 11]
    # A sub-heading that comes straight after the section heading (no table
    # in between) belongs to the same piece: "OE accessories" must not be
    # left behind when "By location - OE accessories" moves to a new page.
    table_before = lambda r: any(report.cell(x, 1).fill.fgColor.rgb not in (None, "00000000")
                                 and report.cell(x, 1).fill.fill_type == "solid"
                                 for x in range(first, r))
    if subs and not table_before(subs[0]):
        subs = subs[1:]
    starts = [first] + subs
    return [(a, b - 1) for a, b in zip(starts, starts[1:] + [last + 1])]


def print_scale(report: Worksheet) -> int:
    """
    The fixed print size (per cent) at which the sheet's columns fit across
    the page - see PAGE SIZE in the module notes. The width Excel prints is
    worked out from the column widths (pixels = width x 7 + 5, at 96 to the
    inch) times EXCEL_WIDER, measured on Brinda's real PDF.
    """
    last_col = _used(report)[1]
    pixels = sum(int((report.column_dimensions[get_column_letter(c)].width or 8.43) * 7 + 5)
                 for c in range(1, last_col + 1))
    width = pixels * 0.75 * EXCEL_WIDER
    room = PAPER_WIDTH - (MARGINS_CM["left"] + MARGINS_CM["right"]) / 2.54 * 72
    return max(50, min(100, int(room / width * 100) - SCALE_SAFETY)) if width else 100


def _page_breaks(report: Worksheet, blocks: list[tuple[int, int]], scale: int) -> None:
    """
    A heading must never be left at the foot of a page with its table on
    the next one (v0.19.1). Excel cannot "keep a heading with its table", so
    the tool decides where EVERY page starts: the pieces from _blocks are
    laid on the page one after another, and when the next piece does not fit
    in what is left, a page break is put before it - heading and table move
    to the next page together.

    v0.19.2: the page height is now exact instead of a cautious guess. The
    print size is fixed (`scale`), so a page holds PAGE_POINTS / scale of
    sheet height - about 40 rows, not the 32 assumed before. (The guess made
    pages end early: "By account deposited to" went to a page of its own
    although the page before it was half empty.) A table longer than a whole
    page starts on a fresh page and is itself cut by the tool where the page
    is full, so the count never drifts from what Excel prints.
    """
    page = PAGE_POINTS / (scale / 100) * PAGE_USE
    height = lambda r: report.row_dimensions[r].height or 15.0
    used = 0.0

    def new_page(before_row: int) -> None:
        nonlocal used
        report.row_breaks.append(Break(id=before_row - 1))
        used = 0.0

    for n, (first, last) in enumerate(blocks):
        need = sum(height(r) for r in range(first, last + 1))
        if used and used + need > page:
            new_page(first)
        if need <= page:
            used += need
        else:                                    # longer than a page: cut it row by row
            for r in range(first, last + 1):
                if used and used + height(r) > page:
                    new_page(r)
                used += height(r)
        if n + 1 < len(blocks):                  # the blank rows before the next piece
            used += sum(height(r) for r in range(last + 1, blocks[n + 1][0]))


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
    with_list = link is not None
    plan = [("Profit & loss", lambda ws: pnl_sheet(ws, data, largest_first=True))]
    if with_list:
        plan.append(("New-car business", lambda ws: _new_car(ws, data, link)))
    plan.append(("High-profit products", lambda ws: _high_profit(ws, data)))
    if with_list:
        plan += [("Penetration by location",
                  lambda ws: _penetration_location(ws, data, link)),
                 ("OE accessories", lambda ws: _oe(ws, data, link))]
    plan += [("Branches", lambda ws: _branches(ws, data)),
             ("Packages vs sales", lambda ws: _packages_vs_sales(ws, data)),
             ("Labour", lambda ws: _labour(ws, data)),
             ("Vehicle-wise", lambda ws: _vehicle(ws, data)),
             ("Spot incentive", lambda ws: _incentive(ws, data)),
             ("Payment modes", lambda ws: _payments(ws, data, payments))]
    row, blocks = 1, []
    for name, writer in plan:
        part = wb.create_sheet(name)
        writer(part)
        rows = _append(report, part, row)
        blocks += _blocks(report, row, row + rows - 1)
        row += rows + GAP_ROWS
        wb.remove(part)

    _finish(report)                                # A4 landscape
    report.print_title_rows = None
    for side, cm in MARGINS_CM.items():
        setattr(report.page_margins, side, cm / 2.54)
    # A FIXED print size instead of "fit to width" (v0.19.2): only then does
    # the tool know how many rows a page holds - see _page_breaks.
    scale = print_scale(report)
    report.sheet_properties.pageSetUpPr.fitToPage = False
    report.page_setup.fitToWidth = report.page_setup.fitToHeight = None
    report.page_setup.scale = scale
    report.oddFooter.left.text = f"Drive N Style - {data.label}"
    report.oddFooter.center.text = ""
    report.oddFooter.right.text = "Page &P of &N"
    report.oddFooter.left.size = report.oddFooter.right.size = 9
    last_row, last_col = _used(report)
    report.print_area = f"A1:{get_column_letter(last_col)}{last_row}"
    _page_breaks(report, blocks, scale)
    wb.calculation.fullCalcOnLoad = True
    path = Path(path)
    wb.save(path)
    return path

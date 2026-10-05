"""
trend.py - Month-wise trend analysis (rebuilt in v0.10.0)
=========================================================

WHAT THE CLIENT ASKED FOR
-------------------------
To track progress month by month once several months are in the tool. The
old Trend sheet had only ten rows and no charts.

WHAT THE SHEET SHOWS NOW (workbook sheet "4 Trend", and a page of the PDF
when two or more months exist)
    1. Key figures - one column per month (up to the last 12 that have been
       read) and a "Total" column:
         invoices, sales, product / service sales, product cost, labour,
         gross profit and margin, indirect costs, net profit and margin,
         average bill, packages sold, spot incentive payable, and - for
         months generated with the delivery (RTO) list - cars delivered,
         cars that took DNS accessories and penetration %.
    2. Change from the previous month - sales, gross profit and net profit,
       in rupees and in percent.
    3. Sales by branch, month by month.
    4. Top 10 products by sales, month by month.
    5. Charts: sales / gross profit / net profit as lines; penetration % as
       bars when at least one month has a delivery list.

WHERE THE FIGURES COME FROM
---------------------------
Every month is worked out afresh from its invoices and the masters' rates
that applied in that month (reports/data.build_month), so a correction in a
master or on Scan review flows into the trend the next time it is
generated. Indirect costs are the month's Monthly inputs plus the automatic
% of COGS heads. The delivery-list figures cannot be recomputed (the list
is a file, not stored), so the tool keeps each month's totals when a
workbook is generated with the list (inputs_repo.save_rto_month).

"Total" adds the months up; percentages and averages in that column are
worked out again from the totals (never an average of percentages).

HOW TO BUILD UP A TREND
-----------------------
Read each month's Zoho invoice export once (Generate reports > step 2) and
enter that month's Monthly inputs. Drive N Style started in August 2026, so
the trend can start there.

Figures here are plain values (not formulas): the same sheet feeds charts
and the PDF. No Qt and no database code in this module.
"""

from __future__ import annotations

from collections import defaultdict

from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.data.invoices_repo import month_key
from app.reports.data import MonthData
from app.reports.workbook import (
    MONEY, NAVY, PCT, _finish, _font, rule, section, title)

PALETTE = ("1F5FBF", "2E9E6B", "E08A1E", "C0392B", "7D4CDB", "17A2B8",
           "D4AC0D", "8E5B3A", "5B6B82", "E0559B")
COUNT = "0"


def month_figures(m: MonthData, rto: dict | None) -> dict:
    """The key figures of one month (`rto` = saved delivery-list totals)."""
    cat = lambda c: round(sum(l.sales for l in m.lines if l.category == c), 2)
    cost = round(sum(i.cost for i in m.invoices), 2)
    labour = round(sum(i.labour for i in m.invoices), 2)
    indirect = round(sum(a for _, a in m.entered_indirect)
                     + sum(a for _, _, a in m.auto_indirect), 2)
    rto = rto or {}
    return dict(
        invoices=len(m.invoices), sales=m.sales, product=cat("Product"),
        service=cat("Service"), cost=cost, labour=labour, gp=m.gross_profit,
        indirect=indirect, net=round(m.gross_profit - indirect, 2),
        packages=sum(1 for i in m.invoices if i.package),
        incentive=m.incentive_payable,     # each executive rounded up to Rs. 10
        internal=m.internal_incentive,
        cars=rto.get("cars"), took=rto.get("took_dns"))


ROWS = (  # (label, key or function of the figures, number format, bold)
    ("Invoices", "invoices", COUNT, False),
    ("Sales (excluding GST)", "sales", MONEY, True),
    ("  Product sales", "product", MONEY, False),
    ("  Service sales", "service", MONEY, False),
    ("Product cost", "cost", MONEY, False),
    ("Labour", "labour", MONEY, False),
    ("Gross profit", "gp", MONEY, True),
    ("Gross margin %", lambda f: _ratio(f["gp"], f["sales"]), PCT, False),
    ("Indirect costs", "indirect", MONEY, False),
    ("Net profit", "net", MONEY, True),
    ("Net margin %", lambda f: _ratio(f["net"], f["sales"]), PCT, False),
    ("Average bill (sales per invoice)",
     lambda f: round(f["sales"] / f["invoices"], 2) if f["invoices"] else "", MONEY, False),
    ("Packages sold", "packages", COUNT, False),
    ("Spot incentive payable", "incentive", MONEY, False),
    ("Internal team incentive", "internal", MONEY, False),
    ("Cars delivered (delivery list)", "cars", COUNT, False),
    ("Cars fitted with DNS accessories", "took", COUNT, False),
    ("DNS penetration %", lambda f: _ratio(f["took"], f["cars"])
     if f["cars"] else "", PCT, False),
)
ADDED = ("invoices", "sales", "product", "service", "cost", "labour", "gp", "indirect",
         "net", "packages", "incentive", "internal", "cars", "took")


def _ratio(a, b):
    return a / b if a is not None and b else ""


def _total(figures: list[dict]) -> dict:
    out = {}
    for k in ADDED:
        values = [f[k] for f in figures if f[k] is not None]
        out[k] = round(sum(values), 2) if values else None
    return out


def _header(ws: Worksheet, row: int, first: str, labels: list[str]) -> None:
    for c, text in enumerate([first] + labels, start=1):
        cell = ws.cell(row, c, text)
        cell.font = _font(True, "FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="right" if c > 1 else "left")
        ws.column_dimensions[get_column_letter(c)].width = 36 if c == 1 else 15


def _put(ws: Worksheet, row: int, label: str, values: list, fmt: str,
         bold: bool = False) -> None:
    ws.cell(row, 1, label).font = _font(bold)
    for c, v in enumerate(values, start=2):
        cell = ws.cell(row, c, "" if v is None else v)
        cell.font, cell.number_format = _font(bold), fmt
        cell.alignment = Alignment(horizontal="right")
        if bold:
            cell.border = Border(top=rule)


def _colour(chart) -> None:
    for i, s in enumerate(chart.series):
        colour = PALETTE[i % len(PALETTE)]
        s.graphicalProperties.solidFill = colour
        s.graphicalProperties.line.solidFill = colour
        if isinstance(chart, LineChart):
            s.graphicalProperties.line.width = 28000
            s.marker.symbol = "circle"
            s.marker.graphicalProperties.solidFill = colour
            s.smooth = False


def trend_sheet(ws: Worksheet, d: MonthData, months: list[MonthData],
                rto_by_month: dict[str, dict] | None = None, charts: bool = True) -> None:
    """`charts=False` (v0.10.3): the PDF version carries no graphs."""
    rto_by_month = rto_by_month or {}
    labels = [m.label[:3] + " " + str(m.year) for m in months]
    figures = [month_figures(m, rto_by_month.get(month_key(m.year, m.month)))
               for m in months]
    n = len(months)
    row = title(ws, "Trend analysis (month on month)", d.label, [
        "Months that have been read into the tool, up to the last 12; each uses the masters' "
        "rates that applied in that month. 'Total' adds the months; its percentages and "
        "averages are worked out from the totals.",
        "Delivery-list rows are filled for months whose workbook was generated with the "
        "delivery (RTO) list."
        + ("" if n > 1 else " Only one month has been read so far: read earlier months' "
                            "invoice exports to see the trend.")])

    # --- 1. key figures -------------------------------------------------------
    row = section(ws, row, "Key figures")
    _header(ws, row, "Particulars", labels + ["Total"])
    head = row
    position = {}
    for label, key, fmt, bold in ROWS:
        row += 1
        get = (lambda f, k=key: f[k]) if isinstance(key, str) else key
        _put(ws, row, label, [get(f) for f in figures] + [get(_total(figures))], fmt, bold)
        position[label] = row

    # --- 2. change from the previous month ---------------------------------------
    row = section(ws, row + 3, "Change from the previous month")
    _header(ws, row, "Particulars", labels)
    for label, key in (("Sales", "sales"), ("Gross profit", "gp"), ("Net profit", "net")):
        diffs = [None] + [round(figures[i][key] - figures[i - 1][key], 2)
                          for i in range(1, n)]
        pcts = [None] + [_ratio(figures[i][key] - figures[i - 1][key],
                                abs(figures[i - 1][key])) for i in range(1, n)]
        row += 1
        _put(ws, row, f"{label} - change (₹)", diffs, MONEY)
        row += 1
        _put(ws, row, f"{label} - change %", pcts, PCT)

    # --- 3. sales by branch / 4. top products ---------------------------------------
    def by_month(title_text: str, first: str, key, limit: int | None) -> int:
        nonlocal row
        groups: dict[str, list[float]] = defaultdict(lambda: [0.0] * n)
        for j, m in enumerate(months):
            for name, sales in key(m):
                groups[name][j] += sales
        ranked = sorted(groups.items(), key=lambda g: -sum(g[1]))[:limit]
        row = section(ws, row + 3, title_text)
        _header(ws, row, first, labels + ["Total"])
        for name, values in ranked:
            row += 1
            values = [round(v, 2) for v in values]
            _put(ws, row, name, values + [round(sum(values), 2)], MONEY)
        return row

    by_month("Sales by branch", "Branch",
             lambda m: [(i.branch or "(no branch)", i.sales) for i in m.invoices], None)
    by_month("Top 10 products by sales", "Product / service",
             lambda m: [(l.product, l.sales) for l in m.lines], 10)

    # --- 5. charts ---------------------------------------------------------------
    if not charts:
        _finish(ws, "B%d" % (head + 1))
        return
    row += 3
    cats = Reference(ws, min_col=2, max_col=n + 1, min_row=head)
    line = LineChart()
    line.title = "Sales, gross profit and net profit"
    line.height, line.width = 8.5, 24
    line.y_axis.number_format = "#,##0"
    line.y_axis.delete = line.x_axis.delete = False
    for label in ("Sales (excluding GST)", "Gross profit", "Net profit"):
        r = position[label]
        line.add_data(Reference(ws, min_col=1, max_col=n + 1, min_row=r),
                      from_rows=True, titles_from_data=True)
    line.set_categories(cats)
    _colour(line)
    ws.add_chart(line, f"A{row}")
    row += 19
    if any(f["cars"] for f in figures):
        bar = BarChart()
        bar.title = "DNS penetration % of cars delivered"
        bar.height, bar.width = 7.5, 24
        bar.y_axis.number_format = "0%"
        bar.y_axis.delete = bar.x_axis.delete = False
        bar.legend = None
        r = position["DNS penetration %"]
        bar.add_data(Reference(ws, min_col=1, max_col=n + 1, min_row=r),
                     from_rows=True, titles_from_data=True)
        bar.set_categories(cats)
        _colour(bar)
        ws.add_chart(bar, f"A{row}")
    _finish(ws, "B%d" % (head + 1))

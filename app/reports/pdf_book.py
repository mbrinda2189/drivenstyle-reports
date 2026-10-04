"""
pdf_book.py - The "PDF version" of the reports (v0.10.0)
========================================================

WHY A SEPARATE VERSION
----------------------
The Excel workbook is the working paper: every invoice, every line, every
formula. The PDF is what the owner reads. Brinda asked (04-10-2026) for the
PDF to carry only the summary tables, with colourful graphs, while the
Excel workbook stays exactly as it is.

So the tool writes a second, temporary workbook laid out for reading -
this module - and Excel turns THAT into the PDF (pdf_export.py). The
temporary workbook is deleted afterwards.

WHAT IS IN THE PDF (one sheet = one section, in this order)
-----------------------------------------------------------
    Cover
    Summary              executive summary WITHOUT "Points needing attention"
    Service vs product   summary table only                    + pie
    Labour               "By product" table only               + bars
    Vehicle-wise         "By segment" table only               + bars
    Spot incentive       "By executive" only, highest first    + bars
    High-profit          top 10 products and top 10 services   + bars
    Indirect vs direct   as in the workbook                    + pie
    Payment modes        by mode, by account deposited to      + pie
    Profit & loss        as in the workbook                    + bars
    New-car penetration  as in the workbook (needs the list)   + bars
    New-car vs other     "Where the month's business came from" + pie
    Trend                only when two or more months are read (trend.py)
NOT in the PDF: invoice profitability, packages, executive-wise sales,
missed opportunity, RTO list vs invoices, consultant scorecard, not
included. They remain in the Excel workbook.

HOW THE GRAPHS ARE MADE
-----------------------
ONE SECTION = ONE PAGE: every sheet is printed upright (portrait) and
scaled to fit a single page, so a table and its graphs are never cut across
pages. (The Trend page turns sideways once it has more than five months.)

They are ordinary Excel charts, so Excel draws them into the PDF. Each
chart reads a small block of figures written far to the right of the page
(column AA onwards), outside the print area, so the page shows only the
table and the graph. The figures for tables and charts are worked out here
in Python from the same MonthData as the workbook.

No Qt and no database code here.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.data.payments_io import Payment
from app.reports import rto_reports as rr
from app.reports.data import MonthData
from app.reports.trend import PALETTE, trend_sheet
from app.reports.workbook import (
    Col, _by_product, _finish, cost_split_sheet, cover_sheet, exec_label, pnl_sheet,
    section, table, title)

DATA_COL = 27               # column AA: chart figures, outside the print area
CHART_CM = (22.0, 8.5)      # width, height
CHART_ROWS = 19             # sheet rows a chart of that height covers
MARGIN = '=IF({sales}{r}=0,"",{gp}{r}/{sales}{r})'
GP = "={sales}{r}-{cost}{r}-{labour}{r}"


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
class Page:
    """A sheet being laid out: tracks the next free row and chart data."""

    def __init__(self, ws: Worksheet, row: int):
        self.ws, self.row, self._data_row = ws, row, 1

    def _block(self, heads: list[str], rows: list[tuple]) -> tuple[int, int]:
        """Write chart figures at column AA; returns (heading row, last row)."""
        top = self._data_row
        for c, h in enumerate(heads):
            self.ws.cell(top, DATA_COL + c, h)
        for r, values in enumerate(rows, start=top + 1):
            for c, v in enumerate(values):
                self.ws.cell(r, DATA_COL + c, v)
        self._data_row = top + len(rows) + 2
        return top, top + len(rows)

    def _place(self, chart) -> None:
        chart.width, chart.height = CHART_CM
        self.ws.add_chart(chart, f"A{self.row}")
        self.row += CHART_ROWS

    def bars(self, heading: str, labels: list[str], series: dict[str, list[float]],
             number_format: str = "#,##0", horizontal: bool = False) -> None:
        """A bar chart: one colour per series, or per bar when there is one series."""
        if not labels:
            return
        names = list(series)
        top, last = self._block(["", *names],
                                [(l, *[series[n][i] for n in names])
                                 for i, l in enumerate(labels)])
        chart = BarChart()
        chart.type = "bar" if horizontal else "col"
        if horizontal:                 # first row at the top, like the table
            chart.x_axis.scaling.orientation = "maxMin"
        chart.title = heading
        chart.y_axis.number_format = number_format
        chart.y_axis.delete = chart.x_axis.delete = False
        chart.add_data(Reference(self.ws, min_col=DATA_COL + 1, max_col=DATA_COL + len(names),
                                 min_row=top, max_row=last), titles_from_data=True)
        chart.set_categories(Reference(self.ws, min_col=DATA_COL, min_row=top + 1,
                                       max_row=last))
        for i, s in enumerate(chart.series):
            s.graphicalProperties.solidFill = PALETTE[i % len(PALETTE)]
        if len(names) == 1:
            chart.legend = None
            for i in range(len(labels)):          # every bar its own colour
                point = DataPoint(idx=i)
                point.graphicalProperties.solidFill = PALETTE[i % len(PALETTE)]
                chart.series[0].dPt.append(point)
        self._place(chart)

    def pie(self, heading: str, labels: list[str], values: list[float]) -> None:
        pairs = [(l, v) for l, v in zip(labels, values) if v and v > 0]
        if not pairs:
            return
        top, last = self._block(["", heading], pairs)
        chart = PieChart()
        chart.title = heading
        chart.add_data(Reference(self.ws, min_col=DATA_COL + 1, min_row=top, max_row=last),
                       titles_from_data=True)
        chart.set_categories(Reference(self.ws, min_col=DATA_COL, min_row=top + 1,
                                       max_row=last))
        for i in range(len(pairs)):
            point = DataPoint(idx=i)
            point.graphicalProperties.solidFill = PALETTE[i % len(PALETTE)]
            chart.series[0].dPt.append(point)
        chart.dataLabels = DataLabelList()
        chart.dataLabels.showPercent = True
        chart.dataLabels.showVal = False
        chart.dataLabels.showSerName = chart.dataLabels.showCatName = False
        chart.dataLabels.showLeaderLines = False
        self._place(chart)

    def finish(self) -> None:
        """Page set-up, and a print area that leaves the chart figures out."""
        ws = self.ws
        _finish(ws)
        used = max((c.column for r in ws.iter_rows(max_col=DATA_COL - 1) for c in r
                    if c.value is not None), default=1)
        width_cm, col = 0.0, 0
        while (col < used or width_cm < CHART_CM[0] + 0.5) and col < DATA_COL - 2:
            col += 1                              # ~0.2 cm per character of width
            width_cm += (ws.column_dimensions[get_column_letter(col)].width or 8.43) * 0.2
        bottom = max(self.row, max((c.row for r in ws.iter_rows(max_col=DATA_COL - 1)
                                    for c in r if c.value is not None), default=1))
        ws.print_area = f"A1:{get_column_letter(col)}{bottom}"
        one_page(ws)


def one_page(ws: Worksheet, landscape: bool = False) -> None:
    """Scale the sheet to exactly one page, so graphs are not cut in two."""
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = None


def _bottom(ws: Worksheet) -> int:
    return max((c.row for r in ws.iter_rows(max_col=DATA_COL - 1) for c in r
                if c.value is not None), default=1) + 3


# ---------------------------------------------------------------------------
# The sheets
# ---------------------------------------------------------------------------
def _summary(ws, d, previous, link, user):
    rr.summary_sheet(ws, d, previous, link, user, attention=False)
    p = Page(ws, _bottom(ws))
    indirect = round(sum(a for _, a in d.entered_indirect)
                     + sum(a for _, _, a in d.auto_indirect), 2)
    p.bars("Sales, costs and profit", ["Sales", "Direct costs", "Gross profit",
                                       "Indirect costs", "Net profit"],
           {d.label: [d.sales, d.cogs, d.gross_profit, indirect,
                      round(d.gross_profit - indirect, 2)]})
    p.finish()


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
    p.pie("Share of sales", [g["category"] for g in rows], [g["sales"] for g in rows])
    p.bars("Sales and gross profit", [g["category"] for g in rows],
           {"Sales": [g["sales"] for g in rows],
            "Gross profit": [round(g["sales"] - g["cost"] - g["labour"], 2) for g in rows]})
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
    p.bars("Labour cost by product (top 12)", [g["product"][:38] for g in rows[:12]],
           {"Labour cost": [g["labour"] for g in rows[:12]]}, horizontal=True)
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
    p.bars("Sales and gross profit by segment", [g["segment"] for g in rows],
           {"Sales": [g["sales"] for g in rows],
            "Gross profit": [round(g["sales"] - g["cost"] - g["labour"], 2) for g in rows]})
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
        "than the full incentive. Highest incentive payable first."])
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
    p.bars("Incentive payable (top 15)", [g["executive"][:30] for g in rows[:15]],
           {"Incentive payable": [g["payable"] for g in rows[:15]]}, horizontal=True)
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
        rows = [r for r in good if r["category"] == category][:10]
        r0 = section(ws, p.row, heading)
        t = table(ws, r0, cols("Product" if category == "Product" else "Service"), rows,
                  empty_text=f"No {category.lower()} reached a {th:g}% margin this month.")
        p.row = t["next"]
        p.bars(f"{heading} - gross profit", [r["product"][:38] for r in rows],
               {"Gross profit": [r["_gp"] for r in rows]}, horizontal=True)
        p.row += 1
    p.finish()


def _costs(ws, d):
    cost_split_sheet(ws, d)
    p = Page(ws, _bottom(ws))
    cost = round(sum(i.cost for i in d.invoices), 2)
    labour = round(sum(i.labour for i in d.invoices), 2)
    indirect = round(sum(a for _, a in d.entered_indirect)
                     + sum(a for _, _, a in d.auto_indirect), 2)
    p.pie("Where the costs go", ["Product cost", "Labour", "Indirect costs"],
          [cost, labour, indirect])
    p.finish()


def _pnl(ws, d):
    pnl_sheet(ws, d)
    p = Page(ws, _bottom(ws))
    heads = sorted(list(d.entered_indirect) + [(h, a) for h, _, a in d.auto_indirect],
                   key=lambda x: -x[1])
    heads = [(h, a) for h, a in heads if a > 0][:12]
    p.bars("Indirect costs by head", [h[:30] for h, _ in heads],
           {"Amount": [a for _, a in heads]}, horizontal=True)
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
    p.pie("Collections by mode", [r["mode"] for r in rows], [r["amount"] for r in rows])
    if accounts:
        p.pie("By account deposited to", list(sorted(accounts)),
              [round(accounts[a], 2) for a in sorted(accounts)])
    p.finish()


def _penetration(ws, d, link):
    rr.penetration_sheet(ws, d, link)
    p = Page(ws, _bottom(ws))
    by_loc = rr._group_rows(link, lambda c: c.location)
    p.bars("DNS penetration % by location", [g["name"] for g in by_loc],
           {"Penetration %": [g["dns"] / g["cars"] if g["cars"] else 0 for g in by_loc]},
           number_format="0%")
    p.bars("Cars delivered and cars that took DNS", [g["name"] for g in by_loc],
           {"Cars delivered": [g["cars"] for g in by_loc],
            "Took DNS": [g["dns"] for g in by_loc]})
    p.finish()


def _source(ws, d, link):
    row = title(ws, "New-car vs other business", d.label, [
        "New-car business = invoices linked to a car in this month's delivery list. Other = "
        "every other invoice (walk-in, earlier deliveries, counter sales).",
        "Sales exclude GST. Gross profit = sales - product cost - labour."])
    row = section(ws, row, "Where the month's business came from")
    rows = [rr._business("New cars delivered this month", link.linked),
            rr._business("Other business", link.other)]
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
    p.pie("Share of sales", [r["name"] for r in rows], [r["sales"] for r in rows])
    p.bars("Sales and gross profit", [r["name"] for r in rows],
           {"Sales": [r["sales"] for r in rows],
            "Gross profit": [round(r["sales"] - r["cost"] - r["labour"], 2) for r in rows]})
    p.finish()


# ---------------------------------------------------------------------------
# The workbook
# ---------------------------------------------------------------------------
def write_pdf_workbook(data: MonthData, months: list[MonthData],
                       payments: list[Payment] | None, path: str | Path,
                       user: str = "", rto: list | None = None,
                       previous: MonthData | None = None,
                       rto_by_month: dict | None = None) -> Path:
    """Write the temporary workbook that Excel turns into the PDF."""
    link = rr.Linked(data, rto) if rto is not None else None
    wb = Workbook()
    cover = wb.active
    cover.title = "Cover"
    plan = [("Summary", lambda ws: _summary(ws, data, previous, link, user)),
            ("Service vs product", lambda ws: _category(ws, data)),
            ("Labour", lambda ws: _labour(ws, data)),
            ("Vehicle-wise", lambda ws: _vehicle(ws, data)),
            ("Spot incentive", lambda ws: _incentive(ws, data)),
            ("High-profit products", lambda ws: _high_profit(ws, data)),
            ("Indirect vs direct", lambda ws: _costs(ws, data)),
            ("Payment modes", lambda ws: _payments(ws, data, payments)),
            ("Profit & loss", lambda ws: _pnl(ws, data))]
    if link is not None:
        plan += [("New-car penetration", lambda ws: _penetration(ws, data, link)),
                 ("New-car vs other", lambda ws: _source(ws, data, link))]
    if len(months) >= 2:
        plan.append(("Trend", lambda ws: (trend_sheet(ws, data, months, rto_by_month),
                                          one_page(ws, landscape=len(months) > 5))))
    for name, writer in plan:
        writer(wb.create_sheet(name))
    cover_sheet(cover, data, [name for name, _ in plan], user, pdf=True)
    one_page(cover)
    wb.calculation.fullCalcOnLoad = True
    path = Path(path)
    wb.save(path)
    return path

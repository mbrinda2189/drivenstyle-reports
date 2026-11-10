"""
cogs_check.py - "18 COGS check": product cost, master sheet vs Zoho (v0.33.0)
============================================================================

WHAT THIS SHEET IS FOR
----------------------
The client (via Brinda, 10-11-2026): "Invoice level - Sale - COGS - item
difference compared to master sheet. Zoho uses FIFO inventory costing, so
have to check its costing - what costing is it taking for each item,
compared to the master sheet."

The tool's product cost is the Product master cost price x qty at the rate
of the invoice date (the "master sheet"). Zoho's is what its FIFO stock
lots say. This sheet puts the two side by side; it CHANGES NOTHING - the
P&L and every other sheet keep the master cost (Brinda's default,
10-11-2026). Under the P&L a short "Product cost - tool vs Zoho" block
points here.

It is written when either Zoho report is uploaded on Generate
(app/data/zoho_costs.py):
    COGS   = Account Transactions of the Cost of Goods Sold account - what
             Zoho POSTED per invoice; adds up to Zoho's P&L figure
    FIFO   = FIFO Cost Lot Tracking - which lot (bill) and cost per unit
             Zoho used for each item of each invoice

SECTIONS
--------
    A. Zoho's cost of goods sold for the month         (needs COGS)
       invoices in these reports + invoices left out / not in the export
       + bills and vendor credits booked to COGS = Zoho's P&L figure
    B. Master vs Zoho - summary                       invoices that agree
       (within Rs. 1), where Zoho is higher, lower, or posted no COGS
    C. Invoice by invoice                             sales, master cost,
       Zoho cost, difference, margin % both ways - biggest difference first
    D. Item by item                                    (needs FIFO)
       Zoho's FIFO cost per unit against the master cost per unit; qty
       sold with no stock; items Zoho does not track as stock
    E. Sold with no stock in Zoho (costed at 0)       (needs FIFO)

"Zoho cost" of an invoice is the COGS Zoho posted (the COGS file); with only
the FIFO file it is the FIFO cost of the invoice's lines instead - the
heading says which. Difference = Zoho - master: plus means Zoho's cost is
higher (Zoho's profit lower).

Only the invoices IN these reports are compared (open Scan review issues
leave an invoice out, as everywhere); section A still shows the rest so the
total agrees with Zoho.

No database and no Qt code here.
"""

from __future__ import annotations

from collections import defaultdict

from openpyxl.worksheet.worksheet import Worksheet

from app.data.zoho_costs import ZohoCosts, invoice_key
from app.reports.data import MonthData
from app.reports.workbook import Col, SLATE, _finish, _font, section, table, title

SHEET = "18 COGS check"
AGREE = 1.0                         # rupees
NOT_TRACKED = "Not tracked as stock in Zoho (no FIFO lot)"


def _item_key(name: str) -> str:
    return " ".join(str(name or "").lower().split())


# ---------------------------------------------------------------------------
# The figures (also used by the P&L block and the PDF)
# ---------------------------------------------------------------------------
class Comparison:
    """Master cost vs Zoho, invoice by invoice and item by item."""

    def __init__(self, d: MonthData, z: ZohoCosts):
        self.d, self.z = d, z
        self.posted = z.cogs.by_invoice() if z.cogs else None
        fifo_by: dict[str, list] = defaultdict(list)
        for f in z.fifo or []:
            fifo_by[invoice_key(f.invoice_no)].append(f)
        self.fifo_by = fifo_by
        self.included = {invoice_key(i.invoice_no) for i in d.invoices}
        self.zoho_label = "Zoho COGS (posted)" if self.posted is not None else "Zoho FIFO cost"

    def zoho_cost(self, invoice_no: str) -> float:
        key = invoice_key(invoice_no)
        if self.posted is not None:
            return self.posted.get(key, 0.0)
        return round(sum(f.cost for f in self.fifo_by.get(key, [])), 2)

    def invoice_rows(self) -> list[dict]:
        rows = []
        for i in self.d.invoices:
            key = invoice_key(i.invoice_no)
            zoho = self.zoho_cost(i.invoice_no)
            fifo = self.fifo_by.get(key, [])
            if self.posted is not None and key not in self.posted:
                result = "No COGS posted in Zoho"
            elif abs(zoho - i.cost) <= AGREE:
                result = "Agrees"
            else:
                result = "Zoho higher" if zoho > i.cost else "Zoho lower"
            if not i.cost and not zoho:
                continue                      # nothing costed either way (services)
            rows.append(dict(
                invoice=i.invoice_no, date=i.invoice_date, customer=i.customer,
                sales=i.sales, master=i.cost, zoho=zoho,
                fifo=round(sum(f.cost for f in fifo), 2),
                no_stock=sum(1 for f in fifo if f.no_stock), result=result))
        return sorted(rows, key=lambda r: (-abs(r["zoho"] - r["master"]), r["invoice"]))

    def summary_rows(self, rows: list[dict] | None = None) -> list[dict]:
        order = ("Agrees", "Zoho higher", "Zoho lower", "No COGS posted in Zoho")
        out = {k: dict(result=k, invoices=0, master=0.0, zoho=0.0) for k in order}
        for r in rows if rows is not None else self.invoice_rows():
            g = out[r["result"]]
            g["invoices"] += 1
            g["master"] = round(g["master"] + r["master"], 2)
            g["zoho"] = round(g["zoho"] + r["zoho"], 2)
        return [g for g in out.values() if g["invoices"]]

    def totals(self) -> tuple[float, float]:
        """(master, Zoho) product cost of the invoices in these reports."""
        master = round(sum(i.cost for i in self.d.invoices), 2)
        return master, round(sum(self.zoho_cost(i.invoice_no) for i in self.d.invoices), 2)

    def month_rows(self) -> list[dict]:
        """Section A: how Zoho's P&L COGS is made up."""
        c = self.z.cogs
        posted = self.posted or {}
        left = {invoice_key(x.invoice_no) for x in self.d.left_out}
        groups = {"in": [0, 0.0], "left": [0, 0.0], "other": [0, 0.0]}
        for key, amount in posted.items():
            g = groups["in" if key in self.included else "left" if key in left else "other"]
            g[0] += 1
            g[1] = round(g[1] + amount, 2)
        rows = [dict(what="Invoices in these reports", n=groups["in"][0], amount=groups["in"][1])]
        if groups["left"][0]:
            rows.append(dict(what="Invoices left out of these reports (open issues)",
                             n=groups["left"][0], amount=groups["left"][1]))
        if groups["other"][0]:
            rows.append(dict(what="Invoices not in this month's invoice export",
                             n=groups["other"][0], amount=groups["other"][1]))
        rows += [dict(what=w, n=n, amount=a) for w, n, a in c.other_kinds()]
        return rows

    def item_rows(self) -> list[dict]:
        """Section D: per item, FIFO cost per unit vs master cost per unit."""
        items: dict[str, dict] = {}
        for l in self.d.lines:
            if not l.qty:
                continue
            g = items.setdefault(_item_key(l.product), dict(
                item=l.product, qty=0.0, master_cost=0.0, lot_qty=0.0, lot_cost=0.0,
                no_stock=0.0, in_fifo=False))
            g["qty"] = round(g["qty"] + l.qty, 2)
            g["master_cost"] = round(g["master_cost"] + l.cost, 2)
        for key, outs in self.fifo_by.items():
            if key not in self.included:
                continue
            for f in outs:
                g = items.setdefault(_item_key(f.item), dict(
                    item=f.item, qty=0.0, master_cost=0.0, lot_qty=0.0, lot_cost=0.0,
                    no_stock=0.0, in_fifo=False))
                g["in_fifo"] = True
                if f.no_stock:
                    g["no_stock"] = round(g["no_stock"] + f.qty, 2)
                else:
                    g["lot_qty"] = round(g["lot_qty"] + f.qty, 2)
                    g["lot_cost"] = round(g["lot_cost"] + f.cost, 2)
        rows = []
        for g in items.values():
            if not g["master_cost"] and not g["in_fifo"]:
                continue                        # services with no cost either way
            master_unit = round(g["master_cost"] / g["qty"], 2) if g["qty"] else ""
            zoho_unit = round(g["lot_cost"] / g["lot_qty"], 2) if g["lot_qty"] else ""
            note = ""
            if not g["in_fifo"]:
                note = NOT_TRACKED
            elif not g["qty"]:
                note = "In Zoho's FIFO report, not on this month's invoices in the tool"
            elif g["no_stock"] and not g["lot_qty"]:
                note = "Every unit sold with no stock in Zoho"
            rows.append(dict(g, master_unit=master_unit, zoho_unit=zoho_unit, note=note,
                             gap=(g["lot_qty"] * (zoho_unit - master_unit)
                                  if g["lot_qty"] and master_unit != "" else 0.0)))
        # largest difference on the costed qty first; not-tracked items after
        return sorted(rows, key=lambda r: (r["note"] == NOT_TRACKED, -abs(r["gap"]),
                                           -r["master_cost"], r["item"]))

    def no_stock_rows(self) -> list[dict]:
        unit = {_item_key(r["item"]): r["master_unit"] for r in self.item_rows()}
        rows = []
        for key, outs in self.fifo_by.items():
            if key not in self.included:
                continue
            for f in outs:
                if f.no_stock:
                    u = unit.get(_item_key(f.item))
                    rows.append(dict(invoice=f.invoice_no, date=f.sold_on, item=f.item,
                                     qty=f.qty, master=round(f.qty * u, 2) if u else 0.0))
        return sorted(rows, key=lambda r: (-r["master"], r["invoice"]))


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------
def invoice_cols(c: Comparison, short: bool = False) -> list[Col]:
    margin = '=IF({sales}{r}=0,"",({sales}{r}-{%s}{r})/{sales}{r})'
    cols = [
        Col("Invoice no", "invoice", width=18),
        *([] if short else [Col("Date", "date", "date", 11)]),
        Col("Customer", "customer", width=26),
        Col("Sales", "sales", "money", 13, total="sum"),
        Col("Master cost (tool)", "master", "money", 13, total="sum"),
        Col(c.zoho_label, "zoho", "money", 13, total="sum"),
        Col("Difference (Zoho - master)", "diff", "money", 13,
            formula="={zoho}{r}-{master}{r}", total="sum"),
    ]
    if short:
        return cols
    cols += [
        Col("Margin % - master", "m1", "pct", 10, formula=margin % "master",
            total=margin % "master"),
        Col("Margin % - Zoho", "m2", "pct", 10, formula=margin % "zoho",
            total=margin % "zoho"),
    ]
    if c.posted is not None and c.z.fifo is not None:
        cols.append(Col("Zoho FIFO cost of the lines", "fifo", "money", 13, total="sum"))
    if c.z.fifo is not None:
        cols.append(Col("Lines sold with no stock", "no_stock", "qty", 9, total="sum"))
    cols.append(Col("Result", "result", width=22))
    return cols


def summary_cols(c: Comparison) -> list[Col]:
    return [
        Col("Result", "result", width=30),
        Col("Invoices", "invoices", "qty", 10, total="sum"),
        Col("Master cost (tool)", "master", "money", 15, total="sum"),
        Col(c.zoho_label, "zoho", "money", 15, total="sum"),
        Col("Difference (Zoho - master)", "diff", "money", 15,
            formula="={zoho}{r}-{master}{r}", total="sum"),
    ]


def cogs_sheet(ws: Worksheet, d: MonthData, z: ZohoCosts) -> None:
    c = Comparison(d, z)
    files = " and ".join(f"{k} ({v})" for k, v in z.names.items())
    row = title(ws, "COGS check - master sheet vs Zoho", d.label, [
        "The tool's product cost = Product master cost price x qty (the master sheet). "
        "Zoho's = its FIFO stock lots. Nothing here changes the P&L or any other sheet.",
        "Difference = Zoho - master: plus means Zoho's cost is higher. Only invoices in these "
        "reports are compared (open Scan review issues are left out, as everywhere).",
        *([f"Zoho files: {files}."] if files else [])])

    if z.cogs is not None:
        row = section(ws, row, "A. Zoho's cost of goods sold for the month"
                      + (f" ({z.cogs.period})" if z.cogs.period else ""))
        t = table(ws, row, [
            Col("Made up of", "what", width=46),
            Col("Entries", "n", "qty", 10, total="sum"),
            Col("Amount", "amount", "money", 15, total="sum"),
        ], c.month_rows(), total_label="Total = Zoho's P&L cost of goods sold")
        row = t["next"]

    rows = c.invoice_rows()
    row = section(ws, row, "B. Master vs Zoho - summary")
    t = table(ws, row, summary_cols(c), c.summary_rows(rows))
    row = section(ws, t["next"], "C. Invoice by invoice - biggest difference first")
    t = table(ws, row, invoice_cols(c), rows, filters=True,
              empty_text="No invoice with a product cost this month.")
    row = t["next"]

    if z.fifo is not None:
        row = section(ws, row, "D. Item by item - Zoho's FIFO cost per unit vs the master")
        ws.cell(row, 1, "Zoho cost per unit = the lots Zoho used for this month's invoices. "
                        "Items sold with no stock are costed at 0 by Zoho and are not in "
                        "that average. Export the FIFO report from the start of the business "
                        "to today - it is filtered by the bill date.").font = _font(color=SLATE, size=9)
        t = table(ws, row + 1, [
            Col("Item", "item", width=46),
            Col("Qty sold", "qty", "qty", 9, total="sum"),
            Col("Qty costed from a lot", "lot_qty", "qty", 10, total="sum"),
            Col("Zoho cost per unit", "zoho_unit", "money", 12),
            Col("Master cost per unit", "master_unit", "money", 12),
            Col("Difference per unit", "unit_diff", "money", 12,
                formula='=IF(OR({zoho_unit}{r}="",{master_unit}{r}=""),"",'
                        '{zoho_unit}{r}-{master_unit}{r})'),
            Col("Difference on qty costed", "gap", "money", 13,
                formula='=IF({unit_diff}{r}="",0,{unit_diff}{r}*{lot_qty}{r})', total="sum"),
            Col("Qty sold with no stock", "no_stock", "qty", 10, total="sum"),
            Col("Note", "note", width=40),
        ], c.item_rows(), filters=True)
        row = section(ws, t["next"], "E. Sold with no stock in Zoho (costed at 0)")
        table(ws, row, [
            Col("Invoice no", "invoice", width=18),
            Col("Date", "date", "date", 11),
            Col("Item", "item", width=46),
            Col("Qty", "qty", "qty", 8, total="sum"),
            Col("Master cost of these units", "master", "money", 14, total="sum"),
        ], c.no_stock_rows(), filters=False,
            empty_text="Every unit sold this month was costed from a stock lot.")
    _finish(ws)


def pnl_block(ws: Worksheet, d: MonthData, z: ZohoCosts, row: int) -> int:
    """Under the Profit & loss: the P&L's product cost beside Zoho's. Returns
    the next free row."""
    c = Comparison(d, z)
    master, zoho = c.totals()
    row = section(ws, row, "Product cost - tool vs Zoho (details: sheet 18 COGS check)")
    rows = [dict(what="Product cost of this report's invoices", tool=master, books=zoho)]
    t = table(ws, row, [
        Col("Product cost", "what", width=38),
        Col("Tool (used in P&L)", "tool", "money", 16),
        Col("As per Zoho", "books", "money", 16),
        Col("Difference", "diff", "money", 14, formula="={tool}{r}-{books}{r}"),
    ], rows)
    row = t["next"] - 2
    if z.cogs is not None:
        ws.cell(row, 1, "Zoho's P&L cost of goods sold (all postings)").font = _font()
        cell = ws.cell(row, 3, z.cogs.total)
        cell.number_format = "#,##0.00"
        cell.font = _font()
        row += 1
    return row + 2

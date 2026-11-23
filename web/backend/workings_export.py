"""
workings_export.py - "Show working" as Excel and PDF (v0.37.0)
==============================================================

WHAT THIS MODULE DOES
---------------------
Builds the downloadable copies of the working of the daily payouts, for
the staff member who checks the amounts by hand (Brinda, 23-11-2026):

    invoice_workbook(view)    ONE invoice, one sheet laid out like the
                              screen: what was read, every item, labour
                              by kind, the spot incentive step by step,
                              internal team, the payout lines and who
                              calculated / checked it. Landscape, fitted
                              to the page width - normally one page.
    invoice_pdf(view)         the same sheet as a PDF (LibreOffice on the
                              server, Excel on a Windows PC -
                              app/reports/pdf_export.py).
    range_workbook(entries)   MANY invoices (a day or a date range), for
                              checking with her own formulas:
                                Invoices  one row per invoice, every input
                                          in its own column, and CHECK
                                          columns that are Excel formulas
                                          (labour total, share earned,
                                          incentive) beside the tool's
                                          amount and the difference
                                Items     one row per item line, with
                                          rate x qty as formulas
                                Read me   what each column means

It reads only what `PayoutStore.working()` gives (the STORED working the
amounts came from) - it calculates nothing itself, except the check
formulas Excel works out in the Items / Invoices sheets.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.reports.pdf_export import export_pdf

MONEY = "#,##0.00"
QTY = "#,##0.##"
BLUE = "1F5FBF"
HEAD_FILL = PatternFill("solid", fgColor="DCE6F5")
TOTAL_FILL = PatternFill("solid", fgColor="F1F5FB")
THIN = Side(style="thin", color="B8C4D6")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14, color=BLUE)
SECTION = Font(bold=True, size=12, color=BLUE)


def _day(iso: str) -> str:
    """"2026-10-09" -> "09-10-2026" (the tool's date style)."""
    return f"{iso[8:10]}-{iso[5:7]}-{iso[0:4]}" if iso and len(iso) >= 10 else (iso or "")


# ---------------------------------------------------------------------------
# One invoice
# ---------------------------------------------------------------------------
class _Sheet:
    """Writes rows top to bottom on one worksheet, keeping the row number."""

    def __init__(self, ws):
        self.ws, self.row = ws, 1

    def text(self, value, font=None, merge_to: int = 0) -> None:
        cell = self.ws.cell(self.row, 1, value)
        if font:
            cell.font = font
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if merge_to:
            self.ws.merge_cells(start_row=self.row, start_column=1,
                                end_row=self.row, end_column=merge_to)
            # a long sentence in merged cells needs a taller row to show in full
            self.ws.row_dimensions[self.row].height = 15 * (len(str(value)) // 190 + 1)
        self.row += 1

    def gap(self) -> None:
        self.row += 1

    def table(self, headings: list[str], rows: list[list], money: set[int] = frozenset(),
              qty: set[int] = frozenset(), total: list | None = None) -> None:
        """Headings, rows, and an optional bold total row. money / qty = column
        numbers (0-based) to show as amounts / quantities."""
        for c, h in enumerate(headings, start=1):
            cell = self.ws.cell(self.row, c, h)
            cell.font, cell.fill, cell.border = BOLD, HEAD_FILL, BOX
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        self.row += 1
        for values in rows + ([total] if total else []):
            for c, v in enumerate(values, start=1):
                cell = self.ws.cell(self.row, c, v)
                cell.border = BOX
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if c - 1 in money:
                    cell.number_format = MONEY
                elif c - 1 in qty:
                    cell.number_format = QTY
                if total is not None and values is total:
                    cell.font, cell.fill = BOLD, TOTAL_FILL
            self.row += 1


def invoice_workbook(view: dict) -> Workbook:
    """The working of one invoice (`view` = PayoutStore.working()) as one sheet."""
    w = view["working"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Working"
    for col, width in zip("ABCDEFGHIJK", (30, 30, 7, 12, 12, 12, 12, 36, 12, 11, 11)):
        ws.column_dimensions[col].width = width
    s = _Sheet(ws)
    s.text(f"Working - Invoice {w['invoice_no']}", TITLE, merge_to=11)
    s.text("How the tool worked out the labour and the spot incentive of this invoice. "
           "Check each figure against the invoice PDF and the masters.", None, merge_to=11)

    # 1. what was read - two blocks side by side (A:B and D:H) to save height
    s.text("1. What was read from the invoice", SECTION, merge_to=11)
    exec_text = w["executive"] + (f"  (printed: {w['printed_executive']})"
                                  if w["printed_executive"] else "")
    left = [("Invoice no", w["invoice_no"]), ("Invoice date", _day(w["invoice_date"])),
            ("Customer", w["customer"]), ("Car", w["car"])]
    right = [("Sales executive", exec_text), ("Branch", w["branch"]),
             ("Invoice total (₹)", f"{w['total']:,.2f}"),
             ("Discount / GST (₹)", f"{w['discount']:,.2f} / {w['gst']:,.2f}")]
    for (l1, v1), (l2, v2) in zip(left, right):
        for col, value, bold in ((1, l1, True), (2, v1, False), (4, l2, True), (6, v2, False)):
            cell = ws.cell(s.row, col, value)
            cell.border = BOX
            if bold:
                cell.font, cell.fill = BOLD, HEAD_FILL
        ws.merge_cells(start_row=s.row, start_column=4, end_row=s.row, end_column=5)
        ws.merge_cells(start_row=s.row, start_column=6, end_row=s.row, end_column=8)
        s.row += 1
    if w["markers"]:
        s.text(f"{w['markers']} “Labour charges” line(s) of ₹1 on the invoice are only "
               "markers that labour was done; they are not used (labour comes from the "
               "Product master).", None, merge_to=11)
    s.gap()

    # 2. items
    s.text("2. Items on the invoice", SECTION, merge_to=11)
    items = w["items"]
    s.table(["Printed on invoice", "Read as (master product)", "Qty", "Typed price / unit",
             "Discount share", "Paid (with GST)", "Fixed price / unit", "Fixed price from",
             "Fixed value", "Labour", "Incentive"],
            [[i["printed"], f"{i['product']}  [{i['matched']}]", i["qty"], i["typed_unit"],
              i["discount"], i["paid"], i["fixed_price"], i["fixed_source_text"]
              + (" - in package" if i["in_package"] else ""), i["fixed_value"], i["labour"],
              i["incentive"]] for i in items],
            money={3, 4, 5, 6, 8, 9, 10}, qty={2},
            total=["Total", "", "", "", round(sum(i["discount"] for i in items), 2),
                   round(sum(i["paid"] for i in items), 2), "", "",
                   round(sum(i["fixed_value"] for i in items), 2),
                   round(sum(i["labour"] for i in items), 2),
                   round(sum(i["incentive"] for i in items), 2)])
    s.gap()

    # 3. labour
    s.text("3. Labour  (Product master labour charge x quantity, rate in force on the "
           "invoice date)", SECTION, merge_to=11)
    groups = w["labour"]["groups"]
    if not groups:
        s.text("No item on this invoice carries labour.", None, merge_to=11)
    for g in groups:
        s.text(f"Labour - {g['kind']}", BOLD, merge_to=5)
        s.table(["Product", "Rate from", "Qty", "Rate (₹)", "Amount (₹)"],
                [[i["product"], _day(i["rate_from"]), i["qty"], i["rate"], i["amount"]]
                 for i in g["items"]], money={3, 4}, qty={2},
                total=[f"Labour - {g['kind']}", "", "", "", g["total"]])
    s.text(f"Labour for this invoice: ₹{w['labour']['total']:,.2f}", BOLD, merge_to=5)
    s.gap()

    # 4. spot incentive
    inc = w["incentive"]
    s.text(f"4. Spot incentive  (payable to {inc['payee']})", SECTION, merge_to=11)
    if inc["items"]:
        s.table(["Product", "Incentive group", "Qty", "Incentive / unit", "Amount (₹)",
                 "Rate from"],
                [[i["product"], i["group"], i["qty"], i["rate"], i["amount"],
                  _day(i["rate_from"])] for i in inc["items"]], money={3, 4}, qty={2})
    k = inc["package"]
    if k:
        s.text(f"Package sold: {k['name']} (all its items are on the invoice: "
               f"{', '.join(k['items'])}). Package incentive ₹{k['incentive']:,.2f}; its "
               f"items count at the coupon value ₹{k['coupon_value']:,.2f} as their fixed "
               "price, and lose their own item incentives.", None, merge_to=11)
    # the steps, each with the invoice's own numbers (working.py writes them)
    for step in inc["steps"]:
        s.text("• " + step, None, merge_to=11)
    s.text(f"Spot incentive payable: ₹{inc['payable']:,.2f}", BOLD, merge_to=5)
    s.gap()

    # 5. internal team
    s.text("5. Internal team incentive  (Product master internal incentive x quantity, "
           "in full)", SECTION, merge_to=11)
    if w["internal"]["items"]:
        s.table(["Product", "Qty", "Rate (₹)", "Amount (₹)"],
                [[i["product"], i["qty"], i["rate"], i["amount"]]
                 for i in w["internal"]["items"]], money={2, 3}, qty={1},
                total=["Internal team", "", "", w["internal"]["total"]])
    else:
        s.text("None on this invoice.", None, merge_to=11)
    s.gap()

    # 6. lines
    s.text("6. Payout lines in the register", SECTION, merge_to=11)
    status = {l["line_id"]: l["status"] for l in view.get("lines", [])}
    # column C is narrow (it holds Qty above), so it stays empty here
    s.table(["Line ID", "Type - pay to", "", "Amount (₹)", "Status now"],
            [[l["line_id"], l["type"] + (f" - {l['payee']}" if l["payee"] else ""), "",
              l["amount"], status.get(l["line_id"], "")] for l in w["lines"]], money={3},
            total=["Total", "", "", round(sum(l["amount"] for l in w["lines"]), 2), ""])
    extra = [l for l in view.get("lines", []) if "-ADJ" in l["line_id"]]
    if extra:
        s.text("Adjustment lines (invoice re-issued after payment): " + "; ".join(
            f"{l['line_id']} {l['payee'] or l['type']} ₹{l['amount']:,.2f} ({l['status']})"
            for l in extra), None, merge_to=11)
    s.gap()

    h = view["history"][0] if view.get("history") else None
    if h:
        s.text(f"Calculated: {h['why']} on {h['made_at']} by {h['made_by']}.", None, merge_to=11)
    c = view.get("check")
    if c:
        s.text(f"Checked by {c['checked_by']} on {c['checked_at']}"
               + (f" - {c['note']}" if c["note"] else "")
               + ("" if c.get("current") else " (an EARLIER working - recalculated since)") + ".",
               None, merge_to=11)
    else:
        s.text("Checked by: ______________________    Date: ____________", None, merge_to=11)

    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    # An ordinary invoice (up to ~60 rows) is shrunk to ONE page; a long one
    # keeps a readable size and runs on to more pages.
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if s.row <= 60 else 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.oddFooter.center.text = "Page &P of &N"
    return wb


def invoice_pdf(view: dict) -> bytes:
    """The one-invoice sheet as PDF bytes (raises pdf_export.PdfError)."""
    with tempfile.TemporaryDirectory(prefix="dns_working_") as folder:
        name = "Working_" + "".join(ch if ch.isalnum() or ch in "-_" else "_"
                                    for ch in view["working"]["invoice_no"])
        xlsx = Path(folder) / f"{name}.xlsx"
        invoice_workbook(view).save(xlsx)
        return export_pdf(xlsx, Path(folder) / f"{name}.pdf").read_bytes()


# ---------------------------------------------------------------------------
# Many invoices - for checking with her own formulas
# ---------------------------------------------------------------------------
INVOICE_COLUMNS = [
    # (heading, width, kind)  kind: text / money / pct
    ("Invoice no", 16, "text"), ("Invoice date", 12, "text"), ("Customer", 24, "text"),
    ("Car", 16, "text"), ("Sales executive", 18, "text"),
    ("Labour - Floor mat", 12, "money"), ("Labour - Sunfilm", 12, "money"),
    ("Labour - Other", 12, "money"),
    ("Labour total (check)", 13, "money"), ("Labour posted", 12, "money"),
    ("Labour difference", 12, "money"),
    ("Package", 18, "text"), ("Fixed prices", 13, "money"), ("Paid for items", 13, "money"),
    ("Share earned (check)", 11, "pct"), ("Full incentive", 12, "money"),
    ("Incentive (check)", 12, "money"), ("Incentive posted", 12, "money"),
    ("Incentive difference", 12, "money"), ("Internal team", 12, "money"),
    ("Calculated", 30, "text"), ("Checked by", 22, "text"), ("Checked on", 16, "text"),
    ("Note", 30, "text"),
]
ITEM_COLUMNS = [
    ("Invoice no", 16, "text"), ("Printed on invoice", 30, "text"),
    ("Read as (master product)", 30, "text"), ("Matched", 11, "text"), ("Qty", 7, "qty"),
    ("Typed price / unit", 12, "money"), ("Typed amount", 12, "money"),
    ("Discount share", 12, "money"), ("Paid (with GST)", 12, "money"),
    ("Fixed price / unit", 12, "money"), ("Fixed price from", 26, "text"),
    ("Fixed value (check)", 12, "money"), ("In package", 9, "text"),
    ("Labour kind", 11, "text"), ("Labour rate", 11, "money"),
    ("Labour (check)", 12, "money"), ("Labour rate from", 12, "text"),
    ("Incentive group", 20, "text"), ("Incentive / unit", 11, "money"),
    ("Incentive (check)", 12, "money"), ("Incentive rate from", 12, "text"),
    ("Internal / unit", 11, "money"), ("Internal (check)", 12, "money"),
]
READ_ME = [
    "WORKINGS OF THE DAILY PAYOUTS",
    "",
    "Sheet Invoices: one row per invoice. Columns marked (check) are Excel formulas worked "
    "out from the other columns; the column beside them is what the tool posted, and the "
    "difference should be 0.",
    "    Labour total (check) = Floor mat + Sunfilm + Other.",
    "    Share earned (check) = Paid for items / Fixed prices, at most 100% (100% when there "
    "are no fixed prices).",
    "    Incentive (check) = Full incentive x Share earned, to the paisa.",
    "    Full incentive = every item incentive x qty (sheet Items) + the package incentive.",
    "    A package's items count at the coupon value as their fixed price, so for those "
    "invoices Fixed prices is not the sum of the items' fixed values.",
    "Sheet Items: one row per item. Labour (check) = Labour rate x Qty; Incentive (check) = "
    "Incentive / unit x Qty; Internal (check) = Internal / unit x Qty; Fixed value (check) = "
    "Fixed price / unit x Qty.",
    "    Fixed price from: Bill value (Incentive master) for an item with an incentive group, "
    "else Selling price (Product master), else the price typed on the invoice.",
    "    Rate from: the date from which the master rate used was in force (the rate in force "
    "on the invoice date is used).",
    "Amounts are exact: spot incentive is rounded up to the next ₹10 only on each "
    "executive's month total in the monthly report.",
    "Every figure is the one stored when the invoice was posted (or last recalculated), so a "
    "master changed later does not change it.",
]


def _header(ws, columns) -> None:
    for c, (heading, width, _) in enumerate(columns, start=1):
        cell = ws.cell(1, c, heading)
        cell.font, cell.fill, cell.border = BOLD, HEAD_FILL, BOX
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}1"


def _put(ws, row: int, columns, values: list) -> None:
    for c, ((_, _, kind), v) in enumerate(zip(columns, values), start=1):
        cell = ws.cell(row, c, v)
        if kind == "money":
            cell.number_format = MONEY
        elif kind == "pct":
            cell.number_format = "0.00%"
        elif kind == "qty":
            cell.number_format = QTY


def range_workbook(entries: list[dict], title: str) -> Workbook:
    """
    `entries`: one dict per invoice, as PayoutStore.working() gives it
    (working may be None for an invoice posted before v0.37.0 whose working
    was never rebuilt - it gets a row with the posted amounts and a note).
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Invoices"
    items = wb.create_sheet("Items")
    readme = wb.create_sheet("Read me")
    _header(ws, INVOICE_COLUMNS)
    _header(items, ITEM_COLUMNS)
    r = ir = 2
    for e in entries:
        w, inv, lines = e["working"], e["invoice"], e["lines"]
        live = [l for l in lines if l["status"] != "Cancelled"]
        posted_labour = round(sum(l["amount"] for l in live if l["type"].startswith("Labour")), 2)
        posted_inc = round(sum(l["amount"] for l in live if l["type"] == "Spot incentive"), 2)
        check = e.get("check") or {}
        h = e["history"][0] if e.get("history") else None
        checked = [check.get("checked_by", ""), check.get("checked_at", ""),
                   (check.get("note", "") + ("" if check.get("current", True)
                                             else " (checked an earlier working)")).strip()]
        if w is None:
            _put(ws, r, INVOICE_COLUMNS,
                 [inv["invoice_no"], inv["invoice_date"],          # already dd-mm-yyyy
                  inv["customer"], "", inv["salesperson"], None, None, None, None,
                  posted_labour, None, "", None, None, None, None, None, posted_inc, None,
                  None, "Working not saved (posted before v0.37.0) - open Show working "
                  "to rebuild it", *checked])
            r += 1
            continue
        kinds = {g["kind"]: g["total"] for g in w["labour"]["groups"]}
        inc = w["incentive"]
        k = inc["package"]
        _put(ws, r, INVOICE_COLUMNS, [
            w["invoice_no"], _day(w["invoice_date"]), w["customer"], w["car"],
            w["executive"] + (f" ({w['printed_executive']})" if w["printed_executive"] else ""),
            kinds.get("Floor mat", 0), kinds.get("Sunfilm", 0), kinds.get("Other", 0),
            f"=F{r}+G{r}+H{r}", posted_labour, f"=ROUND(I{r}-J{r},2)",
            f"{k['name']} ({k['coupon_value']:,.2f})" if k else "",
            inc["fixed"], inc["paid"],
            f"=IF(M{r}<=0,1,MIN(1,N{r}/M{r}))", inc["full"], f"=ROUND(P{r}*O{r},2)",
            posted_inc, f"=ROUND(Q{r}-R{r},2)", w["internal"]["total"],
            f"{h['why']} {h['made_at']} {h['made_by']}" if h else "", *checked])
        r += 1
        for i in w["items"]:
            _put(items, ir, ITEM_COLUMNS, [
                w["invoice_no"], i["printed"], i["product"], i["matched"], i["qty"],
                i["typed_unit"], i["typed"], i["discount"], i["paid"], i["fixed_price"],
                i["fixed_source_text"], f"=ROUND(J{ir}*E{ir},2)",
                "Yes" if i["in_package"] else "", i["labour_kind"], i["labour_rate"],
                f"=ROUND(O{ir}*E{ir},2)", _day(i["rate_from"]), i["incentive_group"],
                i["incentive_rate"], f"=ROUND(S{ir}*E{ir},2)", _day(i["incentive_from"]),
                i["internal_rate"], f"=ROUND(V{ir}*E{ir},2)"])
            ir += 1
    if r > 2:                                              # totals under the invoices
        ws.cell(r, 1, "Total").font = BOLD
        for c, (_, _, kind) in enumerate(INVOICE_COLUMNS, start=1):
            if kind == "money":
                L = get_column_letter(c)
                cell = ws.cell(r, c, f"=SUM({L}2:{L}{r - 1})")
                cell.number_format, cell.font, cell.fill = MONEY, BOLD, TOTAL_FILL
    readme.column_dimensions["A"].width = 120
    readme.cell(1, 1, title).font = TITLE
    for n, text in enumerate(READ_ME, start=3):
        cell = readme.cell(n, 1, text)
        cell.alignment = Alignment(wrap_text=True)
        if n == 3:
            cell.font = BOLD
    return wb

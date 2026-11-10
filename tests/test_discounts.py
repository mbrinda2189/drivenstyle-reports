"""
test_discounts.py - v0.32.0: the discount shown in the reports
==============================================================

Brinda (10-11-2026): "why aren't the discounts calculated?" They were -
sales have always been after discount - but no report showed how much was
given. These tests use the two real invoices of test_reports (DNS-226-2627
carries a Rs. 1,903 discount, no GST) and check:

    * MonthData.discount = the lines' discount shares, EXCLUDING GST, so
      sales + discount = the lines at Zoho's price before discount;
    * Profit & loss: "Sales before discount", "Less: discount given", then
      Sales as a formula of the two (Excel and PDF);
    * Invoice-wise and Executive-wise sheets: Discount and Discount %;
    * Summary and Trend: the discount rows.
"""

import openpyxl

from app.reports.data import build_month
from app.reports.generate import generate
from app.reports.pdf_book import write_pdf_workbook
from app.sample_data import REPORTS
from tests.test_reports import world  # noqa: F401


def test_discount_figures(world):  # noqa: F811
    repo, inv, inp = world
    d = build_month(repo, inv, inp, 2026, 9)
    i226 = next(i for i in d.invoices if i.invoice_no == "DNS-226-2627")
    assert i226.discount == 1903                                   # as on the invoice (no GST)
    assert abs(i226.sales_discount - 1903) <= 1                    # the lines' shares, excl. GST
    assert d.discount == round(sum(i.sales_discount for i in d.invoices), 2) > 0
    # sales + discount = the lines before discount, excluding GST
    before = sum(l.sales + l.discount for l in d.lines)
    assert round(d.sales + d.discount, 2) == round(before, 2)


def test_discount_in_the_workbook(world, tmp_path):  # noqa: F811
    repo, inv, inp = world
    d = build_month(repo, inv, inp, 2026, 9)
    r = generate(repo, inv, inp, 2026, 9, tmp_path, list(REPORTS))
    wb = openpyxl.load_workbook(r.path)

    pnl = list(wb["12 Profit & loss"].iter_rows(values_only=True))
    first = [row[0] for row in pnl]
    at = first.index("Sales before discount")
    assert first[at + 1] == "Less: discount given" and first[at + 2] == "Sales (excluding GST)"
    assert pnl[at][1] == round(d.sales + d.discount, 2) and pnl[at + 1][1] == d.discount
    assert pnl[at + 2][1] == f"=B{at + 1}-B{at + 2}"               # sheet rows are 1-based
    assert pnl[at][2] is None and pnl[at + 1][2] is None           # no "% of sales" on them
    assert "Labour - tool vs Zoho" not in first                    # no Zoho expense file

    def heading(sheet, first_cell):
        return next(row for row in wb[sheet].iter_rows(values_only=True) if row[0] == first_cell)
    assert {"Discount", "Discount %"} <= set(heading("1 Invoice profitability", "Invoice no"))
    assert {"Discount given", "Discount %"} <= set(heading("8 Executive-wise sales", "Executive"))

    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(values_only=True) if row[0]}
    assert summary["Discount given (excl. GST)"] == d.discount
    assert abs(summary["Discount % of price before discount"]
               - d.discount / (d.sales + d.discount)) < 1e-9
    trend = [row[0] for row in wb["4 Trend"].iter_rows(values_only=True)]
    assert "Discount given (excl. GST)" in trend

    # the PDF version's P&L has the same three lines
    ws = openpyxl.load_workbook(write_pdf_workbook(d, [d], None, tmp_path / "p.xlsx"))["Report"]
    text = [row[0] for row in ws.iter_rows(values_only=True)]
    at = text.index("Sales before discount")
    assert text[at + 1:at + 3] == ["Less: discount given", "Sales (excluding GST)"]


def test_labour_tool_vs_zoho_in_the_pnl(world, tmp_path):  # noqa: F811
    """Only shown when the month's Zoho labour is known (uploaded expenses);
    the P&L itself keeps the tool's labour."""
    repo, inv, inp = world
    inp.save_books_labour(2026, 9, {"Sunfilm": 900.0, "Floor mat": 400.0})
    d = build_month(repo, inv, inp, 2026, 9)
    r = generate(repo, inv, inp, 2026, 9, tmp_path, ["Profit & loss"])
    pnl = list(openpyxl.load_workbook(r.path)["12 Profit & loss"].iter_rows(values_only=True))
    first = [row[0] for row in pnl]
    labour_row = pnl[first.index("Labour")]
    assert labour_row[1] == round(sum(i.labour for i in d.invoices), 2)   # tool's figure in P&L
    at = first.index("Labour - tool vs Zoho")
    assert pnl[at + 1][:4] == ("Labour", "Tool (used in P&L)", "As per Zoho", "Difference")
    rows = {row[0]: row for row in pnl[at + 2:] if row[0]}
    assert rows["Sunfilm"][1] == d.labour_by_kind["Sunfilm"] and rows["Sunfilm"][2] == 900
    assert rows["Floor mat"][2] == 400
    # saved again with the same figures: nothing new in the audit log
    before = len(repo.audit_entries(master="inputs"))
    inp.save_books_labour(2026, 9, {"Sunfilm": 900.0, "Floor mat": 400.0})
    assert len(repo.audit_entries(master="inputs")) == before

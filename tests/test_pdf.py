"""
test_pdf.py - The workbook as one PDF (v0.9.1)
==============================================

Excel makes the PDF (through PowerShell), so the real export can only run on
a Windows PC with Excel. Here: the page set-up written into the workbook,
what happens when the PDF cannot be made, and the command handed to Windows.
"""

import subprocess
import sys
from types import SimpleNamespace

import openpyxl
import pytest

from app.data.inputs_repo import InputsRepo
from app.reports import pdf_export
from app.reports.generate import generate
from app.reports.pdf_export import PdfError, export_pdf
from tests.test_rto import world  # noqa: F401  (fixture)


def test_workbook_is_set_up_for_printing(world):  # noqa: F811
    masters, irepo, tmp_path = world
    out = tmp_path / "out"
    out.mkdir()
    r = generate(masters, irepo, InputsRepo(masters), 2026, 9, out,
                 ["Invoice-wise profitability", "Profit & loss"])
    wb = openpyxl.load_workbook(r.path)
    for ws in wb:
        assert ws.page_setup.orientation == "landscape"
        assert ws.sheet_properties.pageSetUpPr.fitToPage
        assert "&P" in ws.oddFooter.center.text
    # the long sheet repeats its heading row on every page
    assert wb["1 Invoice profitability"].print_title_rows


@pytest.mark.skipif(sys.platform == "win32", reason="needs a PC without Excel automation")
def test_pdf_problem_does_not_lose_the_workbook(world):  # noqa: F811
    masters, irepo, tmp_path = world
    out = tmp_path / "out"
    out.mkdir()
    r = generate(masters, irepo, InputsRepo(masters), 2026, 9, out, ["Profit & loss"],
                 pdf=True)
    assert r.path.exists() and r.pdf_path is None
    assert "Windows PC with Microsoft Excel" in r.pdf_error


def test_excel_is_asked_for_one_pdf(tmp_path, monkeypatch):
    book = tmp_path / "Reports with space.xlsx"
    openpyxl.Workbook().save(book)
    seen = {}

    def fake_run(cmd, env, **kwargs):
        seen["cmd"], seen["env"] = cmd, env
        (tmp_path / "Reports with space.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf = export_pdf(book)
    assert pdf.name == "Reports with space.pdf" and pdf.exists()
    assert seen["cmd"][0] == "powershell" and "ExportAsFixedFormat" in seen["cmd"][-1]
    assert seen["env"]["DNS_XLSX"].endswith("Reports with space.xlsx")

    # Excel missing -> a message an accountant can act on
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="ERROR: Retrieving the COM class factory ... 80040154 "
                             "Class not registered", stderr=""))
    (tmp_path / "Reports with space.pdf").unlink()
    with pytest.raises(PdfError, match="Microsoft Excel was not found"):
        export_pdf(book)
    with pytest.raises(PdfError, match="no longer"):
        export_pdf(tmp_path / "missing.xlsx")
    assert pdf_export.pdf_path_for("a/b.xlsx").name == "b.pdf"


# --- v0.10.0: the PDF version (summary tables + graphs) and the trend --------------
def test_pdf_version_is_one_flowing_sheet_without_graphs(world):  # noqa: F811
    """v0.10.3: no graphs, no page per section, page numbers, readable print."""
    from app.data.rto_list import read_rto
    from app.reports.data import build_month
    from app.reports.pdf_book import OTHER_COL, incentive_by_executive, write_pdf_workbook
    from tests.test_rto import write_list
    masters, irepo, tmp_path = world
    d = build_month(masters, irepo, InputsRepo(masters), 2026, 9)
    rto = read_rto(write_list(tmp_path / "RTO.xlsx"))
    book = write_pdf_workbook(d, [d], None, tmp_path / "pdf.xlsx", "tester", rto=rto)
    wb = openpyxl.load_workbook(book)
    assert wb.sheetnames == ["Report"]                 # one sheet = sections follow on
    ws = wb["Report"]
    assert not ws._charts and not ws.row_breaks.brk    # no graphs, no forced page breaks
    text = [row[0] for row in ws.iter_rows(values_only=True) if isinstance(row[0], str)]
    assert "Drive N Style – Monthly reports" not in text and "Notes" not in text  # v0.10.5
    order = [text.index(t) for t in (
        "Drive N Style – Executive summary",
        "Service vs product profitability", "Labour calculation",
        "Vehicle-wise average per car", "Spot incentive calculation",
        "High-profit product sales", "Indirect vs direct cost %", "Payment mode analysis",
        "Profit & loss", "New-car penetration", "New-car vs other business")]
    assert order == sorted(order)
    for gone in ("Points needing attention", "Invoice-wise profitability", "Contents",
                 "Trend analysis (month on month)"):   # one month: no Trend
        assert gone not in text
    # page numbers in the footer; fitted to the page width only; no table over 8 columns
    assert "&P" in ws.oddFooter.right.text and "Drive N Style" in ws.oddFooter.left.text
    assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
    assert ws.max_column <= 8
    assert all((ws.column_dimensions[c].width or 0) <= OTHER_COL for c in "BCDEFGH")
    # formulas were shifted to their new rows: the P&L's gross profit is still sales - costs
    row = next(r for r in ws.iter_rows() if r[0].value == "Gross profit"
               and isinstance(r[1].value, str))
    assert row[1].value.startswith("=B") and str(row[0].row - 1) in row[1].value
    # v0.10.4: "% of sales" must divide by the SALES row of its own table (a fixed
    # $B$n reference) - it pointed at another row and showed 189.2% for sales
    for r in ws.iter_rows():
        if r[0].value == "Sales (excluding GST)" and isinstance(r[2].value, str):
            n = r[0].row
            assert r[2].value == f'=IF($B${n}=0,"",B{n}/$B${n})'
            below = ws.cell(n + 2, 3).value                   # Product cost
            assert below == f'=IF($B${n}=0,"",B{n + 2}/$B${n})'
    # v0.10.5: percentages run downwards - indirect cost heads largest first (PDF only)
    inputs = InputsRepo(masters)
    inputs.save_costs(2026, 9, [("Postage", 10.0), ("Rent", 5000.0), ("Salaries", 900.0)])
    d2 = build_month(masters, irepo, inputs, 2026, 9)
    ws2 = openpyxl.load_workbook(write_pdf_workbook(
        d2, [d2], None, tmp_path / "pdf3.xlsx", rto=rto))["Report"]
    labels = [r[0] for r in ws2.iter_rows(values_only=True) if isinstance(r[0], str)]
    at = labels.index("Indirect vs direct cost %")
    heads = labels[labels.index("Indirect costs", at) + 1:
                   labels.index("Total indirect costs", at)]
    # Rent 5,000 > Salaries 900 > automatic 4% (12) > Postage 10 > automatic 3% (9)
    assert heads == ["Rent", "Salaries", "Breakage / returns / transport (4% of COGS)",
                     "Postage", "Compliance GST (3% of COGS)"]
    pen = labels.index("By location - DNS accessories")
    assert labels[pen + 2:pen + 5] == ["POL", "(not given)", "OOTY"]   # 100%, 100%, 50%
    from app.reports.pdf_book import shift_formula
    assert shift_formula('=IF($B$7=0,"",B9/$B$7)', 100) == '=IF($B$107=0,"",B109/$B$107)'
    assert shift_formula("=ROUND(B11*0.04,2)", 5) == "=ROUND(B16*0.04,2)"
    assert shift_formula("=SUM(C8:C11)", 10) == "=SUM(C18:C21)"

    # the Excel workbook keeps its attention points and every sheet
    r = generate(masters, irepo, InputsRepo(masters), 2026, 9, tmp_path, ["Profit & loss"])
    cells = [c[0] for c in openpyxl.load_workbook(r.path)["Summary"].iter_rows(
        values_only=True) if c[0]]
    assert "Points needing attention" in cells

    # two months -> the Trend section is added, without its charts
    book = write_pdf_workbook(d, [d, d], None, tmp_path / "pdf2.xlsx", rto=None)
    ws = openpyxl.load_workbook(book)["Report"]
    text = [row[0] for row in ws.iter_rows(values_only=True) if isinstance(row[0], str)]
    assert "Trend analysis (month on month)" in text and "New-car penetration" not in text
    assert not ws._charts
    payable = [g["payable"] for g in incentive_by_executive(d)]
    assert payable == sorted(payable, reverse=True)


def test_trend_sheet_and_saved_delivery_totals(world):  # noqa: F811
    from tests.test_rto import write_list
    masters, irepo, tmp_path = world
    inputs = InputsRepo(masters)
    out = tmp_path / "out"
    out.mkdir()
    r = generate(masters, irepo, inputs, 2026, 9, out, ["Trend analysis (month on month)"],
                 rto_path=str(write_list(tmp_path / "RTO.xlsx")))
    saved = inputs.rto_months()["2026-09"]
    assert (saved["cars"], saved["took_dns"]) == (4, 3)
    ws = openpyxl.load_workbook(r.path)["4 Trend"]
    col = {row[0]: row[1] for row in ws.iter_rows(values_only=True) if row[0]}
    assert col["Sales (excluding GST)"] == 6300 and col["Invoices"] == 3
    assert col["Cars delivered (delivery list)"] == 4 and col["DNS penetration %"] == 0.75
    assert "Sales by branch" in col and "Top 10 products by sales" in col
    assert len(ws._charts) == 2                      # lines + penetration bars

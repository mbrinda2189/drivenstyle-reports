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
def test_pdf_version_has_only_the_summary_pages(world):  # noqa: F811
    from app.data.rto_list import read_rto
    from app.reports.data import build_month
    from app.reports.pdf_book import incentive_by_executive, write_pdf_workbook
    from tests.test_rto import write_list
    masters, irepo, tmp_path = world
    d = build_month(masters, irepo, InputsRepo(masters), 2026, 9)
    rto = read_rto(write_list(tmp_path / "RTO.xlsx"))
    book = write_pdf_workbook(d, [d], None, tmp_path / "pdf.xlsx", "tester", rto=rto)
    wb = openpyxl.load_workbook(book)
    assert wb.sheetnames == [
        "Cover", "Summary", "Service vs product", "Labour", "Vehicle-wise",
        "Spot incentive", "High-profit products", "Indirect vs direct", "Payment modes",
        "Profit & loss", "New-car penetration", "New-car vs other"]      # one month: no Trend
    summary = [row[0] for row in wb["Summary"].iter_rows(values_only=True) if row[0]]
    assert "Points needing attention" not in summary
    for ws in wb:                                   # one section = one page, with a graph
        assert ws.page_setup.fitToHeight == 1 and ws.page_setup.orientation == "portrait"
    charted = [name for name in wb.sheetnames if wb[name]._charts]
    assert len(charted) >= 9 and "Profit & loss" in charted      # (no labour here -> no graph)
    assert wb["Service vs product"].print_area            # chart figures are not printed
    # the Excel workbook keeps its attention points and every sheet
    r = generate(masters, irepo, InputsRepo(masters), 2026, 9, tmp_path, ["Profit & loss"])
    cells = [row[0] for row in openpyxl.load_workbook(r.path)["Summary"].iter_rows(
        values_only=True) if row[0]]
    assert "Points needing attention" in cells

    # two months -> the Trend page is added
    book = write_pdf_workbook(d, [d, d], None, tmp_path / "pdf2.xlsx", rto=None)
    names = openpyxl.load_workbook(book).sheetnames
    assert names[-1] == "Trend" and "New-car penetration" not in names
    # by executive: highest incentive payable first
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

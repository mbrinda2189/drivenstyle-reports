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

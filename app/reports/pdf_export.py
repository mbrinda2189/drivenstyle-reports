"""
pdf_export.py - The reports workbook as one PDF (v0.9.1)
========================================================

WHAT THIS DOES
--------------
`export_pdf(workbook_path)` saves the whole workbook as ONE PDF file beside
it (same name, .pdf): every sheet starts on a new page, landscape, fitted
to the page width. Short sheets (Summary, Profit & loss ...) take one page;
long ones (148 invoices) run onto further pages with their column headings
repeated and "sheet name - page x of y" in the footer (set when the
workbook is written, see workbook._finish).

WHY IT USES EXCEL
-----------------
The totals in the workbook are Excel formulas, so the figures exist only
after Excel has calculated them; the tool itself never works them out
twice. Excel is therefore asked to open the workbook and "Save as PDF" -
the PDF then shows exactly what the workbook shows. Brinda confirmed
(03-10-2026) that the client's PC has Excel.

HOW
---
Excel is driven through Windows PowerShell (which is part of Windows), so
no extra Python package is needed and nothing extra has to be bundled in
the executable. Excel runs hidden, opens the workbook read-only,
recalculates, exports and quits. The two file paths are handed over as
environment variables, so names with spaces or apostrophes are safe.

WHEN IT CANNOT WORK
-------------------
Not on Windows, Excel not installed, the PDF open in a viewer, or Excel not
answering within three minutes: `PdfError` is raised with a plain message.
The workbook itself is never affected - generate() reports the PDF problem
separately.

No Qt and no database code here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 180

# 0 = xlTypePDF. $ErrorActionPreference makes any COM error stop the script
# so it is reported; "finally" always closes Excel, or a hidden EXCEL.EXE
# would be left running.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$xl = $null
try {
    $xl = New-Object -ComObject Excel.Application
    $xl.Visible = $false
    $xl.DisplayAlerts = $false
    $wb = $xl.Workbooks.Open($env:DNS_XLSX, 0, $true)
    $xl.CalculateFull()
    $wb.ExportAsFixedFormat(0, $env:DNS_PDF)
    $wb.Close($false)
} catch {
    Write-Output ("ERROR: " + $_.Exception.Message)
    exit 1
} finally {
    if ($xl -ne $null) {
        $xl.Quit()
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
    }
}
"""


class PdfError(Exception):
    """The PDF could not be made (plain-language message)."""


def pdf_path_for(workbook_path: str | Path) -> Path:
    return Path(workbook_path).with_suffix(".pdf")


def export_pdf(workbook_path: str | Path, target: str | Path | None = None) -> Path:
    """
    Save the workbook as one PDF; returns the PDF's path. `target` = where
    to save it (v0.10.0: the PDF is made from a temporary "PDF version"
    workbook but saved beside the real one); default: beside the workbook.
    """
    source = Path(workbook_path).resolve()
    target = Path(target).resolve() if target else pdf_path_for(source)
    if not source.exists():
        raise PdfError(f"“{source.name}” is no longer where it was saved.")
    if sys.platform != "win32":
        raise PdfError("A PDF can only be made on a Windows PC with Microsoft Excel.")
    env = dict(os.environ, DNS_XLSX=str(source), DNS_PDF=str(target))
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", SCRIPT],
            env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise PdfError("Windows PowerShell was not found on this PC.") from exc
    except subprocess.TimeoutExpired as exc:
        raise PdfError("Excel did not finish making the PDF in three minutes. Close any "
                       "Excel message that is waiting and try again.") from exc
    if done.returncode != 0 or not target.exists():
        raise PdfError(_explain((done.stdout or "") + (done.stderr or ""), target))
    return target


def _explain(output: str, target: Path) -> str:
    """Turn Excel's / PowerShell's message into something an accountant can act on."""
    low = output.lower()
    if "80040154" in low or "class not registered" in low or "excel.application" in low \
            and "cannot" in low:
        return ("Microsoft Excel was not found on this PC, so the PDF could not be made. "
                "The Excel workbook is saved.")
    if "document not saved" in low or "being used" in low or "0x800a03ec" in low:
        return (f"“{target.name}” could not be saved. If it is open in a PDF viewer, "
                "close it and try again.")
    detail = " ".join(output.replace("ERROR:", "").split())[:300]
    return "Excel could not make the PDF." + (f" ({detail})" if detail else "")

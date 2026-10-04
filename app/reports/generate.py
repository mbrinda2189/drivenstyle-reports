"""
generate.py - Build a month's workbook in one call
==================================================

WHAT THIS MODULE DOES
---------------------
`generate(masters, invoices, inputs, year, month, out_dir, reports,
payments_path)` is used by the Generate page and by History > Regenerate:

    1. reads the payments export, if one is given (payments_io.py)
    2. works out the month's figures and the trend months (data.py)
    3. writes DriveNStyle_<Mon>-<YYYY>_Reports.xlsx in `out_dir`
       (workbook.py), replacing an earlier file of the same name
    4. records the run for the History screen (inputs_repo.record_run)

Returns a `GenerateResult` (path, counts, sales, gross profit).

Problems the user can fix are raised as `GenerateError` with a plain
message: the workbook is open in Excel, the folder cannot be written, the
payments file is not a Zoho export, or the month has not been scanned.
"""

from __future__ import annotations

from dataclasses import dataclass
import tempfile
from datetime import datetime
from pathlib import Path

from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import InvoicesRepo, MONTH_NAMES
from app.data.masters_repo import MastersRepo
from app.data.payments_io import PaymentsFileError, read_payments
from app.data.rto_list import RtoFileError, read_rto
from app.reports.data import build_month, scanned_months, trend_months
from app.reports.pdf_book import write_pdf_workbook
from app.reports.pdf_export import PdfError, export_pdf, pdf_path_for
from app.reports.rto_reports import Linked
from app.reports.workbook import write_workbook


class GenerateError(Exception):
    """A plain-language reason the workbook could not be made."""


@dataclass
class GenerateResult:
    path: Path
    invoices: int
    left_out: int
    sales: float
    gross_profit: float
    payments_used: bool
    pdf_path: Path | None = None      # v0.9.1: the PDF, when asked for and made
    pdf_error: str = ""               # why the PDF could not be made (workbook is fine)


def file_name(year: int, month: int, at: datetime | None = None) -> str:
    """
    v0.8.0: the name carries the date and time the workbook was generated
    (e.g. DriveNStyle_Sep-2026_Reports_03-10-2026_2122.xlsx), so every
    result is kept and an earlier one is never overwritten.
    """
    stamp = f"_{at:%d-%m-%Y_%H%M}" if at else ""
    return f"DriveNStyle_{MONTH_NAMES[month - 1][:3]}-{year}_Reports{stamp}.xlsx"


def _read_inputs(payments_path: str, rto_path: str):
    """The optional files: (payments or None, delivery list or None)."""
    payments = rto = None
    if payments_path:
        try:
            payments = read_payments(payments_path)
        except PaymentsFileError as exc:
            raise GenerateError(str(exc)) from exc
    if rto_path:                      # v0.9.0: the dealership's delivery list
        try:
            rto = read_rto(rto_path)
        except RtoFileError as exc:
            raise GenerateError(str(exc)) from exc
    return payments, rto


def _previous(masters, invoices, inputs, year: int, month: int):
    """The month before (if it has been read), for the executive summary."""
    earlier = [m for m in scanned_months(invoices) if m < (year, month)]
    return build_month(masters, invoices, inputs, *earlier[-1]) if earlier else None


def generate(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
             year: int, month: int, out_dir: str | Path, reports: list[str],
             payments_path: str = "", rto_path: str = "",
             pdf: bool = False) -> GenerateResult:
    if invoices.scan_run(year, month) is None:
        raise GenerateError("This month's invoices have not been read yet.")
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise GenerateError(f"The folder “{out_dir}” does not exist.")
    payments, rto = _read_inputs(payments_path, rto_path)

    # Products added or imported since the invoices were read also take
    # Zoho's item type as their category, unless it was set by hand.
    invoices.apply_zoho_categories()
    data = build_month(masters, invoices, inputs, year, month)
    if rto is not None:
        # v0.10.0: keep the list's totals so the trend can show penetration
        # month by month (the list itself is not stored).
        link = Linked(data, rto)
        inputs.save_rto_month(year, month, len(rto),
                              sum(link.took_dns(c) for c in rto),
                              sum(c.dns_value for c in rto), sum(c.oe_value for c in rto))
    want_trend = "Trend analysis (month on month)" in reports
    trend = (trend_months(masters, invoices, inputs, year, month)
             if want_trend or pdf else [])
    previous = _previous(masters, invoices, inputs, year, month)
    rto_by_month = inputs.rto_months()
    path = out_dir / file_name(year, month, datetime.now())
    try:
        write_workbook(data, trend if want_trend else [], payments, reports, path,
                       masters.user, rto=rto, previous=previous,
                       rto_by_month=rto_by_month)
    except PermissionError as exc:
        raise GenerateError(f"“{path.name}” could not be saved. If it is open in "
                            "Excel, close it and generate again.") from exc
    except OSError as exc:
        raise GenerateError(f"The workbook could not be saved: {exc}") from exc

    inputs.record_run(year, month, str(path), len(data.invoices), len(data.left_out),
                      data.sales, data.gross_profit, payments_path or "", reports,
                      rto_path or "")
    result = GenerateResult(path, len(data.invoices), len(data.left_out), data.sales,
                            data.gross_profit, payments is not None)
    if pdf:
        # A failure here (no Excel on the PC ...) must not lose the
        # workbook: it is reported separately.
        try:
            result.pdf_path = _make_pdf(data, trend, payments, rto, previous,
                                        rto_by_month, path, masters.user)
        except PdfError as exc:
            result.pdf_error = str(exc)
    return result


def _make_pdf(data, trend, payments, rto, previous, rto_by_month, workbook_path: Path,
              user: str) -> Path:
    """
    v0.10.0: the PDF is made from a temporary "PDF version" workbook
    (summary tables and graphs only - app/reports/pdf_book.py), saved beside
    the real workbook with the same name, and the temporary file is removed.
    """
    with tempfile.TemporaryDirectory(prefix="dns_pdf_") as folder:
        book = Path(folder) / (workbook_path.stem + ".xlsx")
        try:
            write_pdf_workbook(data, trend, payments, book, user, rto=rto,
                               previous=previous, rto_by_month=rto_by_month)
        except OSError as exc:
            raise PdfError(f"The PDF version could not be prepared: {exc}") from exc
        return export_pdf(book, pdf_path_for(workbook_path))


def make_pdf(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
             year: int, month: int, workbook_path: str | Path,
             payments_path: str = "", rto_path: str = "") -> Path:
    """
    The PDF for a month from History: built from the data as it is NOW
    (masters and Scan review fixes made since are included), saved beside
    the workbook it belongs to. Raises PdfError / GenerateError.
    """
    payments, rto = _read_inputs(payments_path, rto_path)
    data = build_month(masters, invoices, inputs, year, month)
    return _make_pdf(data, trend_months(masters, invoices, inputs, year, month), payments,
                     rto, _previous(masters, invoices, inputs, year, month),
                     inputs.rto_months(), Path(workbook_path), masters.user)

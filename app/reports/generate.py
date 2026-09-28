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
from pathlib import Path

from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import InvoicesRepo, MONTH_NAMES
from app.data.masters_repo import MastersRepo
from app.data.payments_io import PaymentsFileError, read_payments
from app.reports.data import build_month, trend_months
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


def file_name(year: int, month: int) -> str:
    return f"DriveNStyle_{MONTH_NAMES[month - 1][:3]}-{year}_Reports.xlsx"


def generate(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
             year: int, month: int, out_dir: str | Path, reports: list[str],
             payments_path: str = "") -> GenerateResult:
    if invoices.scan_run(year, month) is None:
        raise GenerateError("This month's invoices have not been read yet.")
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise GenerateError(f"The folder “{out_dir}” does not exist.")

    payments = None
    if payments_path:
        try:
            payments = read_payments(payments_path)
        except PaymentsFileError as exc:
            raise GenerateError(str(exc)) from exc

    # Products added or imported since the invoices were read also take
    # Zoho's item type as their category, unless it was set by hand.
    invoices.apply_zoho_categories()
    data = build_month(masters, invoices, inputs, year, month)
    trend = (trend_months(masters, invoices, inputs, year, month)
             if "Trend analysis (month on month)" in reports else [])
    path = out_dir / file_name(year, month)
    try:
        write_workbook(data, trend, payments, reports, path, masters.user)
    except PermissionError as exc:
        raise GenerateError(f"“{path.name}” could not be saved. If it is open in "
                            "Excel, close it and generate again.") from exc
    except OSError as exc:
        raise GenerateError(f"The workbook could not be saved: {exc}") from exc

    inputs.record_run(year, month, str(path), len(data.invoices), len(data.left_out),
                      data.sales, data.gross_profit, payments_path or "", reports)
    return GenerateResult(path, len(data.invoices), len(data.left_out), data.sales,
                          data.gross_profit, payments is not None)
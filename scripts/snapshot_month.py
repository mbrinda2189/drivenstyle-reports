"""
snapshot_month.py - Save a month's figures as the "before" picture (v0.22.0)
============================================================================

WHAT THIS SCRIPT DOES
---------------------
Before the tool moves to the web, the figures the desktop tool gives today
are written down, so every later version can be checked against them:

    python scripts/snapshot_month.py 2026 9

    1. makes a COPY of the tool's database in data/baseline/drivenstyle.db
       (the real database is only read, never changed - not even upgraded)
    2. works out the month from that copy, exactly as Generate reports does
    3. writes the figures to data/baseline/figures_2026-09.json
    4. prints the totals, to compare by eye with the month's workbook

From then on `python -m pytest` also runs tests/test_baseline.py: it works
the month out again from the copied database and fails, naming the figure,
if anything is no longer the same.

Run it again ONLY when a figure is meant to change (a rule the client
changed, a master corrected): the old "before" picture is then replaced.

    --db PATH    use this database instead of the tool's own
                 (%LOCALAPPDATA%\\Drive N Style Reports\\drivenstyle.db)
    --out PATH   folder for the copy and the figures (default data/baseline)

data/ is never committed to Git: these are the client's figures.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data.database import connect            # noqa: E402
from app.data.inputs_repo import InputsRepo      # noqa: E402
from app.data.invoices_repo import InvoicesRepo  # noqa: E402
from app.data.masters_repo import MastersRepo    # noqa: E402
from app.data.paths import database_path         # noqa: E402
from app.reports import snapshot as snap         # noqa: E402
from app.utils import format_inr                 # noqa: E402

DB_COPY = "drivenstyle.db"


def figures_name(year: int, month: int) -> str:
    return f"figures_{year:04d}-{month:02d}.json"


def figures_from(db_file: Path, year: int, month: int) -> dict:
    """
    Work a month out from a database file WITHOUT touching that file: it is
    copied to a temporary folder first, because opening a database with this
    version of the tool may upgrade it.
    """
    with tempfile.TemporaryDirectory(prefix="dns_snapshot_") as folder:
        work = Path(folder) / DB_COPY
        shutil.copy2(db_file, work)
        conn = connect(work)
        try:
            masters = MastersRepo(conn, user="snapshot")
            invoices = InvoicesRepo(masters)
            inputs = InputsRepo(masters)
            if invoices.scan_run(year, month) is None:
                raise SystemExit(f"{year:04d}-{month:02d} has not been read into "
                                 f"this database ({db_file}).")
            return snap.snapshot(masters, invoices, inputs, year, month)
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Save a month's figures as the baseline.")
    parser.add_argument("year", type=int)
    parser.add_argument("month", type=int)
    parser.add_argument("--db", default="", help="database file (default: the tool's own)")
    parser.add_argument("--out", default=str(ROOT / "data" / "baseline"))
    args = parser.parse_args(argv)

    source = Path(args.db) if args.db else database_path()
    if not source.is_file():
        print(f"No database at {source}")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    copy = out / DB_COPY
    if source.resolve() != copy.resolve():
        shutil.copy2(source, copy)

    figures = figures_from(copy, args.year, args.month)
    path = snap.save(figures, out / figures_name(args.year, args.month))

    t = figures["totals"]
    print(f"Figures of {figures['month']} saved in {path}")
    print(f"  Invoices included    {t['invoices']}   (left out: {t['left_out']})")
    for label, key in (("Sales", "sales"), ("Product cost", "product_cost"),
                       ("Labour", "labour"), ("Gross profit", "gross_profit"),
                       ("Spot incentive", "spot_incentive"),
                       ("Internal incentive", "internal_incentive")):
        print(f"  {label:<20} {format_inr(t[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

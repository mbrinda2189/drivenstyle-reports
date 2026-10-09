"""
test_baseline.py - The figures must not change when the tool moves to the web (v0.22.0)
=======================================================================================

Two kinds of test:

1. With made-up invoices (always run): a snapshot holds the month's figures,
   two snapshots of the same data are identical, a changed master is
   reported by name, and the script never changes the database it reads.

2. With the client's real month (run only on a PC that has it): for every
   data/baseline/figures_YYYY-MM.json written by

       python scripts/snapshot_month.py 2026 9

   the month is worked out again from data/baseline/drivenstyle.db and must
   give the same figures to the paisa. data/ is not in Git, so elsewhere
   this test is skipped. Another folder can be given with DNS_BASELINE_DIR.
"""

import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.data.database import connect
from app.data.masters_repo import RowChange
from app.reports import snapshot as snap
from scripts import snapshot_month
from tests.test_reports import world  # noqa: F401  (fixture: masters + two invoices)

BASELINE = Path(os.environ.get("DNS_BASELINE_DIR", "")
                or Path(__file__).resolve().parent.parent / "data" / "baseline")
SAVED = sorted(BASELINE.glob("figures_*.json")) if BASELINE.is_dir() else []


def test_snapshot_holds_the_month(world):
    repo, inv, inp = world
    figures = snap.snapshot(repo, inv, inp, 2026, 9)
    t = figures["totals"]
    assert figures["month"] == "2026-09" and figures["layout"] == snap.LAYOUT
    assert t["invoices"] == len(figures["invoices"]) > 0
    # The totals are the sum of the invoices, and profit = sales - cost - labour.
    rows = figures["invoices"].values()
    assert t["sales"] == round(sum(r["sales"] for r in rows), 2)
    assert t["labour"] == round(sum(r["labour"] for r in rows), 2)
    assert t["gross_profit"] == round(t["sales"] - t["product_cost"] - t["labour"], 2)
    assert round(sum(figures["labour"].values()), 2) == t["labour"]


def test_same_data_gives_no_differences(world, tmp_path):
    repo, inv, inp = world
    first = snap.snapshot(repo, inv, inp, 2026, 9)
    path = snap.save(first, tmp_path / "figures.json")
    assert snap.differences(snap.load(path), snap.snapshot(repo, inv, inp, 2026, 9)) == []


def test_a_changed_cost_is_reported_by_name(world):
    repo, inv, inp = world
    before = snap.snapshot(repo, inv, inp, 2026, 9)
    # The first product is on an invoice of the month: its cost goes up by Rs. 100.
    product = dict(repo.list_rows("products")[0])
    values = {k: v for k, v in product.items() if k != "id"}
    values["cost_price"] = product["cost_price"] + 100
    repo.save("products", [RowChange(product["id"], values, date(2026, 4, 1))])
    found = snap.differences(before, snap.snapshot(repo, inv, inp, 2026, 9))
    assert any(line.startswith("totals > product_cost: was ") for line in found)
    assert any(line.startswith("invoices > ") for line in found)


def test_other_layout_is_refused(world):
    repo, inv, inp = world
    figures = snap.snapshot(repo, inv, inp, 2026, 9)
    found = snap.differences(dict(figures, layout=0), figures)
    assert len(found) == 1 and "save them again" in found[0]


def test_script_reads_a_copy_only(world, tmp_path):
    """The database handed to the script is byte for byte the same afterwards."""
    repo, _, _ = world
    source = tmp_path / "real.db"
    disk = connect(source)
    repo.conn.backup(disk)
    disk.close()
    before = source.read_bytes()
    out = tmp_path / "baseline"
    assert snapshot_month.main(["2026", "9", "--db", str(source), "--out", str(out)]) == 0
    assert source.read_bytes() == before
    saved = snap.load(out / "figures_2026-09.json")
    assert snap.differences(saved, snapshot_month.figures_from(out / "drivenstyle.db", 2026, 9)) == []
    assert snapshot_month.main(["2026", "8", "--db", str(tmp_path / "none.db")]) == 1


@pytest.mark.skipif(not SAVED, reason="no saved figures in data/baseline "
                    "(python scripts/snapshot_month.py 2026 9)")
@pytest.mark.parametrize("path", SAVED, ids=lambda p: p.stem)
def test_real_month_still_gives_the_saved_figures(path):
    saved = snap.load(path)
    year, month = map(int, saved["month"].split("-"))
    now = snapshot_month.figures_from(BASELINE / snapshot_month.DB_COPY, year, month)
    found = snap.differences(saved, now)
    assert not found, f"{len(found)} figure(s) changed:\n" + "\n".join(found[:40])

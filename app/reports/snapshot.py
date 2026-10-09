"""
snapshot.py - A month's figures as plain numbers, for "before and after" checks (v0.22.0)
=========================================================================================

WHAT THIS MODULE DOES
---------------------
The tool is moving from a Windows program to a web tool (see web/README.md).
The rule for that move is simple: THE FIGURES MUST NOT CHANGE. A month
worked out by the web tool must give exactly the same sales, product cost,
labour, gross profit and incentive as the desktop tool gives today.

To prove that, this module writes down a month's figures in a plain form
(a "snapshot") and compares two snapshots:

    snapshot(masters, invoices, inputs, year, month)  ->  dict
        the month's figures, taken from reports/data.build_month - the same
        calculation every report sheet is written from

    differences(before, after)  ->  list of plain sentences
        every figure that is not the same in the two snapshots; an empty
        list means "nothing changed"

    save(snapshot, path) / load(path)
        the snapshot as a .json text file (readable in Notepad)

WHAT A SNAPSHOT HOLDS
---------------------
    totals      invoices included, invoices left out, lines, sales, product
                cost, labour, gross profit, spot incentive (after rounding
                each executive up to Rs. 10), internal team incentive,
                Rs. 1 labour marker lines ignored and their value
    auto        the automatic indirect costs (4 % / 3 % of product cost)
    indirect    the heads typed on Monthly inputs
    labour      labour by kind of work (Floor mat / Sunfilm / Other)
    executives  spot incentive payable per executive
    invoices    per invoice: date, executive, branch, car, sales, product
                cost, labour, gross profit, incentive, internal incentive,
                package name
    left_out    invoice numbers left out because of an open Scan review issue

Amounts are rounded to 2 decimals (paise), so two snapshots can be compared
exactly. A snapshot of the client's real month holds the CLIENT'S FIGURES:
it is saved under data/ (never committed to Git, see .gitignore).

No Qt code here, and nothing is written to the database.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import __version__
from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import InvoicesRepo
from app.data.masters_repo import MastersRepo
from app.reports.data import LABOUR_GROUPS, build_month, labour_group

# Version of the snapshot's own layout. Raise it only when a figure is added
# or renamed, so an old file is recognised instead of wrongly compared.
LAYOUT = 1


def _r(amount: float) -> float:
    """An amount to the paisa (and never "-0.0", which would not compare equal as text)."""
    return round(float(amount), 2) + 0.0


def snapshot(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
             year: int, month: int) -> dict:
    """The month's figures as a plain dictionary (see the module notes)."""
    data = build_month(masters, invoices, inputs, year, month)

    # Labour by kind of work - the same grouping rule as the Labour sheet and
    # the daily payout app (reports/data.labour_group).
    labour = {group: 0.0 for group in LABOUR_GROUPS}
    for line in data.lines:
        if line.labour:
            labour[labour_group(line.product)] += line.labour

    return {
        "layout": LAYOUT,
        "tool_version": __version__,
        "month": f"{year:04d}-{month:02d}",
        "totals": {
            "invoices": len(data.invoices),
            "left_out": len(data.left_out),
            "lines": len(data.lines),
            "sales": _r(data.sales),
            "product_cost": _r(sum(i.cost for i in data.invoices)),
            "labour": _r(sum(i.labour for i in data.invoices)),
            "gross_profit": _r(data.gross_profit),
            "spot_incentive": _r(data.incentive_payable),
            "internal_incentive": _r(data.internal_incentive),
            "marker_lines": data.marker_lines,
            "marker_value": _r(data.marker_value),
        },
        "auto": {head: _r(amount) for head, _, amount in data.auto_indirect},
        "indirect": {head: _r(amount) for head, amount in data.indirect_costs},
        "labour": {group: _r(amount) for group, amount in labour.items()},
        "executives": {name: _r(amount)
                       for name, amount in sorted(data.incentive_by_executive.items())},
        "invoices": {
            i.invoice_no: {
                "date": i.invoice_date.isoformat(),
                "executive": i.executive,
                "branch": i.branch,
                "car": i.car,
                "sales": _r(i.sales),
                "product_cost": _r(i.cost),
                "labour": _r(i.labour),
                "gross_profit": _r(i.gross_profit),
                "incentive": _r(i.incentive_payable),
                "internal_incentive": _r(i.internal_incentive),
                "package": i.package.package if i.package else "",
            }
            for i in sorted(data.invoices, key=lambda i: i.invoice_no)
        },
        "left_out": sorted(l.invoice_no for l in data.left_out),
    }


def _walk(before, after, where: str, out: list[str]) -> None:
    """Compare two values of a snapshot, going into dictionaries."""
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after), key=str):
            label = f"{where} > {key}" if where else str(key)
            if key not in after:
                out.append(f"{label}: was there before, missing now")
            elif key not in before:
                out.append(f"{label}: new (was not there before)")
            else:
                _walk(before[key], after[key], label, out)
    elif before != after:
        out.append(f"{where}: was {before!r}, now {after!r}")


def differences(before: dict, after: dict) -> list[str]:
    """
    Every figure that differs between two snapshots, as plain sentences
    ("invoices > DNS-207-2627 > labour: was 500.0, now 600.0"). The tool
    version is not compared - it is expected to move on.
    """
    if before.get("layout") != after.get("layout"):
        return [f"The saved figures are in layout {before.get('layout')}, this version "
                f"of the tool writes layout {after.get('layout')}: save them again "
                "(python scripts/snapshot_month.py ...)."]
    skip = {"tool_version"}
    out: list[str] = []
    _walk({k: v for k, v in before.items() if k not in skip},
          {k: v for k, v in after.items() if k not in skip}, "", out)
    return out


def save(figures: dict, path: str | Path) -> Path:
    """Write a snapshot as a .json text file (sorted, so two files compare line by line)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(figures, indent=2, sort_keys=True, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load(path: str | Path) -> dict:
    """Read a snapshot written by save()."""
    return json.loads(Path(path).read_text(encoding="utf-8"))

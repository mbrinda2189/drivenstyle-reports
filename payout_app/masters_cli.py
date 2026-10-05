"""
masters_cli.py - Create the masters Google Sheet, and check it
==============================================================

WHAT THIS MODULE DOES
---------------------
Until the payout app has its own screens, the masters sheet is set up and
checked with these commands, run from the project folder:

    python -m payout_app.masters_cli create
        Signs in to Google (sign in as the account that should OWN the
        sheet - automation.drivenstyle@gmail.com), makes a new Google Sheet
        "Drive N Style Masters" and fills it with the masters that are in
        the monthly tool on this PC now, including every dated price,
        labour charge and incentive. It then reads the new sheet back and
        checks it, remembers it on this PC and prints its link.
        It refuses to make a second sheet when one is already remembered;
        add --new to make another one on purpose.

    python -m payout_app.masters_cli check
        Reads the remembered sheet and runs every check. Prints either the
        number of records per tab, or the list of problems with their tab
        and row number. Nothing in the monthly tool is changed.

    python -m payout_app.masters_cli use <link or id>
        Remember an existing masters sheet on this PC (for a second PC).

    python -m payout_app.masters_cli preview
        No Google needed: shows how many rows each tab WOULD get from the
        masters on this PC, and checks them the same way.

The monthly tool keeps using its own masters for now (decided 05-10-2026):
the sheet is for the daily payout app until it has proved itself.
After `create`, share the sheet from Google Sheets itself: the client as
Editor, the staff as Viewer.
"""

from __future__ import annotations

import argparse
import sys

from app.data.database import connect
from app.data.inputs_repo import InputsRepo
from app.data.masters_repo import MastersRepo
from payout_app import masters_sheet, settings
from payout_app.google_api import GoogleError, SheetsClient, sign_in


def _print_result(result: masters_sheet.LoadResult) -> int:
    """Show a LoadResult; returns the exit code (0 = sheet is fine)."""
    for note in result.notes:
        print(f"  note: {note}")
    if result.problems:
        print(f"\n{len(result.problems)} problem(s) - nothing from the sheet "
              "will be used until they are fixed:")
        for problem in result.problems:
            print(f"  - {problem}")
        return 1
    print("The sheet is fine." + (" (last good copy)" if result.from_cache else ""))
    for tab, count in result.counts.items():
        print(f"  {tab:<18} {count:>5} records")
    for key, value in result.settings.items():
        print(f"  {key:<24} {value:g} %")
    return 0


def _local_tabs() -> dict[str, list[list]]:
    """The monthly tool's masters on this PC, as sheet rows."""
    masters = MastersRepo(connect())
    return masters_sheet.to_tabs(masters, InputsRepo(masters))


def cmd_preview(_args) -> int:
    tabs = _local_tabs()
    for name, rows in tabs.items():
        print(f"  {name:<18} {max(len(rows) - 1, 0):>5} rows")
    return _print_result(masters_sheet.load_tabs(tabs))


def cmd_create(args) -> int:
    if settings.get("masters_sheet_id") and not args.new:
        print("A masters sheet is already remembered on this PC:\n  "
              + settings.get("masters_sheet_url")
              + "\nUse 'check' to check it, or add --new to make another one.")
        return 1
    tabs = _local_tabs()
    before = masters_sheet.load_tabs(tabs)
    if not before.ok:
        print("The masters on this PC do not pass the sheet's checks, so no "
              "sheet was made:")
        return _print_result(before)
    client = SheetsClient(sign_in())
    sheet_id, url = client.create(masters_sheet.SHEET_TITLE, tabs,
                                  masters_sheet.tab_layout())
    settings.save(masters_sheet_id=sheet_id, masters_sheet_url=url)
    print(f"Created “{masters_sheet.SHEET_TITLE}”:\n  {url}\n")
    return _print_result(masters_sheet.refresh(lambda: client.read_tabs(sheet_id)))


def cmd_check(_args) -> int:
    sheet_id = settings.get("masters_sheet_id")
    if not sheet_id:
        print("No masters sheet is remembered on this PC yet. Run 'create', "
              "or 'use <link>' for an existing sheet.")
        return 1

    def read():
        return SheetsClient(sign_in()).read_tabs(sheet_id)

    return _print_result(masters_sheet.refresh(read))


def cmd_use(args) -> int:
    sheet_id = settings.sheet_id_from(args.sheet)
    if not sheet_id:
        print("That does not look like a Google Sheet link or id.")
        return 1
    client = SheetsClient(sign_in())
    title = client.title(sheet_id)
    settings.save(masters_sheet_id=sheet_id,
                  masters_sheet_url=f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    print(f"This PC now uses the sheet “{title}”.")
    return _print_result(masters_sheet.refresh(lambda: client.read_tabs(sheet_id)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m payout_app.masters_cli",
        description="Create and check the Drive N Style masters Google Sheet.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="make the sheet from this PC's masters")
    create.add_argument("--new", action="store_true",
                        help="make another sheet even if one is remembered")
    create.set_defaults(run=cmd_create)
    sub.add_parser("check", help="read the sheet and check it").set_defaults(run=cmd_check)
    use = sub.add_parser("use", help="remember an existing sheet on this PC")
    use.add_argument("sheet", help="the sheet's link or id")
    use.set_defaults(run=cmd_use)
    sub.add_parser("preview", help="check this PC's masters without Google"
                   ).set_defaults(run=cmd_preview)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except GoogleError as exc:
        print(f"\n{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

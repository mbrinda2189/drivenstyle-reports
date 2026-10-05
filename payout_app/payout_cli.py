"""
payout_cli.py - Scan the invoice folder and post to the payout register
=======================================================================

WHAT THIS MODULE DOES
---------------------
Until the payout app has its own screens, the daily work is done with
these commands, run from the project folder:

    python -m payout_app.payout_cli create-register
        Makes the Google Sheet "Drive N Style Payout Register" (sign in as
        the account that should own it) and remembers it on this PC.
        Share it afterwards: staff and client as Editor.

    python -m payout_app.payout_cli use-register <link or id>
        Remember an existing register on this PC (for a second PC).

    python -m payout_app.payout_cli scan "<folder of invoice PDFs>"
        The daily run:
          1. reads the masters sheet and checks it (stops on any mistake);
          2. reads the register and puts back any calculated cell that was
             changed by hand;
          3. reads every PDF in the folder, works out labour and incentive;
          4. posts the new lines, records invoices that need review, and
             prints the tally: files = posted + already posted + ...
        Options:
          --dry-run          show what WOULD be posted; write nothing
          --from dd-mm-yyyy  leave invoices dated before this alone (the
                             register starts at go-live, with no back-posting)

    python -m payout_app.payout_cli status
        Pending and paid totals per payee, from the register.

Running `scan` twice is safe: an invoice already posted is never posted or
calculated again (see register.py, POSTING RULES).
"""

from __future__ import annotations

import argparse
import sys
from app.utils import format_inr
from payout_app import register, service, settings
from payout_app.google_api import GoogleError, SheetsClient, sign_in
from payout_app.masters_sheet import parse_sheet_date


def _register_id() -> str:
    sheet_id = settings.get("register_sheet_id")
    if not sheet_id:
        raise GoogleError("No payout register is remembered on this PC yet. Run "
                          "'create-register', or 'use-register <link>'.")
    return sheet_id


def cmd_create_register(args) -> int:
    if settings.get("register_sheet_id") and not args.new:
        print("A payout register is already remembered on this PC:\n  "
              + settings.get("register_sheet_url")
              + "\nAdd --new to make another one on purpose.")
        return 1
    client = SheetsClient(sign_in())
    sheet_id, url = client.create(register.SHEET_TITLE, register.new_register_tabs(),
                                  register.register_layout())
    client.write_formulas(sheet_id, register.SUMMARY, register.summary_formulas())
    settings.save(register_sheet_id=sheet_id, register_sheet_url=url)
    print(f"Created “{register.SHEET_TITLE}”:\n  {url}")
    return 0


def cmd_use_register(args) -> int:
    sheet_id = settings.sheet_id_from(args.sheet)
    if not sheet_id:
        print("That does not look like a Google Sheet link or id.")
        return 1
    client = SheetsClient(sign_in())
    tabs = client.tab_names(sheet_id)
    missing = [t for t in (register.PAYOUTS, register.INVOICES, register.MATCHES,
                           register.LOG) if t not in tabs]
    if missing:
        print(f"“{client.title(sheet_id)}” is not a payout register: it has no "
              f"tab {', '.join(missing)}.")
        return 1
    settings.save(register_sheet_id=sheet_id,
                  register_sheet_url=f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    print(f"This PC now uses the register “{client.title(sheet_id)}”.")
    return 0


def _show(title: str, items: list[str]) -> None:
    if items:
        print(f"\n{title}")
        for item in items:
            print(f"  - {item}")


def cmd_scan(args) -> int:
    start = None
    if args.start:
        try:
            start = parse_sheet_date(args.start)
        except Exception:
            print(f"--from “{args.start}” is not a date (use dd-mm-yyyy).")
            return 1
    print(f"Reading the PDF files in {args.folder} ...")
    report = service.scan(service.Session(), args.folder, args.dry_run, start)
    dry = " (dry run - nothing is written)" if report.dry_run else ""
    _show("Notes:", report.notes)
    if report.stopped:
        _show(report.stopped, report.problems)
        return 1
    _show(f"Calculated cells changed by hand; restored{dry}:", report.restored)
    _show("Please check:", report.warnings)
    print(f"\nPosted{dry}: {len(report.posted)} new line(s), "
          f"{format_inr(report.posted_total)}")
    for line in report.posted:
        print(f"  {line['line_id']:<24} {line['type']:<15} "
              f"{(line['payee'] or '-'):<28} {format_inr(line['amount']):>12}")
    if report.corrected:
        print(f"{report.corrected} existing line(s) corrected (re-issued invoices).")
    _show(f"In review ({len(report.review)}) - not posted until fixed:",
          [f"{r.invoice_no}: {' '.join(r.reasons)}" for r in report.review])
    _show("Not used:", [f"{r.file_name}: {' '.join(r.reasons)}" for r in report.not_used])
    t = report.tally
    parts = [f"{t[k]} {k}" for k in ("posted", "already posted", "re-issued", "in review",
                                     "cancelled", "not used", "before start date") if t[k]]
    print(f"\nTally: {t['files']} file(s) = " + (" + ".join(parts) or "0"))
    return 0


def cmd_status(_args) -> int:
    client = SheetsClient(sign_in())
    rows = client.read_tabs(_register_id()).get(register.PAYOUTS) or []
    totals = register.pending_by_payee(rows)
    if not totals:
        print("No payout lines in the register yet.")
        return 0
    print(f"{'Type':<16}{'Payee':<30}{'Pending':>14}{'Paid':>14}")
    for kind, payee, pending, paid in totals:
        print(f"{kind:<16}{(payee or '-'):<30}{format_inr(pending):>14}{format_inr(paid):>14}")
    print(f"{'Total':<46}{format_inr(sum(t[2] for t in totals)):>14}"
          f"{format_inr(sum(t[3] for t in totals)):>14}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m payout_app.payout_cli",
        description="Daily labour / incentive payouts for Drive N Style.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-register", help="make the payout register sheet")
    create.add_argument("--new", action="store_true")
    create.set_defaults(run=cmd_create_register)
    use = sub.add_parser("use-register", help="remember an existing register on this PC")
    use.add_argument("sheet")
    use.set_defaults(run=cmd_use_register)
    scan = sub.add_parser("scan", help="read the invoice folder and post the payouts")
    scan.add_argument("folder", help="folder holding the invoice PDFs")
    scan.add_argument("--dry-run", action="store_true",
                      help="show what would be posted; write nothing")
    scan.add_argument("--from", dest="start", default="",
                      help="ignore invoices dated before this (dd-mm-yyyy)")
    scan.set_defaults(run=cmd_scan)
    sub.add_parser("status", help="pending and paid totals").set_defaults(run=cmd_status)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except GoogleError as exc:
        print(f"\n{exc}")
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())

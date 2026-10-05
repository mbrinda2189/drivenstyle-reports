"""
payout_app - Drive N Style daily labour / incentive payout app
==============================================================

WHAT THIS PACKAGE IS
--------------------
A SEPARATE small app for the client's staff (plan approved by Brinda on
05-10-2026). Every day the staff save the new invoice PDFs in a folder;
this app reads them, works out the labour charge and the spot incentive
with the SAME masters and rules as the monthly reports tool, and posts the
result to a shared Google Sheet where the staff record that each amount
was paid, with proof.

It lives in the same repository as the monthly tool on purpose: the
invoice reader, the matching rules and the incentive calculation are in
`app/data/` and `app/reports/` (no screen code there) and are imported
from here, so a rule changed once applies to both apps and the daily
payouts always add up to the monthly report.

THE MODULES (built step by step)
--------------------------------
    masters_sheet.py   The masters as a Google Sheet: the layout of the
                       tabs, writing the current masters into that layout,
                       and reading the sheet back with every check
                       ("validate on read"). No Google code - only rows.
    google_api.py      Signing in to Google and the few Sheets calls the
                       app needs (create a sheet, read its tabs).
    settings.py        Small settings file on each PC (which sheet to use).
    masters_cli.py     Commands to create the masters sheet and to check it:
                           python -m payout_app.masters_cli create
                           python -m payout_app.masters_cli check
    engine.py          Invoice PDFs -> payout lines (labour, spot incentive,
                       internal team) with their workings, or the reasons
                       an invoice needs review. Uses the monthly tool's
                       own matching and valuation code.
    register.py        The payout register sheet: layout, what a scan has
                       to write (post once, in review, re-issued invoices),
                       and finding calculated cells changed by hand.
    payout_cli.py      The daily commands:
                           python -m payout_app.payout_cli create-register
                           python -m payout_app.payout_cli scan "<folder>"
                           python -m payout_app.payout_cli status
    service.py         The app's actions in one place - the daily scan,
                       saving a match, cancelling an invoice - used by
                       both the screens and the commands.
    slip.py            The payout slip (to pay / paid on a day), as data
                       and as a printable page.
    ui/                The screens (PySide6):  python -m payout_app
                       Scan, Review, Payouts, History and Set-up.
Still to come: the installer for the staff PCs.
"""

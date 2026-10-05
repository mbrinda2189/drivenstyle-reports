"""
test_invoice_pdfs.py - Read real invoice PDFs (only when provided)
=================================================================

Client invoices are never stored in Git. To run these tests, put sample
PDFs in a folder and point DNS_SAMPLE_INVOICES at it:

    $env:DNS_SAMPLE_INVOICES = "C:\\path\\to\\sample invoices"   (PowerShell)
    python -m pytest tests/test_invoice_pdfs.py

Every PDF in the folder must read without error, and its printed figures
must agree with each other (line amounts = Sub Total, and the totals
arithmetic). Without the variable, the tests are skipped.

v0.13.0 - PDFs against Zoho's export. The daily payout app reads PDFs and
the monthly reports read the export, so both must give the same figures.
Point DNS_SAMPLE_EXPORT at the Invoice.csv of the same period as well:

    $env:DNS_SAMPLE_EXPORT = "C:\\path\\to\\Invoice.csv"

For every invoice found in both, the item names, quantities and line
amounts must be the same, the totals must agree, and the amount billed per
line (after discount, with GST) must agree within 5 paise. The salesperson
is NOT compared: an invoice edited in Zoho after its PDF was saved shows
the newer name in the export.
"""

import os
from pathlib import Path

import pytest

from app.data.invoice_reader import read_invoice
from app.data.invoices_repo import billed_lines, check_totals

FOLDER = os.environ.get("DNS_SAMPLE_INVOICES", "")
PDFS = sorted(Path(FOLDER).glob("*.pdf")) if FOLDER else []

EXPORT = os.environ.get("DNS_SAMPLE_EXPORT", "")

pytestmark = pytest.mark.skipif(not PDFS, reason="DNS_SAMPLE_INVOICES not set")


@pytest.mark.parametrize("pdf", PDFS, ids=[p.name for p in PDFS])
def test_sample_invoice_reads_and_adds_up(pdf):
    inv = read_invoice(pdf)
    assert inv.invoice_no and inv.invoice_date and inv.lines
    assert all(l.description and l.amount >= 0 for l in inv.lines)
    assert check_totals(inv) == []


def _same(a: str, b: str) -> bool:
    """Compare two printed texts ignoring capitals and extra spaces."""
    return " ".join(str(a or "").split()).lower() == " ".join(str(b or "").split()).lower()


@pytest.mark.skipif(not EXPORT, reason="DNS_SAMPLE_EXPORT not set")
def test_pdfs_agree_with_zoho_export():
    from app.data.invoice_export import read_export

    export = {i.invoice_no: i for i in read_export(EXPORT).invoices}
    compared, problems = 0, []
    for pdf in PDFS:
        p = read_invoice(pdf)
        e = export.get(p.invoice_no)
        if e is None:
            continue                               # not in this export
        compared += 1
        no = p.invoice_no
        if p.invoice_date != e.invoice_date:
            problems.append(f"{no}: date {p.invoice_date} / {e.invoice_date}")
        for name in ("total", "discount", "rounding"):
            if abs(getattr(p, name) - getattr(e, name)) > 0.011:
                problems.append(f"{no}: {name} {getattr(p, name)} / {getattr(e, name)}")
        if len(p.lines) != len(e.lines):
            problems.append(f"{no}: {len(p.lines)} lines / {len(e.lines)}")
            continue
        for lp, le, bp, be in zip(p.lines, e.lines, billed_lines(p), billed_lines(e)):
            if not _same(lp.description, le.description):
                problems.append(f"{no}: item “{lp.description}” / “{le.description}”")
            if abs(lp.qty - le.qty) > 1e-6 or abs(lp.amount - le.amount) > 0.011:
                problems.append(f"{no}: {lp.description}: qty / amount differ")
            if abs(bp - be) > 0.05:
                problems.append(f"{no}: {lp.description}: billed {bp} / {be}")
    assert compared, "no invoice of the PDF folder is in the export"
    assert problems == []

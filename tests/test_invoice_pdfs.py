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
"""

import os
from pathlib import Path

import pytest

from app.data.invoice_reader import read_invoice
from app.data.invoices_repo import check_totals

FOLDER = os.environ.get("DNS_SAMPLE_INVOICES", "")
PDFS = sorted(Path(FOLDER).glob("*.pdf")) if FOLDER else []

pytestmark = pytest.mark.skipif(not PDFS, reason="DNS_SAMPLE_INVOICES not set")


@pytest.mark.parametrize("pdf", PDFS, ids=[p.name for p in PDFS])
def test_sample_invoice_reads_and_adds_up(pdf):
    inv = read_invoice(pdf)
    assert inv.invoice_no and inv.invoice_date and inv.lines
    assert all(l.description and l.amount >= 0 for l in inv.lines)
    assert check_totals(inv) == []
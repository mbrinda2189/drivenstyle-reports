"""
test_invoices.py - Tests for invoice amounts, matching, issues and fixes
========================================================================

Real client invoices are never committed to Git, so these tests build
invoices in code (ParsedInvoice) with the same figures as the Carkrafts
samples. test_invoice_pdfs.py reads real PDFs when a sample folder is
provided.
"""

from datetime import date

import pytest

from app.data.invoice_reader import InvoiceLine, ParsedInvoice, parse_amount, parse_date
from app.data.invoices_repo import (
    FileResult, InvoicesRepo, allocate_lines, check_totals, is_labour_marker,
    split_salesperson, vehicle_key)
from app.data.masters_repo import RowChange


# --- helpers --------------------------------------------------------------
def inv_0753(**changes) -> ParsedInvoice:
    """DNS26-GST-0753: GST invoice, 4 lines, Rs. 1 discount, rounding 0.20."""
    inv = ParsedInvoice(
        file_name="Invoice_DNS26-GST-0753.pdf", gstin="33AAOFD7793F1Z2",
        invoice_no="DNS26-GST-0753", invoice_date=date(2026, 9, 5),
        salesperson="Edhayan- ooty", vehicle="I20", customer="SURAJ 440464",
        lines=[InvoiceLine(1, "I20 - PVC Full Floor Mat + Labour Extra", "39181090", 1, "", 3300, 3300),
               InvoiceLine(2, "Labour Charges for PVC/MLF/Luxury Floor Mat (i20/ NIOS/ Aura/ Verna)",
                           "39181090", 1, "", 1, 1),
               InvoiceLine(3, "Underbody Coating - 5 Seater", "870899", 1, "", 3500, 3500),
               InvoiceLine(4, "Silencer Coating - All Cars", "870892", 1, "", 1500, 1500)],
        sub_total=8301, discount=1, discount_base=7034.72,
        taxes={"CGST 9%": 633.04, "SGST 9%": 633.04}, tax_rate=18.0,
        rounding=0.20, total=8300, payment_made=8300)
    for k, v in changes.items():
        setattr(inv, k, v)
    return inv


def inv_226() -> ParsedInvoice:
    """DNS-226-2627: no GST shown, Rs. 1,903 discount."""
    amounts = [7000, 1, 8000, 1, 2100, 750, 3500, 1, 550]
    names = ["Sunfilm - Nano Ceramic - Front (SK)", "Labour Charges for Sunfilm - Front",
             "Sunfilm - Nano Ceramic - Side and Rear (SK)",
             "Labour Charges for Sunfilm - Side and Rear", "Horn",
             "Punch.EV Mudflap - Techno", "PUNCH - PVC Full Floor Mat + Labour Extra",
             "Labour Charges for PVC/MLF/Luxury Floor Mat (i20/ NIOS/ Aura/ Verna)",
             "Punch EV Number Plate Frame"]
    return ParsedInvoice(
        file_name="Invoice_DNS-226-2627.pdf", gstin="33AAOFD7793F1Z2",
        invoice_no="DNS-226-2627", invoice_date=date(2026, 9, 4),
        salesperson="Nandha Kumar", vehicle="PUNCH.EV",
        lines=[InvoiceLine(i + 1, n, "", 1, "", a, a) for i, (n, a) in enumerate(zip(names, amounts))],
        sub_total=21903, discount=1903, discount_base=21903, total=20000)


@pytest.fixture
def irepo(repo):
    return InvoicesRepo(repo)


def add_exec(repo, name, phone, branch):
    repo.save("executives", [RowChange(None, dict(name=name, phone=phone, branch=branch,
                                                  active=True))])


def add_product(repo, name, labour=False):
    repo.save("products", [RowChange(None, dict(
        sku="", name=name, hsn_sac="", category="Product", incentive_group="",
        selling_price=0, cost_price=0, has_labour=labour, labour_charge=0, active=True))])


# --- small helpers -----------------------------------------------------------
@pytest.mark.parametrize("text, value", [
    ("₹8,300.00", 8300.0), ("(-) 1,903.00", 1903.0), ("0.20", 0.2), ("abc", None)])
def test_parse_amount(text, value):
    assert parse_amount(text) == value


def test_parse_date_is_day_first():
    assert parse_date(": 04/09/2026") == date(2026, 9, 4)


@pytest.mark.parametrize("printed, parts", [
    ("Kumaran - HO", ("Kumaran", "HO")), ("Edhayan- ooty", ("Edhayan", "ooty")),
    ("Nandha Kumar", ("Nandha Kumar", "")), ("", ("", ""))])
def test_split_salesperson(printed, parts):
    assert split_salesperson(printed) == parts


def test_vehicle_key_ignores_punctuation():
    assert vehicle_key("PUNCH.EV") == vehicle_key("Punch EV") == "punchev"


def test_labour_marker_lines():
    assert is_labour_marker("Labour Charges for Sunfilm - Front")
    assert not is_labour_marker("I20 - PVC Full Floor Mat + Labour Extra")


# --- per-line amounts and checks ------------------------------------------------
def test_gst_invoice_split_matches_printed_figures():
    inv = inv_0753()
    shares = allocate_lines([l.amount for l in inv.lines], 18.0, 1.0,
                            inv.tax_total, inv.total, inv.rounding)
    assert round(sum(s["before_tax"] for s in shares), 2) == pytest.approx(7034.75, abs=0.05)
    assert round(sum(s["discount"] for s in shares), 2) == pytest.approx(1.0, abs=0.02)
    assert round(sum(s["gst"] for s in shares), 2) == pytest.approx(1266.08, abs=0.05)


def test_non_gst_invoice_whole_amount_is_sales():
    inv = inv_226()
    shares = allocate_lines([l.amount for l in inv.lines], 0.0, 1903.0, 0, 20000, 0)
    assert sum(s["gst"] for s in shares) == 0
    assert round(sum(s["net"] for s in shares), 2) == pytest.approx(20000, abs=0.05)


def test_totals_that_agree_raise_nothing():
    assert check_totals(inv_0753()) == []
    assert check_totals(inv_226()) == []


def test_totals_that_disagree_are_reported():
    bad = inv_0753(total=8400)
    assert "Total is 8,400.00" in check_totals(bad)[0]
    bad = inv_226()
    bad.lines[0].amount = 700          # misread line
    assert "Sub Total" in check_totals(bad)[0]


# --- storing and issues -------------------------------------------------------------
def scan(irepo, *invoices):
    return irepo.store_scan(2026, 9, "folder", [
        FileResult(i.file_name, "read", "", i) for i in invoices])


def test_store_and_replace_a_month(irepo):
    assert scan(irepo, inv_0753(), inv_226())["read"] == 2
    assert scan(irepo, inv_226())["read"] == 1                  # re-scan replaces
    assert [i["invoice_no"] for i in irepo.invoices(2026, 9)] == ["DNS-226-2627"]


def test_duplicate_invoice_number_uses_first_file(irepo):
    a, b = inv_226(), inv_226()
    b.file_name = "copy.pdf"
    counts = scan(irepo, a, b)
    assert counts == {"read": 1, "skipped": 1, "error": 0}
    skipped = [f for f in irepo.scan_files(2026, 9) if f["status"] == "skipped"]
    assert "also in Invoice_DNS-226-2627.pdf" in skipped[0]["reason"]


def test_salesperson_by_name_and_branch(repo, irepo):
    add_exec(repo, "Edhayan", "9000000001", "Ooty")
    add_exec(repo, "Edhayan", "9000000002", "HO")
    scan(irepo, inv_0753())
    [inv] = irepo.invoices(2026, 9)
    assert inv["executive"] == "Edhayan – Ooty"


def test_salesperson_issues_none_or_several(repo, irepo):
    add_exec(repo, "Nandha Kumar", "9000000001", "HO")
    add_exec(repo, "Nandha Kumar", "9000000002", "Ooty")
    scan(irepo, inv_226())
    [issue] = [i for i in irepo.issues(2026, 9) if i.kind == "salesperson"]
    assert "more than one" in issue.message and len(issue.options) == 2


def test_salesperson_fix_for_one_or_all_invoices(repo, irepo):
    add_exec(repo, "Nandha Kumar", "9000000001", "HO")
    add_exec(repo, "Nandha Kumar", "9000000002", "Ooty")
    scan(irepo, inv_226())
    eid = repo.list_rows("executives")[0]["id"]
    irepo.set_salesperson("DNS-226-2627", "Nandha Kumar", eid, all_invoices=False)
    assert not [i for i in irepo.issues(2026, 9) if i.kind == "salesperson"]
    assert irepo.conn.execute("SELECT COUNT(*) FROM match_aliases").fetchone()[0] == 0
    log = repo.audit_entries(master="scan")
    assert log[0]["record"] == "Invoice DNS-226-2627" and log[0]["field"] == "Salesperson"


def test_product_issues_are_grouped_and_fixed_once(repo, irepo):
    second = inv_0753(invoice_no="DNS26-GST-0999", file_name="b.pdf")
    scan(irepo, inv_0753(), second)
    underbody = [i for i in irepo.issues(2026, 9)
                 if i.kind == "product" and "Underbody" in i.printed]
    assert len(underbody) == 1 and len(underbody[0].invoices) == 2
    add_product(repo, "Underbody Coating 5 Seater (UC-5S)")
    pid = repo.list_rows("products")[0]["id"]
    irepo.map_product("Underbody Coating - 5 Seater", pid)
    assert not [i for i in irepo.issues(2026, 9) if "Underbody" in i.printed]


def test_adding_the_product_to_the_master_clears_the_issue(repo, irepo):
    scan(irepo, inv_0753())
    add_product(repo, "silencer coating - all cars")
    assert not [i for i in irepo.issues(2026, 9) if "Silencer" in i.printed]


def test_car_matching_and_fix(repo, irepo):
    repo.save("cars", [RowChange(None, dict(make="Tata", model="Punch EV", segment="", active=True))])
    scan(irepo, inv_226(), inv_0753())
    cars = [i for i in irepo.issues(2026, 9) if i.kind == "car"]
    assert [i.invoices for i in cars] == [["DNS26-GST-0753"]]         # I20 not in master
    repo.save("cars", [RowChange(None, dict(make="Hyundai", model="i20 N Line", segment="", active=True))])
    cid = [c["id"] for c in repo.list_rows("cars") if c["make"] == "Hyundai"][0]
    irepo.set_car("DNS26-GST-0753", "I20", cid, all_invoices=True)
    assert not [i for i in irepo.issues(2026, 9) if i.kind == "car"]


def test_labour_marker_without_labour_product_is_not_flagged(repo, irepo):
    """v0.6.3: Rs. 1 labour lines are ignored, so they never raise an issue."""
    for name in ("I20 - PVC Full Floor Mat + Labour Extra", "Underbody Coating - 5 Seater",
                 "Silencer Coating - All Cars"):
        add_product(repo, name, labour=False)
    scan(irepo, inv_0753())
    assert not [i for i in irepo.issues(2026, 9) if i.kind == "labour"]


def test_no_labour_issue_when_a_product_has_labour(repo, irepo):
    add_product(repo, "I20 - PVC Full Floor Mat + Labour Extra", labour=True)
    add_product(repo, "Underbody Coating - 5 Seater")
    add_product(repo, "Silencer Coating - All Cars")
    scan(irepo, inv_0753())
    assert not [i for i in irepo.issues(2026, 9) if i.kind == "labour"]


def test_totals_issue_and_acknowledge(irepo):
    scan(irepo, inv_0753(total=8400))
    [t] = [i for i in irepo.issues(2026, 9) if i.kind == "totals"]
    irepo.acknowledge(t.key, "totals")
    assert not [i for i in irepo.issues(2026, 9) if i.kind == "totals"]


def test_fixes_survive_a_rescan(repo, irepo):
    add_exec(repo, "Edhayan", "9000000001", "Coimbatore")
    scan(irepo, inv_0753())
    eid = repo.list_rows("executives")[0]["id"]
    irepo.set_salesperson("DNS26-GST-0753", "Edhayan- ooty", eid, all_invoices=True)
    scan(irepo, inv_0753())
    assert not [i for i in irepo.issues(2026, 9) if i.kind == "salesperson"]


def test_skipped_files_are_listed(irepo):
    irepo.store_scan(2026, 9, "f", [FileResult("x.pdf", "error", "Could not be read: no item table found.")])
    [f] = irepo.issues(2026, 9)
    assert f.kind == "file" and f.status == "skipped"


def test_unknown_salesperson_is_one_row_for_all_its_invoices(repo, irepo):
    """v0.6.1: one row per printed name, fixed for every invoice at once."""
    second = inv_226()
    second.invoice_no, second.file_name = "DNS-227-2627", "Invoice_DNS-227-2627.pdf"
    irepo.store_scan(2026, 9, "folder", [FileResult(i.file_name, "read", "", i)
                                         for i in (inv_226(), second)])
    [issue] = [i for i in irepo.issues(2026, 9) if i.kind == "salesperson"]
    assert issue.grouped and issue.invoices == ["DNS-226-2627", "DNS-227-2627"]
    assert issue.key == "name:nandha kumar" and "(on 2 invoices)" in issue.message
    add_exec(repo, "Nandhakumar", "9876543210", "HO")
    eid = repo.list_rows("executives")[0]["id"]
    irepo.set_salesperson(issue.key, issue.printed, eid, all_invoices=True)
    assert not [i for i in irepo.issues(2026, 9) if i.kind == "salesperson"]


def test_ambiguous_salesperson_stays_one_row_per_invoice(repo, irepo):
    second = inv_226()
    second.invoice_no, second.file_name = "DNS-227-2627", "Invoice_DNS-227-2627.pdf"
    add_exec(repo, "Nandha Kumar", "9876543210", "HO")
    add_exec(repo, "Nandha Kumar", "9876543211", "Ooty")
    irepo.store_scan(2026, 9, "folder", [FileResult(i.file_name, "read", "", i)
                                         for i in (inv_226(), second)])
    rows = [i for i in irepo.issues(2026, 9) if i.kind == "salesperson"]
    assert [i.key for i in rows] == ["DNS-226-2627", "DNS-227-2627"]
    assert not any(i.grouped for i in rows)

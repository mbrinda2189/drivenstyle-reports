"""
test_payout_engine.py - Payout lines, the register's posting rules and checks
=============================================================================

Payout app, v0.15.0. Nothing here needs Google or real PDFs: invoices are
built in code (the same September samples as test_invoices.py), the masters
come from a sheet built in code, and the register is a pair of row lists.

What is checked:
* labour, spot incentive (with discount rule, package, "gets incentive =
  No", "Others") and internal team lines, with their workings;
* the daily lines add up to the monthly tool's own figures;
* an invoice is posted once; in-review invoices are retried; a re-issued
  invoice corrects unpaid lines and adds adjustment lines for paid ones;
* a calculated cell changed by hand is found and put back.
"""

from datetime import date, datetime

import pytest

from app.data.inputs_repo import InputsRepo
from app.data.invoice_reader import InvoiceLine, ParsedInvoice
from app.data.masters_repo import RowChange
from payout_app import engine, masters_sheet as ms, register as rg
from payout_app.google_api import format_requests
from tests.test_invoices import inv_0753, inv_226, inv_237

NOW = datetime(2026, 10, 5, 18, 0)
WHO = "staff@example.com"


def build_masters(repo, **edits):
    """Masters for the September sample invoices, loaded through the sheet."""
    repo.save("incentives", [
        RowChange(None, dict(name="Underbody", incentive_amount=200, bill_value=3500,
                             active=True), date(2026, 4, 1)),
        RowChange(None, dict(name="Sunfilm", incentive_amount=500, bill_value=7000,
                             active=True), date(2026, 4, 1)),
        RowChange(None, dict(name="Basic Package", incentive_amount=1000,
                             bill_value=15000, active=True), date(2026, 4, 1))])
    repo.save("executives", [
        RowChange(None, dict(name="Edhayan", phone="9000000004", branch="Ooty",
                             gets_incentive=True, active=True)),
        RowChange(None, dict(name="Nandha Kumar", phone="9000000003", branch="HO",
                             gets_incentive=edits.get("nandha_gets", True), active=True)),
        RowChange(None, dict(name="Kumaran", phone="9000000005", branch="HO",
                             gets_incentive=True, active=True))])
    repo.save("cars", [
        RowChange(None, dict(make="Hyundai", model="i20", segment="Hatchback", active=True)),
        RowChange(None, dict(make="Hyundai", model="Exter", segment="Compact SUV", active=True)),
        RowChange(None, dict(make="Tata", model="Punch EV", segment="Compact SUV", active=True))])
    items = [("I20 - PVC Full Floor Mat + Labour Extra", True, 150, "", 0),
             ("Underbody Coating - 5 Seater", False, 0, "Underbody", 0),
             ("Silencer Coating - All Cars", False, 0, "", 0),
             ("Sunfilm - Nano Ceramic - Front (SK)", True, 300, "Sunfilm", 0),
             ("Sunfilm - Nano Ceramic - Side and Rear (SK)", True, 500, "", 0),
             ("Horn", False, 0, "", 0),
             ("Punch.EV Mudflap - Techno", False, 0, "", 0),
             ("PUNCH - PVC Full Floor Mat + Labour Extra", True, 150, "", 0),
             ("Punch EV Number Plate Frame", False, 0, "", 0),
             ("Exter - PVC Full Floor Mat + Labour Extra", True, 175, "", 0),
             ('14" WHEEL CUPS', False, 0, "", 0),
             ("PPF - Gloss - Hatchback", True, 4000, "", 3000)]
    repo.save("products", [RowChange(None, dict(
        sku="", name=n, hsn_sac="", category="Product", incentive_group=g, selling_price=0,
        cost_price=100, has_labour=lab, labour_charge=lc, internal_incentive=internal,
        vehicle_needed=True, active=True), date(2026, 4, 1))
        for n, lab, lc, g, internal in items])
    for package_item, product in edits.get("package", []):
        repo.save("package_items", [RowChange(None, dict(
            package="Basic Package", item=package_item, product=product, active=True))])
    result = ms.load_tabs(ms.to_tabs(repo, InputsRepo(repo)))
    assert result.ok, result.problems
    return result.masters


def files(*invoices):
    return [(inv.file_name, inv, "") for inv in invoices]


def with_vehicle(inv, vehicle, salesperson=None):
    inv.vehicle = vehicle
    if salesperson is not None:
        inv.salesperson = salesperson
    return inv


def september():
    """Three sample invoices, each with a salesperson and car the masters know."""
    return files(with_vehicle(inv_0753(), "I20", "Edhayan - Ooty"),
                 inv_226(),
                 with_vehicle(inv_237(), "EXTER", "Kumaran - HO"))


def lines_of(outcome, invoice_no):
    return {l.type: l for r in outcome.results if r.invoice_no == invoice_no
            for l in r.lines}


# --- the calculation -------------------------------------------------------
def test_labour_incentive_and_workings(repo):
    out = engine.calculate(build_masters(repo), september())
    assert [r.state for r in out.results] == [engine.READY] * 3

    a = lines_of(out, "DNS26-GST-0753")
    assert a[engine.LABOUR].amount == 150 and a[engine.LABOUR].payee == ""
    assert a[engine.LABOUR].working == "I20 - PVC Full Floor Mat + Labour Extra: 150 x 1"
    assert a[engine.LABOUR].line_id == "DNS26-GST-0753-LAB"
    # Underbody billed at its full 3,500 (Rs. 1 discount on the whole invoice)
    assert a[engine.INCENTIVE].payee == "Edhayan"
    assert a[engine.INCENTIVE].amount == pytest.approx(199.98, abs=0.02)
    assert a[engine.INCENTIVE].working.startswith("Underbody: 200 x 1 x min(1, 3,499.")
    assert a[engine.INCENTIVE].working.endswith("/ 3,500)")

    b = lines_of(out, "DNS-226-2627")
    assert b[engine.LABOUR].amount == 300 + 500 + 150
    # Sunfilm front 7,000 on a 21,903 invoice with 1,903 discount
    billed = 7000 * (1 - 1903 / 21903)
    assert b[engine.INCENTIVE].amount == pytest.approx(500 * billed / 7000, abs=0.01)
    assert b[engine.INCENTIVE].payee == "Nandha Kumar"
    assert b[engine.INCENTIVE].car == "Tata Punch EV"

    c = lines_of(out, "DNS-237-2627")           # GST on one line only
    assert list(c) == [engine.LABOUR] and c[engine.LABOUR].amount == 175


def test_daily_lines_add_up_to_the_monthly_figures(repo):
    from app.data.invoices_repo import FileResult, InvoicesRepo
    from app.reports.data import build_month
    masters = build_masters(repo)
    out = engine.calculate(masters, september())
    # the monthly tool's own valuation of the same invoices
    monthly_masters = build_masters_fresh(repo)
    inv = InvoicesRepo(monthly_masters)
    inv.store_scan(2026, 9, "x", [FileResult(f, "read", "", i) for f, i, _ in september()])
    month = build_month(monthly_masters, inv, InputsRepo(monthly_masters), 2026, 9)
    total = lambda kind: sum(l.amount for r in out.results for l in r.lines if l.type == kind)
    assert len(month.invoices) == 3
    assert total(engine.LABOUR) == pytest.approx(sum(i.labour for i in month.invoices))
    assert total(engine.INCENTIVE) == pytest.approx(
        sum(i.incentive_payable for i in month.invoices), abs=0.05)


def test_no_incentive_for_an_executive_marked_no(repo):
    out = engine.calculate(build_masters(repo, nandha_gets=False), september())
    assert engine.INCENTIVE not in lines_of(out, "DNS-226-2627")
    assert engine.LABOUR in lines_of(out, "DNS-226-2627")


def test_package_incentive_replaces_item_incentives(repo):
    masters = build_masters(repo, package=[
        ("Sunfilm", "Sunfilm - Nano Ceramic - Front (SK)"),
        ("Floor mat", "PUNCH - PVC Full Floor Mat + Labour Extra")])
    line = lines_of(engine.calculate(masters, september()), "DNS-226-2627")[engine.INCENTIVE]
    billed = (7000 + 3500) * (1 - 1903 / 21903)
    assert line.amount == pytest.approx(1000 * billed / 15000, abs=0.01)
    assert line.working.startswith("Basic Package (package): 1,000 x min(1, ")


def test_internal_team_line(repo):
    ppf = ParsedInvoice(
        file_name="Invoice_DNS-400-2627.pdf", gstin="33AAOFD7793F1Z2",
        invoice_no="DNS-400-2627", invoice_date=date(2026, 10, 3),
        salesperson="Kumaran - HO", vehicle="I20", customer="RAVI",
        lines=[InvoiceLine(1, "PPF - Gloss - Hatchback", "", 2, "", 60000, 120000)],
        sub_total=120000, total=120000)
    got = lines_of(engine.calculate(build_masters(repo), files(ppf)), "DNS-400-2627")
    assert got[engine.INTERNAL].amount == 6000 and got[engine.INTERNAL].payee == "Internal team"
    assert got[engine.INTERNAL].working == "PPF - Gloss - Hatchback: 3,000 x 2"
    assert got[engine.LABOUR].amount == 8000


def test_review_reasons_and_saved_matches(repo):
    odd = with_vehicle(inv_0753(), "I-20 SPORTZ", "Harish - Ho")
    odd.lines[2].description = "Under body coating 5 seater"
    masters = build_masters(repo)
    out = engine.calculate(masters, files(odd))
    (res,) = out.results
    assert res.state == engine.REVIEW and res.lines == []
    assert any("Under body coating 5 seater" in r for r in res.reasons)
    assert any("Harish - Ho" in r for r in res.reasons)
    assert any("I-20 SPORTZ" in r for r in res.reasons)

    matches = [dict(kind="Item", printed="Under body coating 5 seater",
                    target="Underbody Coating - 5 Seater"),
               dict(kind="Salesperson", printed="Harish - Ho", target="Others"),
               dict(kind="Car", printed="I-20 SPORTZ", target="Hyundai i20"),
               dict(kind="Item", printed="Something", target="Not a product")]
    out = engine.calculate(build_masters_fresh(repo), files(odd), matches)
    (res,) = out.results
    assert res.state == engine.READY
    assert lines_of(out, res.invoice_no)[engine.INCENTIVE].payee == "Others (Harish - Ho)"
    assert out.notes == ["Saved match “Something” → “Not a product” is not used: "
                         "“Not a product” is not in the masters (or fits several records)."]


def build_masters_fresh(repo):
    """A second in-memory copy of the masters already in `repo`."""
    return ms.load_tabs(ms.to_tabs(repo, InputsRepo(repo))).masters


def test_files_that_are_not_used(repo, tmp_path):
    bad = tmp_path / "notes.pdf"
    bad.write_text("not a pdf")
    (name, inv, reason), = engine.read_files([bad])
    assert inv is None and reason.startswith("Could not be read")
    twice = files(with_vehicle(inv_0753(), "I20", "Edhayan - Ooty"),
                  with_vehicle(inv_0753(), "I20", "Edhayan - Ooty"))
    twice[1] = ("copy.pdf", twice[1][1], "")
    out = engine.calculate(build_masters(repo), twice + [(name, inv, reason)])
    assert [r.state for r in out.results] == [engine.READY, engine.NOT_USED, engine.NOT_USED]
    assert "is also in Invoice_DNS26-GST-0753.pdf" in out.results[1].reasons[0]


def test_print_changes_only_when_the_invoice_says_something_else():
    same, edited = inv_0753(), inv_0753()
    edited.salesperson = "Harish - MTP"
    assert engine.invoice_print(inv_0753()) == engine.invoice_print(same)
    assert engine.invoice_print(edited) != engine.invoice_print(same)


# --- the register ----------------------------------------------------------
class Sheet:
    """The register's two tabs as row lists, applying a Plan like Google would."""

    def __init__(self):
        self.payouts = [list(rg.PAYOUT_HEADERS)]
        self.invoices = [list(rg.INVOICE_HEADERS)]
        self.log = []

    def apply(self, plan):
        for n, cells in plan.payout_updates:
            self.payouts[n - 1][:len(cells)] = cells
        for n, cells in plan.invoice_updates:
            self.invoices[n - 1] = cells
        self.payouts += [list(r) for r in plan.payout_appends]
        self.invoices += [list(r) for r in plan.invoice_appends]
        self.log += plan.log
        return plan

    def scan(self, outcome, **kw):
        return self.apply(rg.plan(self.payouts, self.invoices, outcome, WHO, NOW, **kw))

    def row(self, line_id):
        return next(r for r in self.payouts if r[0] == line_id)


def test_post_once_and_tally(repo):
    sheet = Sheet()
    out = engine.calculate(build_masters(repo), september())
    first = sheet.scan(out)
    assert first.tally["files"] == 3 and first.tally["posted"] == 3
    assert [r[0] for r in sheet.payouts[1:]] == [
        "DNS26-GST-0753-LAB", "DNS26-GST-0753-INC", "DNS-226-2627-LAB",
        "DNS-226-2627-INC", "DNS-237-2627-LAB"]
    row = sheet.row("DNS-226-2627-LAB")
    assert row[rg.P["Status"]] == "Pending" and row[rg.P["Amount"]] == 950
    assert row[rg.P["Invoice date"]] == ms.date_to_serial(date(2026, 9, 4))
    assert row[rg.P["Calculated on"]] == "05-10-2026 18:00"
    assert [r[rg.I["State"]] for r in sheet.invoices[1:]] == ["Posted"] * 3
    assert sheet.invoices[1][rg.I["Scanned by"]] == WHO and len(sheet.log) == 3

    again = sheet.scan(engine.calculate(build_masters_fresh(repo), september()))
    assert again.tally["already posted"] == 3 and not again.has_writes
    assert sum(again.tally[k] for k in again.tally if k != "files") == again.tally["files"]


def test_posted_lines_do_not_change_when_a_master_changes_later(repo):
    sheet = Sheet()
    sheet.scan(engine.calculate(build_masters(repo), september()))
    mat = next(p for p in repo.list_rows("products") if p["name"].startswith("I20 - PVC"))
    repo.save("products", [RowChange(mat["id"], dict(mat, labour_charge=999.0),
                                     date(2026, 4, 1))])
    again = sheet.scan(engine.calculate(build_masters_fresh(repo), september()))
    assert not again.has_writes
    assert sheet.row("DNS26-GST-0753-LAB")[rg.P["Amount"]] == 150


def test_in_review_is_recorded_then_posted_when_fixed(repo):
    sheet = Sheet()
    odd = with_vehicle(inv_0753(), "I20", "Harish - Ho")
    first = sheet.scan(engine.calculate(build_masters(repo), files(odd)))
    assert first.tally["in review"] == 1 and sheet.payouts[1:] == []
    assert sheet.invoices[1][rg.I["State"]] == "In review"
    assert "Harish - Ho" in sheet.invoices[1][rg.I["Reason"]]
    same = sheet.scan(engine.calculate(build_masters_fresh(repo), files(odd)))
    assert same.tally["in review"] == 1 and not same.has_writes     # nothing new to say
    fixed = sheet.scan(engine.calculate(
        build_masters_fresh(repo), files(odd),
        [dict(kind="Salesperson", printed="Harish - Ho", target="Edhayan (9000000004)")]))
    assert fixed.tally["posted"] == 1 and len(sheet.invoices) == 2
    assert sheet.invoices[1][rg.I["State"]] == "Posted"
    assert sheet.row("DNS26-GST-0753-INC")[rg.P["Payee"]] == "Edhayan"


def test_start_date_and_cancelled_invoices(repo):
    sheet = Sheet()
    out = engine.calculate(build_masters(repo), september())
    sheet.invoices.append(["DNS-237-2627", "", "", "", "", "", "Cancelled", "", "", "", "", ""])
    done = sheet.scan(out, start=date(2026, 9, 5))
    assert (done.tally["before start date"], done.tally["cancelled"],
            done.tally["posted"]) == (1, 1, 1)
    assert {r[1] for r in sheet.payouts[1:]} == {"DNS26-GST-0753"}


def reissued_0753(salesperson="Edhayan - Ooty", drop_underbody=False):
    inv = with_vehicle(inv_0753(), "I20", salesperson)
    inv.lines[0].qty, inv.lines[0].amount = 2, 6600        # two floor mats now
    inv.sub_total, inv.total = 11601, 11600
    inv.discount_base, inv.taxes = 9831.36, {"CGST 9%": 884.73, "SGST 9%": 884.73}
    inv.rounding = 0.18
    if drop_underbody:
        del inv.lines[2]
        inv.sub_total, inv.total = 8101, 8100
        inv.discount_base, inv.taxes = 6865.25, {"CGST 9%": 617.78, "SGST 9%": 617.78}
        inv.rounding = 0.19
    return inv


def test_reissued_invoice_corrects_unpaid_lines(repo):
    sheet = Sheet()
    sheet.scan(engine.calculate(build_masters(repo), september()))
    done = sheet.scan(engine.calculate(build_masters_fresh(repo),
                                       files(reissued_0753(drop_underbody=True))))
    assert done.tally["re-issued"] == 1
    labour = sheet.row("DNS26-GST-0753-LAB")
    assert labour[rg.P["Amount"]] == 300 and labour[rg.P["Status"]] == "Pending"
    assert rg.unseal(labour[rg.P["Check"]])[rg.P["Amount"]] == "300.00"
    incentive = sheet.row("DNS26-GST-0753-INC")
    assert incentive[rg.P["Status"]] == "Cancelled"
    assert incentive[rg.P["Remarks"]] == "Invoice re-issued: no longer due"
    assert sheet.invoices[1][rg.I["State"]] == "Re-issued"
    assert sorted(e[2] for e in sheet.log[-2:]) == ["Re-issued invoice: line cancelled",
                                                    "Re-issued invoice: line corrected"]
    assert rg.verify(sheet.payouts, WHO, NOW).payout_updates == []


def test_reissued_invoice_adds_adjustments_for_paid_lines(repo):
    sheet = Sheet()
    sheet.scan(engine.calculate(build_masters(repo), september()))
    for lid in ("DNS26-GST-0753-LAB", "DNS26-GST-0753-INC"):
        sheet.row(lid)[rg.P["Status"]] = "Paid"
        sheet.row(lid)[rg.P["Reference"]] = "UTR1"
    # more labour, and the incentive now belongs to another executive
    sheet.scan(engine.calculate(build_masters_fresh(repo),
                                files(reissued_0753("Kumaran - HO"))))
    assert sheet.row("DNS26-GST-0753-LAB")[rg.P["Amount"]] == 150       # untouched
    adj = sheet.row("DNS26-GST-0753-LAB-ADJ1")
    assert adj[rg.P["Amount"]] == 150 and adj[rg.P["Status"]] == "Pending"
    assert adj[rg.P["Working"]].startswith("Invoice re-issued: now 300.00")
    back = sheet.row("DNS26-GST-0753-INC-ADJ1")
    assert back[rg.P["Payee"]] == "Edhayan"
    assert back[rg.P["Amount"]] == pytest.approx(-199.98, abs=0.02)
    new = sheet.row("DNS26-GST-0753-INC-ADJ2")
    assert new[rg.P["Payee"]] == "Kumaran" and new[rg.P["Amount"]] == pytest.approx(200, abs=0.05)
    # the same re-issued file again: nothing more to do
    again = sheet.scan(engine.calculate(build_masters_fresh(repo),
                                        files(reissued_0753("Kumaran - HO"))))
    assert again.tally["already posted"] == 1 and not again.has_writes


def test_cells_changed_by_hand_are_put_back(repo):
    sheet = Sheet()
    sheet.scan(engine.calculate(build_masters(repo), september()))
    assert rg.verify(sheet.payouts, WHO, NOW).has_writes is False
    row = sheet.row("DNS-226-2627-LAB")
    row[rg.P["Amount"]] = 9500                    # typed over in the browser
    row[rg.P["Status"]] = "Paid"                  # theirs to change
    check = rg.verify(sheet.payouts, WHO, NOW)
    assert [(e[2], e[3], e[4], e[5]) for e in check.log] == [
        ("Changed by hand - restored", "DNS-226-2627-LAB: Amount", "9500.00", "950.00")]
    assert check.warnings == [f"Payouts, row {sheet.payouts.index(row) + 1} "
                              "(DNS-226-2627-LAB): marked Paid without a reference or a proof."]
    sheet.apply(check)
    assert row[rg.P["Amount"]] == 950 and row[rg.P["Status"]] == "Paid"
    assert rg.verify(sheet.payouts, WHO, NOW).payout_updates == []


def test_rows_that_cannot_be_verified_and_duplicates(repo):
    sheet = Sheet()
    sheet.scan(engine.calculate(build_masters(repo), september()))
    sheet.payouts.append(list(sheet.payouts[1]))                       # pasted copy
    typed = ["X-1-LAB", "X-1", "", "", "", "Labour", "", 500]
    sheet.payouts.append(typed)
    problems = rg.verify(sheet.payouts, WHO, NOW).problems
    assert any("rows 2 and 7: the line DNS26-GST-0753-LAB is there twice" in p for p in problems)
    assert any(p.startswith("Payouts, row 8 (X-1-LAB): the Check cell is missing")
               for p in problems)


def test_pending_totals_and_matches_tab(repo):
    sheet = Sheet()
    sheet.scan(engine.calculate(build_masters(repo), september()))
    sheet.row("DNS-237-2627-LAB")[rg.P["Status"]] = "Paid"
    totals = rg.pending_by_payee(sheet.payouts)
    assert totals[0] == ("Labour", "", 1100.0, 175.0)
    assert [t[1] for t in totals[1:]] == ["Edhayan", "Nandha Kumar"]
    rows = [rg.MATCH_HEADERS, ["Item", "Old name", "New name", WHO, "x"], ["", "", ""]]
    assert rg.matches_from(rows) == [dict(kind="Item", printed="Old name", target="New name")]


def test_register_layout_matches_its_headings():
    tabs, layout = rg.new_register_tabs(), rg.register_layout()
    for tab in (rg.PAYOUTS, rg.INVOICES, rg.MATCHES, rg.LOG):
        assert len(layout[tab]) == len(tabs[tab][0]), tab
    requests = format_requests(7, layout[rg.PAYOUTS], len(rg.PAYOUT_HEADERS))
    warned = [r["addProtectedRange"]["protectedRange"] for r in requests
              if "addProtectedRange" in r]
    assert [w["range"]["startColumnIndex"] for w in warned] == list(range(10)) + [18]
    assert all(w["warningOnly"] for w in warned)
    hidden = [r["updateDimensionProperties"]["range"]["startIndex"] for r in requests
              if "updateDimensionProperties" in r]
    assert hidden == [rg.P["Check"]]
    assert rg.summary_formulas()[rg.SUMMARY_SECOND_TABLE_ROW + 1][0].startswith("=IFERROR(QUERY(")

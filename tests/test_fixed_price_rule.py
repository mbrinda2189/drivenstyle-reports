"""
test_fixed_price_rule.py - v0.35.0: incentive against fixed prices, the
"Prices above fixed price" report, and Recalculate
========================================================================

The client (16-11-2026) found salespeople typing an item ABOVE its fixed
price and then giving a "discount". From v0.35.0:

* the spot incentive compares what the customer paid for the WHOLE invoice
  with the invoice's fixed prices (bill value of the incentive group, else
  the Product master selling price, else the typed price):
      payable = full incentive x min(1, paid / fixed prices)
  so typing prices differently - with the same amount collected - can not
  change the incentive (the PPF + seat cover example from the chat);
* every item typed above its fixed price is listed for the internal team;
* Recalculate works posted invoices out again with today's masters: unpaid
  lines are corrected, newly due lines added, paid lines never touched.
"""

from datetime import date

import pytest

from app.data.inputs_repo import InputsRepo
from app.data.invoice_reader import InvoiceLine, ParsedInvoice
from app.data.masters_repo import MastersRepo, RowChange
from payout_app import engine, masters_sheet as ms

D = date(2026, 4, 1)


def masters(repo):
    """PPF (bill value 70,000, incentive 3,000), a seat cover sold at a
    selling price of 12,000 with no incentive, and the items of estimate
    515 at the client's real bill values / selling prices."""
    repo.save("incentives", [RowChange(None, dict(name=n, incentive_amount=a, bill_value=b,
                                                  active=True), D) for n, a, b in [
        ("PPF", 3000, 70000), ("Pvc Full Mat", 50, 3000),
        ("Nano Ceramic Sunfilm - Front", 500, 6000),
        ("Nano Ceramic Sunfilm - Side/Rear", 500, 7000),
        ("Nappa & Seat cover Above", 500, 12000), ("Rear Bumper", 200, 4500),
        ("Underbody", 200, 3500), ("Silencer", 150, 1500)]])
    repo.save("executives", [RowChange(None, dict(name="Arun Kumar", phone="9000000001",
                                                  branch="HO", gets_incentive=True,
                                                  active=True))])
    repo.save("cars", [RowChange(None, dict(make="Hyundai", model="Creta", segment="SUV",
                                            active=True))])
    items = [("Paint Protection Film", "PPF", 75000),
             ("Seat Cover - Plain", "", 12000),
             ("Creta - PVC Full Floor Mat", "Pvc Full Mat", 3300),
             ("Sunfilm - Nano Ceramic - Front (SK)", "Nano Ceramic Sunfilm - Front", 6000),
             ("Sunfilm - Nano Ceramic - Side and Rear (SK)",
              "Nano Ceramic Sunfilm - Side/Rear", 8000),
             ("Seat Cover - Infinity Leather -Lavish - creta", "Nappa & Seat cover Above", 14500),
             ("Rear Guard - SS - Ctrack", "Rear Bumper", 4800),
             ("Underbody Coating - 5 Seater", "Underbody", 3500),
             ("Silencer Coating - All Cars", "Silencer", 1500),
             ("Horn", "", 0),                         # no selling price: typed price counts
             ("Consumables - Exp", "", 1)]            # Rs. 1 = a placeholder, not a price
    repo.save("products", [RowChange(None, dict(
        sku="", name=n, hsn_sac="", category="Product", incentive_group=g, selling_price=sp,
        cost_price=100, has_labour=False, labour_charge=0, internal_incentive=0,
        vehicle_needed=True, active=True), D) for n, g, sp in items])
    result = ms.load_tabs(ms.to_tabs(repo, InputsRepo(repo)))
    assert result.ok, result.problems
    return result.masters


@pytest.fixture
def repo(tmp_path):
    from app.data.database import connect
    return MastersRepo(connect(tmp_path / "m.db"), "test")


def invoice(no, items, discount=0.0):
    lines = [InvoiceLine(i + 1, n, "", 1, "", a, a) for i, (n, a) in enumerate(items)]
    sub = sum(a for _, a in items)
    return ParsedInvoice(file_name=f"Invoice_{no}.pdf", gstin="33AAOFD7793F1Z2",
                         invoice_no=no, invoice_date=date(2026, 11, 4),
                         salesperson="Arun Kumar - HO", vehicle="CRETA", customer="SAMPLE",
                         lines=lines, sub_total=sub, discount=discount,
                         discount_base=sub if discount else 0, total=sub - discount)


def incentive(repo, *invoices):
    out = engine.calculate(masters(repo), [(i.file_name, i, "") for i in invoices])
    return {r.invoice_no: next((l for l in r.lines if l.type == engine.INCENTIVE), None)
            for r in out.results}


def test_typing_prices_differently_cannot_change_the_incentive(repo):
    """The chat's example: the customer pays 77,000 either way."""
    honest = invoice("DNS-701-2627", [("Paint Protection Film", 70000),
                                      ("Seat Cover - Plain", 12000)], 5000)
    shifted = invoice("DNS-702-2627", [("Paint Protection Film", 75000),
                                       ("Seat Cover - Plain", 7000)], 5000)
    got = incentive(repo, honest, shifted)
    expected = 3000 * 77000 / 82000                          # 2,817.07
    assert got["DNS-701-2627"].amount == pytest.approx(expected, abs=0.01)
    assert got["DNS-702-2627"].amount == pytest.approx(expected, abs=0.01)
    assert got["DNS-702-2627"].working.startswith(
        "Paid 77,000.00 vs fixed prices 82,000.00 -> 93.90% of the incentive.")


def test_one_item_raised_then_discounted(repo):
    """PPF typed at 75,000: less 5,000 -> full; less 10,000 -> 3,000 x 65/70."""
    full = invoice("DNS-703-2627", [("Paint Protection Film", 75000)], 5000)
    cut = invoice("DNS-704-2627", [("Paint Protection Film", 75000)], 10000)
    got = incentive(repo, full, cut)
    assert got["DNS-703-2627"].amount == 3000
    assert got["DNS-703-2627"].working == (
        "Paid 70,000.00 vs fixed prices 70,000.00 -> full incentive. PPF: 3,000 x 1 = 3,000 x 1")
    assert got["DNS-704-2627"].amount == pytest.approx(3000 * 65 / 70, abs=0.01)   # 2,785.71


def estimate_515():
    """Estimate / invoice 515: prices raised by 4,900, discount 4,400."""
    return invoice("DNS-515-2627", [
        ("Creta - PVC Full Floor Mat", 3400), ("Sunfilm - Nano Ceramic - Front (SK)", 6000),
        ("Sunfilm - Nano Ceramic - Side and Rear (SK)", 8000),
        ("Seat Cover - Infinity Leather -Lavish - creta", 15000),
        ("Rear Guard - SS - Ctrack", 5000), ("Underbody Coating - 5 Seater", 3500),
        ("Silencer Coating - All Cars", 1500)], 4400)


def test_invoice_515_earns_the_full_incentive(repo):
    """Fixed prices 37,500; the customer paid 38,000 -> the full 2,100."""
    line = incentive(repo, estimate_515())["DNS-515-2627"]
    assert line.amount == 2100
    assert line.working.startswith(
        "Paid 38,000.00 vs fixed prices 37,500.00 -> full incentive.")


def test_no_selling_price_counts_at_the_typed_price(repo):
    """A Horn with no selling price adds its typed price to both sides."""
    inv = invoice("DNS-705-2627", [("Paint Protection Film", 70000), ("Horn", 1800)], 1800)
    assert incentive(repo, inv)["DNS-705-2627"].amount == pytest.approx(
        3000 * 70000 / 71800, abs=0.01)


def test_prices_above_fixed_price_are_listed(repo):
    from app.data.invoices_repo import InvoicesRepo
    from app.reports.data import build_month
    m = masters(repo)
    engine.calculate(m, [("x.pdf", estimate_515(), "")])     # stores the invoice in `m`
    d = build_month(m, InvoicesRepo(m), InputsRepo(m), 2026, 11)
    rows = d.raised_prices()
    got = {r["product"]: (r["typed_unit"], r["fixed_unit"], r["raised"]) for r in rows}
    assert got == {
        "Seat Cover - Infinity Leather -Lavish - creta": (15000, 12000, 3000),
        "Sunfilm - Nano Ceramic - Side and Rear (SK)": (8000, 7000, 1000),
        "Rear Guard - SS - Ctrack": (5000, 4500, 500),
        "Creta - PVC Full Floor Mat": (3400, 3000, 400)}
    assert [r["raised"] for r in rows] == [3000, 1000, 500, 400]     # largest first
    assert rows[0]["inv_over"] == 500 and rows[0]["inv_discount"] == 4400
    assert rows[0]["fixed_source"] == "bill value" and rows[0]["has_incentive"]
    (summary,) = d.raised_by_executive()
    assert summary == dict(executive="Arun Kumar – HO", invoices=1, items=4,
                           raised=4900, discount=4400)


def test_a_placeholder_selling_price_is_not_a_fixed_price(repo):
    """Consumables at a master price of Rs. 1 count at their typed price and
    are not listed as raised."""
    from app.data.invoices_repo import InvoicesRepo
    from app.reports.data import build_month
    m = masters(repo)
    inv = invoice("DNS-706-2627", [("Paint Protection Film", 70000), ("Consumables - Exp", 650)])
    engine.calculate(m, [("x.pdf", inv, "")])
    d = build_month(m, InvoicesRepo(m), InputsRepo(m), 2026, 11)
    assert d.raised_prices() == []
    assert d.invoices[0].fixed_total == 70650 and d.invoices[0].incentive_payable == 3000

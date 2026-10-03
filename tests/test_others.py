"""
test_others.py - "Others" for salesperson / car, and Zoho price dates (v0.7.1)
==============================================================================

1. A salesperson or vehicle that is not in the masters can be fixed as
   "Others" on Scan review. The invoice then goes into the reports under
   Others (branch as printed on the invoice, incentive still calculated)
   instead of being left out.
2. A Zoho item list import makes Zoho's prices apply from the chosen date
   ONWARDS: later dated amounts (e.g. from the staff sheet) are removed.
"""

from datetime import date

from app.data.database import connect
from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import OTHERS, OTHERS_ID
from app.data.masters_repo import MastersRepo
from app.reports.data import build_month
from tests.test_counter_sales import month, product
from tests.test_invoice_export import line


def test_others_puts_the_invoice_in_the_reports(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    product(masters, "Horn")
    irepo = month(tmp_path, masters, [
        line("DNS-347-2627", "2026-09-06", "Jayaraj - KVP", "DOST - AUTO", "Horn",
             "", "", "goods", 1, 2100, 2100, inv_total=2100, branch="KVP"),
        line("DNS-348-2627", "2026-09-07", "Jayaraj - KVP", "DOST - AUTO", "Horn",
             "", "", "goods", 1, 2100, 2100, inv_total=2100, branch="KVP"),
    ])
    kinds = sorted(i.kind for i in irepo.issues(2026, 9))
    assert kinds == ["car", "salesperson"]            # one grouped row each
    assert build_month(masters, irepo, InputsRepo(masters), 2026, 9).invoices == []

    irepo.set_salesperson("name:x", "Jayaraj - KVP", OTHERS_ID, True)
    irepo.set_car("name:x", "DOST - AUTO", OTHERS_ID, True)
    assert irepo.issues(2026, 9) == []

    d = build_month(masters, irepo, InputsRepo(masters), 2026, 9)
    assert len(d.invoices) == 2
    inv = d.invoices[0]
    assert inv.executive == OTHERS and inv.branch == "KVP"
    assert inv.car == OTHERS and inv.segment == OTHERS
    assert inv.printed_executive == "Jayaraj - KVP"
    assert inv.printed_car == "DOST - AUTO"
    # the fix is in the audit log
    log = [r["new_value"] for r in masters.conn.execute(
        "SELECT new_value FROM audit_log WHERE master = 'scan'")]
    assert log == ["Others (not in master)"] * 2


def test_others_for_one_invoice_only(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    product(masters, "Horn")
    irepo = month(tmp_path, masters, [
        line("DNS-1-2627", "2026-09-06", "", "DZIRE", "Horn", "", "", "goods",
             1, 2100, 2100, inv_total=2100),
    ])
    irepo.set_salesperson("DNS-1-2627", "", OTHERS_ID, False)   # none printed
    irepo.set_car("DNS-1-2627", "DZIRE", OTHERS_ID, False)
    assert irepo.issues(2026, 9) == []
    [inv] = build_month(masters, irepo, InputsRepo(masters), 2026, 9).invoices
    assert inv.executive == OTHERS and inv.branch == "HO"


def test_zoho_prices_replace_later_dated_amounts():
    masters = MastersRepo(connect(":memory:"))
    rec = dict(name="Horn", selling_price=2000, cost_price=1000, labour_charge=600, _row=2)
    masters.import_records("products", [rec], date(2026, 4, 1))
    # first Zoho import went in dated 1 November (the v0.7.0 default)
    zoho = dict(name="Horn", selling_price=2100, cost_price=1200, _row=2)
    masters.import_records("products", [zoho], date(2026, 11, 1))
    pid = masters.list_rows("products")[0]["id"]
    assert masters.rate_on("products", pid, date(2026, 9, 5))["cost_price"] == 1000

    # importing Zoho's list again from 1 April makes its prices final
    r = masters.import_records("products", [dict(zoho)], date(2026, 4, 1),
                               replace_later=True)
    assert r.updated == 1
    for day in (date(2026, 4, 1), date(2026, 9, 5), date(2026, 12, 1)):
        rate = masters.rate_on("products", pid, day)
        assert (rate["selling_price"], rate["cost_price"]) == (2100, 1200)
        assert rate["labour_charge"] == 600           # labour is kept
    assert len(masters.rate_history("products", pid)) == 1

"""
test_counter_sales.py - Invoices without a vehicle (v0.6.7)
===========================================================

Counter items (perfume, shampoo, microfiber cloth ...) are sold without a
car. An invoice with no vehicle is accepted when every item on it is marked
"Vehicle needed = No"; a car job without a vehicle is still flagged.
"""

import sqlite3

from app.data import database
from app.data.database import connect
from app.data.invoice_export import classify_export
from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import FIRM_GSTIN, InvoicesRepo
from app.data.master_defs import counter_item_default
from app.data.masters_repo import MastersRepo, RowChange
from app.reports.data import COUNTER_SALE, build_month
from tests.test_invoice_export import line, write_csv


def product(masters, name, vehicle=None):
    values = dict(sku="", name=name, hsn_sac="", category="Product",
                  incentive_group="", selling_price=250, cost_price=100,
                  has_labour=False, labour_charge=0, active=True,
                  vehicle_needed=counter_item_default(name) if vehicle is None else vehicle)
    masters.save("products", [RowChange(None, values)])


def month(tmp_path, masters, rows):
    f = write_csv(tmp_path / "Invoice.csv", rows)
    irepo = InvoicesRepo(masters)
    irepo.store_scan(2026, 9, str(f), classify_export(f, 2026, 9, FIRM_GSTIN).results)
    return irepo


def test_counter_item_words():
    assert not counter_item_default("Turtle wax Perfume")
    assert not counter_item_default("Carnauba Shampoo-500ml - Turtlewax")
    assert not counter_item_default("Microfiber Cloth - GEN")
    assert counter_item_default("Wax Polishing - All Cars")        # done on a car
    assert counter_item_default("Roof Rail - All cars")


def test_counter_sale_needs_no_vehicle(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    masters.save("executives", [RowChange(None, dict(
        name="Nandha Kumar", phone="9876543210", branch="HO", active=True))])
    product(masters, "Turtle wax Perfume")
    product(masters, "Horn")
    irepo = month(tmp_path, masters, [
        # counter sale: perfume only, no vehicle -> accepted
        line("DNS-241-2627", "2026-09-06", "Nandha Kumar", "", "Turtle wax Perfume",
             "", "", "goods", 1, 250, 250, inv_total=250),
        # a horn needs a car: no vehicle -> flagged
        line("DNS-242-2627", "2026-09-06", "Nandha Kumar", "", "Horn", "", "", "goods",
             1, 2100, 2100, inv_total=2100),
        # perfume + horn, no vehicle -> flagged
        line("DNS-243-2627", "2026-09-06", "Nandha Kumar", "", "Turtle wax Perfume",
             "", "", "goods", 1, 250, 250, inv_total=2350),
        line("DNS-243-2627", "2026-09-06", "Nandha Kumar", "", "Horn", "", "", "goods",
             1, 2100, 2100, inv_total=2350),
    ])
    cars = [i for i in irepo.issues(2026, 9) if i.kind == "car"]
    assert sorted(i.key for i in cars) == ["DNS-242-2627", "DNS-243-2627"]

    d = build_month(masters, irepo, InputsRepo(masters), 2026, 9)
    [inv] = d.invoices
    assert inv.invoice_no == "DNS-241-2627" and inv.car == COUNTER_SALE
    assert inv.segment == COUNTER_SALE


def test_vehicle_needed_can_be_turned_off_on_the_masters_screen(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    product(masters, "Horn")
    horn = masters.list_rows("products")[0]
    assert horn["vehicle_needed"] is True
    masters.save("products", [RowChange(horn["id"], dict(horn, vehicle_needed=False))])
    assert masters.get("products", horn["id"])["vehicle_needed"] is False


def test_upgrade_marks_existing_counter_items(tmp_path):
    db = tmp_path / "drivenstyle.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for step in database._MIGRATIONS[:6]:
        if callable(step):
            step(conn)
        else:
            conn.executescript(step)
    conn.executescript("""
        INSERT INTO meta VALUES ('schema_version', '6');
        INSERT INTO products(name, name_key) VALUES ('Turtle wax Perfume', 'turtle wax perfume'),
                                                    ('Horn', 'horn');
    """)
    conn.commit()
    conn.close()
    masters = MastersRepo(connect(db))
    flags = {p["name"]: p["vehicle_needed"] for p in masters.list_rows("products")}
    assert flags == {"Turtle wax Perfume": False, "Horn": True}
    log = masters.audit_entries(master="products")
    assert any(e["field"] == "Vehicle needed" and e["record"] == "Turtle wax Perfume"
               for e in log)

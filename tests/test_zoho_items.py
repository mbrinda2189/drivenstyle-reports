"""
test_zoho_items.py - Zoho's item list as the Product master (v0.7.0)
====================================================================

Zoho's item names and prices are final (Brinda, 03-10-2026). Item.csv from
Zoho Books is imported as the Product master; the staff sheet only adds
labour / incentive for those items.
"""

import csv

from app.data.database import connect
from app.data.excel_io import (
    convert_rows, is_zoho_item_export, read_sheet, suggest_mapping, zoho_item_mapping)
from app.data.master_defs import PRODUCTS
from app.data.masters_repo import MastersRepo, RowChange
from app.utils import parse_inr

HEAD = ["Item ID", "Item Name", "SKU", "HSN/SAC", "Description", "Rate", "Account",
        "Product Type", "Product Name", "Status", "Purchase Rate", "Item Type"]
ROWS = [
    ["1", "Water Wash - Hatchback", "WW-Hatch", "998729", "", "INR 800.00", "Sales",
     "service", "Water Wash - Hatchback", "Active", "INR 1.00", "Sales and Purchases"],
    ["2", "Roof Rail - All cars", "", "87089900", "", "INR 3500.00", "Sales",
     "goods", "Roof Rail - All cars", "Active", "INR 1865.00", "Inventory"],
    ["3", "Labour Charges for Sunfilm - Front", "LAC-04", "998729", "", "INR 1.00",
     "Sales", "service", "Labour Charges for Sunfilm - Front", "Active", "INR 700.00",
     "Sales and Purchases"],
]


def zoho_records(tmp_path, rows=ROWS):
    f = tmp_path / "Item.csv"
    with open(f, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(HEAD)
        w.writerows(rows)
    sheet = read_sheet(f, PRODUCTS)
    assert is_zoho_item_export(sheet.headers)
    recs, problems = convert_rows(PRODUCTS, sheet, zoho_item_mapping(sheet.headers))
    assert problems == []
    return recs


def test_zoho_ppf_labour_item_is_a_marker():
    from app.data.invoices_repo import is_labour_marker
    assert is_labour_marker("Paint Protection Film -Labour Charges")
    assert not is_labour_marker("Seat Cover - Lavish Mvs - City + Labour charges")
    assert not is_labour_marker("MLF MAT - Ertiga + Labour Charges")


def test_inr_prefix_is_read_as_an_amount():
    assert parse_inr("INR 14000.00") == 14000.0
    assert parse_inr("Rs. 1,200") == 1200.0


def test_zoho_export_is_recognised_and_mapped(tmp_path):
    sheet = read_sheet(_write(tmp_path), PRODUCTS)
    m = zoho_item_mapping(sheet.headers)
    assert m == {"name": "Item Name", "sku": "SKU", "hsn_sac": "HSN/SAC",
                 "selling_price": "Rate", "cost_price": "Purchase Rate",
                 "category": "Product Type"}
    assert not is_zoho_item_export(["CODE", "Item Description", "Sale with GST"])


def _write(tmp_path):
    f = tmp_path / "Item.csv"
    with open(f, "w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerows([HEAD] + ROWS)
    return f


def test_import_takes_names_prices_and_category_from_zoho(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    recs, markers = MastersRepo.split_zoho_items(zoho_records(tmp_path))
    assert markers == ["Labour Charges for Sunfilm - Front"]            # not a product
    result = masters.import_records("products", recs, source="Import: Item.csv")
    assert result.added == 2
    rows = {p["name"]: p for p in masters.list_rows("products")}
    rail = rows["Roof Rail - All cars"]
    assert rail["selling_price"] == 3500 and rail["cost_price"] == 1865
    assert rail["category"] == "Product" and rail["hsn_sac"] == "87089900"
    assert rows["Water Wash - Hatchback"]["category"] == "Service"


def test_zoho_import_keeps_labour_and_incentive_and_updates_prices(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    masters.save("incentives", [RowChange(None, dict(
        name="Side Step", incentive_amount=300, bill_value=12500, active=True))])
    masters.save("products", [RowChange(None, dict(
        sku="", name="Roof Rail - All cars", hsn_sac="", category="Service",
        incentive_group="Side Step", selling_price=3000, cost_price=1780,
        has_labour=True, labour_charge=250, vehicle_needed=True, active=True))])
    recs, _ = MastersRepo.split_zoho_items(zoho_records(tmp_path))
    result = masters.import_records("products", recs)
    assert result.updated == 1 and result.added == 1
    rail = next(p for p in masters.list_rows("products") if p["name"].startswith("Roof"))
    assert (rail["selling_price"], rail["cost_price"]) == (3500, 1865)   # Zoho's
    assert rail["category"] == "Product"                                 # Zoho's
    assert rail["labour_charge"] == 250 and rail["has_labour"] is True   # kept
    assert rail["incentive_group"] == "Side Step"                        # kept


def test_products_not_in_zoho_list(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    for name in ("Roof rails - All Cars", "Roof Rail - All cars"):
        masters.save("products", [RowChange(None, dict(
            sku="", name=name, hsn_sac="", category="Product", incentive_group="",
            selling_price=1, cost_price=1, has_labour=False, labour_charge=0,
            vehicle_needed=True, active=True))])
    names = [r[1] for r in ROWS]
    missing = masters.products_not_in(names)
    assert [p["name"] for p in missing] == ["Roof rails - All Cars"]
    masters.delete("products", [p["id"] for p in missing], source="Import: Item.csv")
    assert [p["name"] for p in masters.list_rows("products")] == ["Roof Rail - All cars"]
    assert any(e["action"] == "Deleted" for e in masters.audit_entries(master="products"))


def test_staff_sheet_updates_only_existing_items_when_add_new_is_off(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    recs, _ = MastersRepo.split_zoho_items(zoho_records(tmp_path))
    masters.import_records("products", recs)
    staff = [dict(_row=2, name="Roof Rail - All cars", labour_charge=250.0),
             dict(_row=3, name="ROOF RAIL SILVER/BLACK - CRETA", labour_charge=250.0)]
    result = masters.import_records("products", staff, add_new=False)
    assert result.not_added == 1 and result.added == 0
    rows = {p["name"]: p for p in masters.list_rows("products")}
    assert set(rows) == {"Roof Rail - All cars", "Water Wash - Hatchback"}
    assert rows["Roof Rail - All cars"]["labour_charge"] == 250
    assert rows["Roof Rail - All cars"]["has_labour"] is True           # switched on
    assert rows["Roof Rail - All cars"]["selling_price"] == 3500        # untouched

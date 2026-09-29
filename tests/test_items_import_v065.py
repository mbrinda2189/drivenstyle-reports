"""
test_items_import_v065.py - Client's category column and repeated CODEs (v0.6.5)
================================================================================
"""

from openpyxl import Workbook

from app.data.database import connect
from app.data.excel_io import convert_rows, convert_value, read_sheet, suggest_mapping
from app.data.invoice_export import classify_export
from app.data.invoices_repo import FIRM_GSTIN, InvoicesRepo
from app.data.master_defs import PRODUCTS
from app.data.masters_repo import MastersRepo, RowChange
from tests.test_invoice_export import rows_226, write_csv

HEAD = [None, "CODE", "category", "Item Description", "Labour", "Sale with GST",
        "Purchase without GST", "HSN/SAC"]


def sheet(tmp_path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Data - Items"
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    wb.save(tmp_path / "Items.xlsx")
    sh = read_sheet(tmp_path / "Items.xlsx", PRODUCTS)
    recs, problems = convert_rows(PRODUCTS, sh, suggest_mapping(PRODUCTS, sh.headers))
    assert problems == []
    return recs


def test_sales_is_product_and_service_is_service():
    f = PRODUCTS.get_field("category")
    assert convert_value(f, "SALES") == "Product"
    assert convert_value(f, "SERVICE") == "Service"
    assert convert_value(f, "120 sqft purchased") is None       # notes ignored


def test_category_column_matched_and_final(tmp_path):
    recs = sheet(tmp_path, [
        [1, "HRN", "SALES", "Horn", "-", 2100, 900, 998729],          # SAC, but SALES
        [2, "MUD", "SERVICE", "Punch.EV Mudflap - Techno", 0, 750, 300, 87089900],
    ])
    assert [r["category"] for r in recs] == ["Product", "Service"]
    masters = MastersRepo(connect(":memory:"))
    masters.import_records("products", recs)
    # Zoho says both are goods: only products WITHOUT a sheet category follow it.
    f = write_csv(tmp_path / "Invoice.csv", rows_226())
    irepo = InvoicesRepo(masters)
    irepo.store_scan(2026, 9, str(f), classify_export(f, 2026, 9, FIRM_GSTIN).results)
    cats = {p["name"]: p["category"] for p in masters.list_rows("products")}
    assert cats == {"Horn": "Product", "Punch.EV Mudflap - Techno": "Service"}


def test_category_changed_on_masters_screen_is_final(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    masters.import_records("products", sheet(tmp_path, [
        [1, "HRN", None, "Horn", 0, 2100, 900, 998729]]))             # no category
    horn = masters.list_rows("products")[0]
    assert horn["category"] == "Service"                               # from SAC 99…
    row = dict(horn, category="Service")
    masters.save("products", [RowChange(horn["id"], dict(row, category="Product"))])
    masters.save("products", [RowChange(horn["id"], dict(row, category="Service"))])
    f = write_csv(tmp_path / "Invoice.csv", rows_226())
    irepo = InvoicesRepo(masters)
    irepo.store_scan(2026, 9, str(f), classify_export(f, 2026, 9, FIRM_GSTIN).results)
    assert masters.get("products", horn["id"])["category"] == "Service"   # not Zoho's


def test_code_shared_by_different_items_is_dropped(tmp_path):
    recs = sheet(tmp_path, [
        [124, 87089900, "SALES", "REAR POWER WINDOW - EXTER", 0, 4000, 2500, None],
        [181, 87089900, "SALES", "Roof rails - All Cars", 0, 3500, 1780, None],
        [190, 87089900, "SALES", "Door Visior - Aura", 0, 1500, 600, None],
        [10, "HRN", "SALES", "Horn", 0, 2100, 900, None],
        [11, "HRN", "SALES", "Horn", 0, 2200, 900, None],               # true repeat
    ])
    masters = MastersRepo(connect(":memory:"))
    result = masters.import_records("products", recs)
    rows = {p["name"]: p for p in masters.list_rows("products")}
    assert set(rows) == {"REAR POWER WINDOW - EXTER", "Roof rails - All Cars",
                         "Door Visior - Aura", "Horn"}                  # none lost
    assert all(rows[n]["sku"] == "" for n in rows if n != "Horn")
    assert rows["Horn"]["sku"] == "HRN" and rows["Horn"]["selling_price"] == 2200
    assert any("CODE 87089900 is used for 3 different items" in w for w in result.warnings)


def test_upgrade_adds_category_fixed(tmp_path):
    conn = connect(tmp_path / "t.db")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(products)")}
    assert "category_fixed" in cols

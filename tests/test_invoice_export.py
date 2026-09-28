"""
test_invoice_export.py - Tests for Zoho's invoice export (v0.6.0)
=================================================================

Real client exports are never committed to Git, so these tests write a
small Invoice.csv in code with the same columns and figures as the
September 2026 export (DNS26-GST-0753, DNS-226-2627), plus made-up rows for
the special cases (another month, a void invoice, a wrong total).
"""

import csv
from datetime import date

import pytest
from openpyxl import Workbook

from app.data.database import connect
from app.data.excel_io import convert_rows, read_sheet, suggest_mapping
from app.data.invoice_export import ExportFileError, classify_export, read_export
from app.data.invoices_repo import (
    FIRM_GSTIN, ZOHO_CATEGORY_SOURCE, InvoicesRepo, branch_key, is_labour_marker,
    person_key)
from app.data.master_defs import PRODUCTS
from app.data.masters_repo import MastersRepo, RowChange

HEAD = ["Invoice Date", "Invoice ID", "Invoice Number", "Invoice Status",
        "Customer Name", "Sales person", "CF.Vehicle", "CF.VIN / Registration Number",
        "CF.Customer Type", "CF.Branch", "CF.Invoice Type", "Item Name", "SKU",
        "HSN/SAC", "Item Type", "Quantity", "Usage unit", "Item Price", "Item Total",
        "Item Tax %", "Item Tax Amount", "CGST Rate %", "CGST", "SGST Rate %", "SGST",
        "IGST", "Entity Discount Amount", "SubTotal", "Round Off", "Total", "Balance",
        "Supplier Org Name", "Supplier GST Registration Number"]


def line(no, day, sp, car, item, sku, hsn, typ, qty, price, total, tax=0.0,
         disc=0.0, ro=0.0, inv_total=0.0, balance=0.0, status="Closed",
         mode="UPI", branch="HO", gstin=FIRM_GSTIN):
    half = round(tax / 2, 2)
    return {"Invoice Date": day, "Invoice ID": "1", "Invoice Number": no,
            "Invoice Status": status, "Customer Name": "CUSTOMER", "Sales person": sp,
            "CF.Vehicle": car, "CF.VIN / Registration Number": "TN99", "CF.Customer Type":
            "Walk-In", "CF.Branch": branch, "CF.Invoice Type": mode, "Item Name": item,
            "SKU": sku, "HSN/SAC": hsn, "Item Type": typ, "Quantity": f"{qty:.2f}",
            "Usage unit": "", "Item Price": f"{price:.2f}", "Item Total": f"{total:.2f}",
            "Item Tax %": "18.00" if tax else "", "Item Tax Amount": f"{tax:.2f}" if tax else "",
            "CGST Rate %": "9.00" if tax else "", "CGST": f"{half:.2f}" if tax else "",
            "SGST Rate %": "9.00" if tax else "", "SGST": f"{half:.2f}" if tax else "",
            "IGST": "", "Entity Discount Amount": f"{disc:.3f}", "SubTotal": "0",
            "Round Off": f"{ro:.2f}", "Total": f"{inv_total:.2f}", "Balance": f"{balance:.2f}",
            "Supplier Org Name": "CARKRAFTS - Coimbatore",
            "Supplier GST Registration Number": gstin}


def rows_0753():
    """DNS26-GST-0753 exactly as in the September export (GST, discount Rs. 1)."""
    k = dict(no="DNS26-GST-0753", day="2026-09-05", sp="Edhayan - Cuddalore",
             car="I20", disc=1.0, ro=0.20, inv_total=8300.0)
    return [
        line(item="I20 - PVC Full Floor Mat + Labour Extra", sku="EA-DS01PVC-CBE",
             hsn="39181090", typ="goods", qty=1, price=3300, total=2796.20, tax=503.32, **k),
        line(item="Labour Charges for PVC/MLF/Luxury Floor Mat (i20/ NIOS/ Aura/ Verna)",
             sku="LAC-01", hsn="39181090", typ="service", qty=1, price=1, total=0.84,
             tax=0.16, **k),
        line(item="Underbody Coating - 5 Seater", sku="UC-5S", hsn="870899", typ="goods",
             qty=1, price=3500, total=2965.68, tax=533.82, **k),
        line(item="Silencer Coating - All Cars", sku="SC-A", hsn="870892", typ="goods",
             qty=1, price=1500, total=1271.00, tax=228.78, **k)]


def rows_226():
    """DNS-226-2627 (no GST, Rs. 1,903 discount) - Zoho's Item Totals."""
    k = dict(no="DNS-226-2627", day="2026-09-04", sp="Nandha Kumar", car="PUNCH.EV",
             disc=1903.0, inv_total=20000.0, branch="", hsn="998729", sku="")
    items = [("Sunfilm - Nano Ceramic - Front (SK)", 7000, 6391.82, "goods"),
             ("Labour Charges for Sunfilm - Front", 1, 0.91, "service"),
             ("Sunfilm - Nano Ceramic - Side and Rear (SK)", 8000, 7304.94, "goods"),
             ("Labour Charges for Sunfilm - Side and Rear", 1, 0.91, "service"),
             ("Horn", 2100, 1917.55, "goods"), ("Punch.EV Mudflap - Techno", 750, 684.84, "goods"),
             ("PUNCH - PVC Full Floor Mat + Labour Extra", 3500, 3195.91, "goods"),
             ("Labour Charges for PVC/MLF/Luxury Floor Mat (i20/ NIOS/ Aura/ Verna)", 1, 0.91,
              "service"),
             ("Punch EV Number Plate Frame", 550, 502.21, "goods")]
    return [line(item=n, typ=t, qty=1, price=p, total=v, **k) for n, p, v, t in items]


def extra_rows():
    return [
        # An August invoice in the same export -> ignored for September.
        line("DNS-150-2627", "2026-08-30", "Nandha Kumar", "I20", "Horn", "", "", "goods",
             1, 2100, 2100, inv_total=2100),
        # A void invoice -> skipped.
        line("DNS-300-2627", "2026-09-20", "Nandha Kumar", "I20", "Horn", "", "", "goods",
             1, 2100, 2100, inv_total=2100, status="Void"),
        # Overdue, cash, with a total that does not agree with its lines.
        line("DNS-301-2627", "2026-09-21", "Udhayakumar - Head Office", "CRETA",
             "Labour - Seat Cover - Art Leather", "", "", "service", 1, 1, 1,
             inv_total=2501, balance=2501, mode="Cash"),
        line("DNS-301-2627", "2026-09-21", "Udhayakumar - Head Office", "CRETA",
             "Seat Cover Lavish - Creta", "", "998729", "goods", 1, 2400, 2400,
             inv_total=2501, balance=2501, mode="Cash"),
    ]


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=HEAD)
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def export(tmp_path):
    return write_csv(tmp_path / "Invoice.csv", rows_0753() + rows_226() + extra_rows())


# --- reading ------------------------------------------------------------------
def test_reads_one_invoice_per_number(export):
    exp = read_export(export)
    assert exp.rows == 17
    assert [i.invoice_no for i in exp.invoices] == [
        "DNS26-GST-0753", "DNS-226-2627", "DNS-150-2627", "DNS-300-2627", "DNS-301-2627"]
    gst = exp.invoices[0]
    assert gst.source == "export" and gst.invoice_date == date(2026, 9, 5)
    assert gst.taxes == {"CGST 9%": 633.04, "SGST 9%": 633.04} and gst.tax_rate == 18.0
    assert gst.total == 8300 and gst.rounding == 0.20 and gst.payment_mode == "UPI"
    assert gst.lines[0].net_value == 2796.20 and gst.lines[0].gst == 503.32
    assert gst.lines[0].item_type == "goods" and gst.lines[0].sku == "EA-DS01PVC-CBE"
    unpaid = exp.invoices[-1]                  # Total 2,501, Balance 2,501
    assert unpaid.payment_made == 0 and unpaid.balance_due == 2501
    assert unpaid.payment_mode == "Cash" and unpaid.branch == "HO"


def test_reads_xlsx_too(tmp_path):
    wb = Workbook()
    wb.active.append(HEAD)
    for r in rows_0753():
        wb.active.append([r[h] for h in HEAD])
    wb.save(tmp_path / "Invoice.xlsx")
    [inv] = read_export(tmp_path / "Invoice.xlsx").invoices
    assert inv.invoice_no == "DNS26-GST-0753" and len(inv.lines) == 4


def test_not_an_export_is_refused(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("Name,Amount\nA,1\n")
    with pytest.raises(ExportFileError, match="Invoice Number"):
        read_export(f)
    with pytest.raises(ExportFileError):
        read_export(tmp_path / "x.pdf")


def test_classify_keeps_the_month(export):
    scan = classify_export(export, 2026, 9, FIRM_GSTIN)
    assert scan.other_months == 1
    status = {r.file_name: r.status for r in scan.results}
    assert status == {"DNS26-GST-0753": "read", "DNS-226-2627": "read",
                      "DNS-300-2627": "skipped", "DNS-301-2627": "read"}


def test_labour_markers_include_labour_dash():
    assert is_labour_marker("Labour - Seat Cover - Art Leather")
    assert is_labour_marker("Labour Charges PVC/MLF/Luxury Floor Mat  (Venue / Exter / Creta)")
    assert not is_labour_marker("MLF MAT EXTER + LABOUR EXTRA")
    assert not is_labour_marker("Labourer gloves")


def test_person_and_branch_keys():
    assert person_key("UDHAYA KUMAR") == person_key("Udhayakumar")
    assert person_key("S.F. Naveen") == person_key("SF Naveen")
    assert branch_key("Head Office") == branch_key("HO") == branch_key("Ho")
    assert branch_key("KTG") == branch_key("KOTHAGIRI")


# --- storing, checks and matching --------------------------------------------------
@pytest.fixture
def stored(export):
    masters = MastersRepo(connect(":memory:"))
    irepo = InvoicesRepo(masters)
    scan = classify_export(export, 2026, 9, FIRM_GSTIN)
    irepo.store_scan(2026, 9, str(export), scan.results)
    return masters, irepo


def test_zoho_line_values_are_stored_as_they_are(stored):
    _, irepo = stored
    inv = {i["invoice_no"]: i for i in irepo.invoices(2026, 9)}
    lines = inv["DNS26-GST-0753"]["lines"]
    assert [l["net_value"] for l in lines] == [2796.20, 0.84, 2965.68, 1271.00]
    assert round(sum(l["gst"] for l in lines), 2) == 1266.08
    assert lines[1]["is_labour_marker"] == 1
    assert round(sum(l["net_value"] for l in inv["DNS-226-2627"]["lines"]), 2) == 20000.00
    assert inv["DNS26-GST-0753"]["source"] == "export"
    assert inv["DNS-301-2627"]["status"] == "Closed"
    assert inv["DNS-301-2627"]["lines"][0]["is_labour_marker"] == 1


def test_export_totals_check(stored):
    _, irepo = stored
    totals = [i for i in irepo.issues(2026, 9) if i.kind == "totals"]
    assert [i.key for i in totals] == ["DNS-301-2627"]          # 2,401 vs 2,501
    assert "Total is 2,501.00" in totals[0].message
    skipped = [i for i in irepo.issues(2026, 9) if i.kind == "file"]
    assert [i.key for i in skipped] == ["DNS-300-2627"]


def test_salesperson_matching_ignores_spaces_and_branch_short_forms(stored):
    masters, irepo = stored
    masters.save("executives", [
        RowChange(None, dict(name="UDHAYA KUMAR", phone="9876543210", branch="HO", active=True)),
        RowChange(None, dict(name="Edhayan", phone="9876543211", branch="Cuddalore",
                             active=True))])
    inv = {i["invoice_no"]: i for i in irepo.invoices(2026, 9)}
    assert inv["DNS-301-2627"]["executive"] == "UDHAYA KUMAR – HO"
    assert inv["DNS26-GST-0753"]["executive"] == "Edhayan – Cuddalore"


def add_product(masters, name, category="Product", source="Items.xlsx"):
    masters.save("products", [RowChange(None, dict(
        sku="", name=name, hsn_sac="998729", category=category, incentive_group="",
        selling_price=0, cost_price=0, has_labour=False, labour_charge=0,
        active=True))], source=source)
    return next(p for p in masters.list_rows("products") if p["name"] == name)


def test_category_follows_zoho_item_type_unless_set_by_hand(stored):
    masters, irepo = stored
    # Imported with the HSN guess "Service", but Zoho says goods.
    horn = add_product(masters, "Horn", "Service")
    # Added on the Masters screen: the user chose the category - kept.
    mud = add_product(masters, "Punch.EV Mudflap - Techno", "Service", "Masters screen")
    assert irepo.apply_zoho_categories() == 1
    assert masters.get("products", horn["id"])["category"] == "Product"
    assert masters.get("products", mud["id"])["category"] == "Service"
    log = masters.conn.execute("SELECT * FROM audit_log WHERE source = ?",
                               (ZOHO_CATEGORY_SOURCE,)).fetchall()
    assert [(r["old_value"], r["new_value"]) for r in log] == [("Service", "Product")]

    # Corrected by hand afterwards -> Zoho no longer changes it.
    row = dict(masters.get("products", horn["id"]), category="Service")
    masters.save("products", [RowChange(horn["id"], row)])
    assert irepo.apply_zoho_categories() == 0
    assert masters.get("products", horn["id"])["category"] == "Service"


def test_mapping_an_item_applies_its_zoho_type(stored):
    masters, irepo = stored
    plate = add_product(masters, "Number plate frame", "Service")
    irepo.map_product("Punch EV Number Plate Frame", plate["id"])
    assert masters.get("products", plate["id"])["category"] == "Product"


# --- the client's Items.xlsx -----------------------------------------------------
def test_items_master_headings_and_dash_amounts(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append([None, "CODE", "Item Description", "Vendor", "Labour", "Sale with GST",
               "Purchase without GST", "Margin", "Min Sale Price with GST", "HSN/SAC",
               "Product Type", "Usuage Unit", None])
    ws.append([1, "WW-Hatch", "Water Wash - Hatchback", None, "-", 800, 1, None, None,
               998729.0, None, None, "ok ok"])
    ws.append([2, "SF-F", "Sunfilm - Front", None, 400, 7000, 2500, 3032, 6500,
               39206929.0, "120 sqft purchased", None, None])
    wb.save(tmp_path / "Items.xlsx")
    sheet = read_sheet(tmp_path / "Items.xlsx", PRODUCTS)
    mapping = suggest_mapping(PRODUCTS, sheet.headers)
    assert mapping["sku"] == "CODE" and mapping["name"] == "Item Description"
    assert mapping["labour_charge"] == "Labour" and mapping["has_labour"] is None
    assert mapping["selling_price"] == "Sale with GST"
    assert mapping["cost_price"] == "Purchase without GST"
    records, problems = convert_rows(PRODUCTS, sheet, mapping)
    assert problems == []
    assert records[0]["labour_charge"] == 0.0 and records[1]["labour_charge"] == 400.0
    assert records[1].get("category") is None          # notes, not a category

    masters = MastersRepo(connect(":memory:"))
    masters.import_records("products", records)
    rows = {p["sku"]: p for p in masters.list_rows("products")}
    assert rows["SF-F"]["has_labour"] is True and rows["WW-Hatch"]["has_labour"] is False
    assert rows["WW-Hatch"]["category"] == "Service"     # from the SAC code
    assert rows["SF-F"]["selling_price"] == 7000 and rows["SF-F"]["cost_price"] == 2500

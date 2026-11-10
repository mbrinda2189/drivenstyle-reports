"""
test_cogs_check.py - v0.33.0: product cost, master sheet vs Zoho
===============================================================

The client: "Invoice level - Sale - COGS - item difference compared to master
sheet. Zoho uses FIFO inventory costing ... what costing is it taking for
each item, compared to the master sheet."

The two Zoho files are built here in the shape of the real exports:
    Account_Transactions.xlsx   title row, then date | account_name |
                                transaction_details | ... | transaction_type |
                                reference_number | entity_number | debit |
                                credit | net_amount | ... | account_type
    FIFO_Cost_Lot_Tracking.xlsx title row, "Product In / Product Out" row,
                                then the headings (Date and Transactions twice)
Every product in the master costs Rs. 100 a unit (tests.test_counter_sales).
"""

import io
from datetime import date

import openpyxl
import pytest

from app.data.database import connect
from app.data.inputs_repo import InputsRepo
from app.data.masters_repo import MastersRepo, RowChange
from app.data.zoho_costs import ZohoCostFileError, read_cogs, read_fifo
from app.reports.data import build_month
from app.reports.generate import GenerateError, generate
from tests.test_counter_sales import month, product
from tests.test_invoice_export import line

COGS_HEAD = ["date", "account_name", "transaction_details", "transaction_id",
             "reference_transaction_id", "offset_account_id", "offset_account_type",
             "transaction_type", "reference_number", "entity_number", "debit", "credit",
             "net_amount", "contact_id", "account_id", "currency_code", "account_group",
             "account_type"]


def cogs_row(day, kind, number, debit=0.0, credit=0.0, who="CUSTOMER"):
    return [day, "Cost of Goods Sold", who, "1", None, "", "", kind, "E-1", number,
            debit or "", credit or "", round(debit - credit, 2), "1", "2", "INR", "expense",
            "cost_of_goods_sold"]


def write_cogs(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["CARKRAFTS - Coimbatore\nAccount Transactions\nBasis: Accrual\n"
               "From 01/09/2026 To 30/09/2026"])
    ws.append(COGS_HEAD)
    for row in (cogs_row("2026-09-06", "invoice", "DNS-1-2627", 250),     # master 200
                cogs_row("2026-09-06", "invoice", "DNS-2-2627", 100),     # master 100
                # DNS-3-2627: Zoho posted no COGS (master 100)
                cogs_row("2026-09-20", "invoice", "DNS-9-2627", 40),      # not in the export
                cogs_row("2026-09-14", "bill", "DC-1", 450, who="Wuerth India"),
                cogs_row("2026-09-02", "vendor_credit", "171", 0, 60, who="Autograde INC")):
        ws.append(row)
    ws.append([""])
    wb.save(path)
    return path


FIFO_HEAD = ["Date", "Transactions", "Received From", "Item Name", "SKU", "Quantity", "Age",
             "Remaining Qty", "Cost Per Unit", "Total", "Date", "Transactions", "Disperse To",
             "Dispersed Qty"]


def write_fifo(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["CARKRAFTS - Coimbatore\n FIFO Cost Lot Tracking\n From 01/07/2026 To 10/11/2026"])
    ws.append(["Product In"] * 10 + ["Product Out"] * 4)
    ws.append(FIFO_HEAD)
    for row in (
        # Horn on DNS-1: one unit from a lot at 150 (master 100)
        ["20/07/2026", "Bill # 215", "Autograde INC", "Horn", "", "2.00", "", "-", "150.00",
         "300.00", "06/09/2026", "Invoice # DNS-1-2627", "SOUDHA", "1.00"],
        # Mat on DNS-1: sold with no stock -> Zoho cost 0
        ["", "", "", "Mat", "", "0.00", "", "-1.00", "0.00", "0.00", "06/09/2026",
         "Invoice # DNS-1-2627", "SOUDHA", "1.00"],
        # Horn on DNS-2 from the same lot
        ["20/07/2026", "Bill # 215", "Autograde INC", "Horn", "", "2.00", "", "-", "150.00",
         "300.00", "06/09/2026", "Invoice # DNS-2-2627", "LATHA", "1.00"],
        # not a sale
        ["20/07/2026", "Bill # 216", "Autograde INC", "Horn", "", "1.00", "", "-", "150.00",
         "150.00", "07/09/2026", "Vendor Credits # 17", "Autograde", "1.00"],
    ):
        ws.append(row)
    wb.save(path)
    return path


def test_read_cogs(tmp_path):
    c = read_cogs(write_cogs(tmp_path / "Account_Transactions.xlsx"))
    assert c.period == "From 01/09/2026 To 30/09/2026"
    assert c.total == 250 + 100 + 40 + 450 - 60                     # = Zoho's P&L COGS
    assert c.by_invoice() == {"DNS-1-2627": 250, "DNS-2-2627": 100, "DNS-9-2627": 40}
    assert sorted(c.other_kinds()) == [("Purchase bills booked to COGS", 1, 450),
                                       ("Vendor credits", 1, -60)]
    bad = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["Invoice Number", "Total"])
    wb.save(bad)
    with pytest.raises(ZohoCostFileError, match="Account Transactions"):
        read_cogs(bad)
    with pytest.raises(ZohoCostFileError, match="FIFO"):
        read_fifo(bad)
    with pytest.raises(ZohoCostFileError, match=".xlsx or .csv"):
        read_cogs(tmp_path / "x.pdf")


def test_read_fifo(tmp_path):
    rows = read_fifo(write_fifo(tmp_path / "FIFO.xlsx"))
    assert len(rows) == 3                                           # vendor credit left out
    horn = rows[0]
    assert (horn.invoice_no, horn.item, horn.qty, horn.cost, horn.lot) == (
        "DNS-1-2627", "Horn", 1, 150, "Bill # 215")
    assert horn.lot_date == date(2026, 7, 20) and horn.sold_on == date(2026, 9, 6)
    mat = rows[1]
    assert mat.no_stock and mat.cost == 0


@pytest.fixture
def world(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    product(masters, "Horn")
    product(masters, "Mat")
    masters.save("executives", [RowChange(None, dict(
        name="Nandha Kumar", phone="9876543210", branch="HO", active=True))])
    masters.save("cars", [RowChange(None, dict(make="Hyundai", model="Exter",
                                               segment="SUV", active=True))])
    rows = []
    for no, items in (("DNS-1-2627", ["Horn", "Mat"]), ("DNS-2-2627", ["Horn"]),
                      ("DNS-3-2627", ["Mat"])):
        rows += [line(no, "2026-09-06", "Nandha Kumar", "Exter", item, "", "", "goods",
                      1, 1000, 1000, inv_total=1000 * len(items)) for item in items]
    return masters, month(tmp_path, masters, rows), tmp_path


def test_cogs_sheet_and_pnl(world):
    masters, irepo, tmp_path = world
    out = tmp_path / "out"
    out.mkdir()
    r = generate(masters, irepo, InputsRepo(masters), 2026, 9, out, ["Profit & loss"],
                 cogs_path=str(write_cogs(tmp_path / "cogs.xlsx")),
                 fifo_path=str(write_fifo(tmp_path / "fifo.xlsx")),
                 file_names={"COGS": "Account_Transactions.xlsx", "FIFO": "FIFO.xlsx",
                             "other": "x"})
    wb = openpyxl.load_workbook(r.path)
    assert "18 COGS check" in wb.sheetnames
    rows = list(wb["18 COGS check"].iter_rows(values_only=True))
    first = [row[0] for row in rows]
    assert any("Account_Transactions.xlsx" in str(t) for t in first)

    # A. made up like Zoho's P&L figure
    a = first.index("Made up of")
    made = {row[0]: row for row in rows[a + 1:a + 6] if row[0]}
    assert made["Invoices in these reports"][1:3] == (2, 350)
    assert made["Invoices not in this month's invoice export"][1:3] == (1, 40)
    assert made["Purchase bills booked to COGS"][2] == 450
    assert made["Vendor credits"][2] == -60

    # B. summary: DNS-2 agrees, DNS-1 Zoho higher, DNS-3 no COGS posted
    b = first.index("B. Master vs Zoho - summary")
    summary = {row[0]: row for row in rows[b + 2:b + 7] if row[0]}
    assert summary["Agrees"][1:4] == (1, 100, 100)
    assert summary["Zoho higher"][1:4] == (1, 200, 250)
    assert summary["No COGS posted in Zoho"][1:4] == (1, 100, 0)

    # C. invoice by invoice, biggest difference first
    c = first.index("C. Invoice by invoice - biggest difference first")
    assert rows[c + 1][0] == "Invoice no"
    assert [row[0] for row in rows[c + 2:c + 5]] == ["DNS-3-2627", "DNS-1-2627", "DNS-2-2627"]
    one = rows[c + 3]
    head = rows[c + 1]
    assert one[head.index("Zoho FIFO cost of the lines")] == 150
    assert one[head.index("Lines sold with no stock")] == 1
    assert str(one[head.index("Difference (Zoho - master)")]).startswith("=")

    # D. item by item: Horn 150 a unit in Zoho, 100 in the master
    d = next(i for i, t in enumerate(first) if str(t).startswith("D. Item by item"))
    items = {row[0]: row for row in rows[d + 3:d + 6] if row[0]}
    head = rows[d + 2]
    horn = items["Horn"]
    assert horn[head.index("Zoho cost per unit")] == 150
    assert horn[head.index("Master cost per unit")] == 100
    assert horn[head.index("Qty costed from a lot")] == 2
    assert items["Mat"][head.index("Qty sold with no stock")] == 1

    # E. sold with no stock
    e = first.index("E. Sold with no stock in Zoho (costed at 0)")
    assert rows[e + 2][0] == "DNS-1-2627" and rows[e + 2][2] == "Mat" and rows[e + 2][4] == 100

    # Under the P&L: the tool's product cost (kept in the P&L) beside Zoho's
    pnl = list(wb["12 Profit & loss"].iter_rows(values_only=True))
    text = [row[0] for row in pnl]
    at = text.index("Product cost - tool vs Zoho (details: sheet 18 COGS check)")
    assert pnl[at + 2][:3] == ("Product cost of this report's invoices", 400, 350)
    assert pnl[at + 3][0] == "Zoho's P&L cost of goods sold (all postings)" \
        and pnl[at + 3][2] == 780
    assert pnl[text.index("Product cost")][1] == 400                     # P&L unchanged


def test_only_one_file_and_no_file(world, tmp_path):
    masters, irepo, _ = world
    out = tmp_path / "out1"
    out.mkdir()
    inputs = InputsRepo(masters)
    r = generate(masters, irepo, inputs, 2026, 9, out, ["Profit & loss"],
                 fifo_path=str(write_fifo(tmp_path / "fifo.xlsx")))
    rows = list(openpyxl.load_workbook(r.path)["18 COGS check"].iter_rows(values_only=True))
    first = [row[0] for row in rows]
    assert "Made up of" not in first                      # no COGS file: no section A
    c = first.index("C. Invoice by invoice - biggest difference first")
    assert "Zoho FIFO cost" in rows[c + 1]                # Zoho cost = FIFO cost

    r2 = generate(masters, irepo, inputs, 2026, 9, out, ["Profit & loss"])
    assert "18 COGS check" not in openpyxl.load_workbook(r2.path).sheetnames
    with pytest.raises(GenerateError, match="Account Transactions"):
        generate(masters, irepo, inputs, 2026, 9, out, ["Profit & loss"],
                 cogs_path=str(write_fifo(tmp_path / "fifo2.xlsx")))


def test_pdf_has_the_comparison(world, tmp_path):
    from app.data.zoho_costs import ZohoCosts
    from app.reports.pdf_book import write_pdf_workbook
    masters, irepo, _ = world
    d = build_month(masters, irepo, InputsRepo(masters), 2026, 9)
    d.zoho_costs = ZohoCosts(read_cogs(write_cogs(tmp_path / "c.xlsx")),
                             read_fifo(write_fifo(tmp_path / "f.xlsx")))
    ws = openpyxl.load_workbook(write_pdf_workbook(d, [d], None, tmp_path / "p.xlsx"))["Report"]
    text = [row[0] for row in ws.iter_rows(values_only=True)]
    assert "Product cost - master vs Zoho" in text
    assert "The 10 invoices that differ most (all in Excel, sheet 18)" in text


# ---------------------------------------------------------------------------
# Through the web server
# ---------------------------------------------------------------------------
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("itsdangerous")

from tests.test_web_auth import H                              # noqa: E402
from tests.test_web_monthly import M, put_file, read_month, world as web_world  # noqa: E402,F401


def test_cogs_files_through_the_web(web_world, tmp_path, monkeypatch):  # noqa: F811
    from app.reports import pdf_export
    monkeypatch.setattr(pdf_export, "find_libreoffice", lambda: None)
    settings, admin, staff, export = web_world
    cogs = write_cogs(tmp_path / "Account_Transactions.xlsx").read_bytes()
    fifo = write_fifo(tmp_path / "FIFO_Cost_Lot_Tracking.xlsx").read_bytes()
    assert put_file(staff, "cogs", cogs, "Account_Transactions.xlsx").status_code == 403
    wrong = put_file(admin, "cogs", fifo, "FIFO.xlsx")              # FIFO file as the COGS file
    assert wrong.status_code == 400 and "Account Transactions" in wrong.json()["detail"]
    files = put_file(admin, "cogs", cogs, "Account_Transactions.xlsx").json()
    assert files["cogs"]["name"] == "Account_Transactions.xlsx"
    assert put_file(admin, "fifo", fifo, "FIFO.xlsx").json()["fifo"]["name"] == "FIFO.xlsx"
    read_month(admin, export)
    made = admin.post(f"{M}/generate", headers=H, json={"reports": ["Profit & loss"]})
    assert made.status_code == 200, made.text
    assert made.json()["cogs_used"]
    book = openpyxl.load_workbook(io.BytesIO(admin.get(
        f"/api/monthly/runs/{made.json()['run']['id']}/download").content))
    notes = [r[0] for r in book["18 COGS check"].iter_rows(values_only=True, max_row=6)]
    assert any("Account_Transactions.xlsx" in str(n) for n in notes)  # the uploaded name

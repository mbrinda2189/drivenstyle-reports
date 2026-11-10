"""
test_rto.py - Delivery (RTO) list, new-car sheets and executive summary (v0.9.0)
================================================================================

The dealership's list of cars delivered is linked to the invoices by the
last six digits of the VIN, giving penetration, missed opportunities, a
list-vs-invoice check and a consultant scorecard.

From v0.30.0 the list may also be the dealership's own Car Sales Report
(.xls, sheet "Act Del List"): car and OE columns only, no DNS columns. The
tests at the end build a file of that shape and check that the list's own
DNS figures are left out rather than shown as zeros.
"""

from datetime import date

import openpyxl
import pytest

from app.data.database import connect
from app.data.inputs_repo import InputsRepo
from app.data.masters_repo import MastersRepo, RowChange
from app.data.rto_list import RtoFileError, dns_given, model_key, read_rto, vin6
from app.reports.data import build_month
from app.reports.generate import generate
from app.reports.rto_reports import Linked, reconcile_rows
from tests.test_counter_sales import month, product
from tests.test_invoice_export import line

HEAD = ["S.NO", "DELIVERY DATE", "CUSTOMER NAME", "MODEL", "VIN NO", "SALES CONSULTANT",
        "Location", "OE Accessories List", "OE Total Value", "DNS Accessories List",
        "DNS Total Value", "Executive Contribution", "DNS Team Contribution",
        "Executive Incentive", "Remarks"]
CARS = [
    ["1", "01.09.26", "SOUDHA BEGAM", "EXTER", "MALB281CYTM271295", "Karuppusamy", "POL",
     None, 4947, "1)PVC MAT", 2100, "YES", "YES", 50, "-"],              # invoiced, agrees
    ["2", "02.09.26", "MONIKA", "New Venue", "MALFG81ALTD128360", "Tharun K", "OOTY",
     "1)MUD FLAP", None, None, 0, "-", "-", "-", "NO NEED"],              # nothing bought
    ["3", "03.09.26", "RAMESH", "I 20", 279764, "Tharun K", "OOTY",
     None, 0, "1)HORN", 5000, "-", "-", "-", None],                       # in list, no invoice
    ["4", "04.09.26", "LATHA", "All New i20", "MALBH512TTM447779", "Joel", None,
     None, 0, None, 0, "-", "-", "-", "WILL UPDATE LATER"],               # invoiced, list nil
]


def write_list(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEAD)
    for row in CARS:
        ws.append(row)
    wb.save(path)
    return path


def test_vin_and_model_keys():
    assert vin6("MALB281CYTM271295") == "271295" and vin6(310221) == "310221"
    assert vin6("SOUDHA BEGAM 271295") == "271295"
    assert vin6("TN45 BK5353") == "" and vin6("RAVI 9876543210") == ""
    assert model_key("All New i20") == model_key("I 20") == "I20"
    assert model_key("New Venue") == "VENUE" and model_key("Grand i10 Nios") == "NIOS"


def test_read_rto(tmp_path):
    cars = read_rto(write_list(tmp_path / "RTO.xlsx"))
    assert len(cars) == 4
    first = cars[0]
    assert (first.delivered, first.vin6, first.location) == (date(2026, 9, 1), "271295", "POL")
    assert (first.oe_value, first.dns_value, first.incentive) == (4947, 2100, 50)
    assert cars[1].has_oe and not cars[1].has_dns and cars[1].remarks == "NO NEED"
    assert cars[3].location == "(not given)" and cars[3].model_group == "I20"
    other = tmp_path / "x.xlsx"
    openpyxl.Workbook().save(other)
    with pytest.raises(RtoFileError):
        read_rto(other)


@pytest.fixture
def world(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    product(masters, "Horn")
    masters.save("executives", [RowChange(None, dict(
        name="Nandha Kumar", phone="9876543210", branch="HO", active=True))])
    masters.save("cars", [RowChange(None, dict(make="Hyundai", model="Exter",
                                               segment="SUV", active=True))])
    rows = [line(no, "2026-09-06", "Nandha Kumar", "Exter", "Horn", "", "", "goods",
                 1, 2100, 2100, inv_total=2100) for no in ("DNS-1-2627", "DNS-2-2627",
                                                           "DNS-3-2627")]
    for r, (customer, vin) in zip(rows, (("SOUDHA BEGAM 271295", "271295"),
                                         ("LATHA MAHESH 447779", "447779"),
                                         ("WALK IN TN45 BK5353", "TN45 BK5353"))):
        r["Customer Name"], r["CF.VIN / Registration Number"] = customer, vin
    return masters, month(tmp_path, masters, rows), tmp_path


def test_list_is_linked_to_invoices(world):
    masters, irepo, tmp_path = world
    d = build_month(masters, irepo, InputsRepo(masters), 2026, 9)
    link = Linked(d, read_rto(write_list(tmp_path / "RTO.xlsx")))
    assert sorted(i.invoice_no for i in link.linked) == ["DNS-1-2627", "DNS-2-2627"]
    assert [i.invoice_no for i in link.other] == ["DNS-3-2627"]       # walk-in
    assert [link.took_dns(c) for c in link.cars] == [True, False, True, True]
    assert {r["customer"]: r["status"] for r in reconcile_rows(link)} == {
        "SOUDHA BEGAM": "Agrees", "RAMESH": "In the list, no invoice found",
        "LATHA": "Invoiced, list shows no DNS value"}


def test_workbook_with_and_without_the_list(world):
    masters, irepo, tmp_path = world
    out = tmp_path / "out"
    out.mkdir()
    inputs = InputsRepo(masters)
    r = generate(masters, irepo, inputs, 2026, 9, out, ["Profit & loss"],
                 rto_path=str(write_list(tmp_path / "RTO.xlsx")))
    wb = openpyxl.load_workbook(r.path)
    assert wb.sheetnames == ["Cover", "Summary", "12 Profit & loss",
                             "13 New-car penetration", "14 Missed opportunity",
                             "15 RTO list vs invoices", "16 New-car vs other",
                             "17 Consultant scorecard", "Not included"]
    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(values_only=True) if row[0]}
    assert summary["Cars delivered"] == 4
    assert summary["Cars fitted with DNS accessories"] == 3
    assert summary["DNS penetration %"] == 0.75
    missed = [row[1] for row in wb["14 Missed opportunity"].iter_rows(values_only=True)]
    assert "MONIKA" in missed and "LATHA" not in missed
    assert inputs.runs()[0]["rto_path"].endswith("RTO.xlsx")

    # without the list: summary only, and it says so
    r2 = generate(masters, irepo, inputs, 2026, 9, out, ["Profit & loss"])
    wb2 = openpyxl.load_workbook(r2.path) if r2.path != r.path else None
    cells = [row[0] for row in openpyxl.load_workbook(r2.path)["Summary"].iter_rows(
        values_only=True) if row[0]]
    assert any("delivery (RTO) list was not given" in str(c) for c in cells)


# ---------------------------------------------------------------------------
# v0.30.0 - the dealership's Car Sales Report (no DNS columns)
# ---------------------------------------------------------------------------
# The heading row exactly as in Car_Sales_Report_-_Oct26.xls (note the two
# spaces and the "(NDP)" note on the OE value heading).
SALES_HEAD = ["S.NO", "DELIVERY DATE", "CUSTOMER NAME", "MODEL", "VIN NO",
              "SALES CONSULTANT", "Location", "OE ACCESSORIES LIST", "OE Total Value  (NDP)"]
SALES_CARS = [
    [1, date(2026, 9, 1), "SOUDHA BEGAM", "EXTER", "MALB281CYTM271295", "Karuppusamy", "POL",
     None, 4947.5],                                         # invoiced (DNS-1-2627)
    [2, "02-09.2026", "MONIKA", "New Venue", "MALFG81ALTD128360", "Tharun K", "OOTY",
     None, 0],                                              # nothing from DNS
    [3, date(2026, 9, 4), "LATHA", "All New i20", "MALBH512TTM447779", "Joel", "OOTY",
     None, 9303.38],                                        # invoiced (DNS-2-2627)
]


def write_sales_report(path):
    """An .xlsx shaped like the Car Sales Report: "Sheet1" with the headings
    only, then "Act Del List" with the cars, then an unrelated sheet."""
    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    wb.active.append(SALES_HEAD)
    ws = wb.create_sheet("Act Del List")
    ws.append(SALES_HEAD)
    for row in SALES_CARS:
        ws.append(row)
    wb.create_sheet("Part Wise - List").append(["SEQ", "Invoice No", "Part Name"])
    wb.save(path)
    return path


def write_sales_report_xls(path):
    """The same as a real old-style .xls (the client's file is one)."""
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook()
    as_date = xlwt.easyxf(num_format_str="DD-MM-YYYY")
    for name, rows in (("Sheet1", []), ("Act Del List", SALES_CARS)):
        sheet = book.add_sheet(name)
        for c, text in enumerate(SALES_HEAD):
            sheet.write(0, c, text)
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row):
                if isinstance(value, date):
                    sheet.write(r, c, value, as_date)
                elif value is not None:
                    sheet.write(r, c, value)
    book.save(str(path))
    return path


@pytest.mark.parametrize("writer, name", [(write_sales_report, "Car_Sales_Report.xlsx"),
                                          (write_sales_report_xls, "Car_Sales_Report.xls")])
def test_car_sales_report_is_read(tmp_path, writer, name):
    cars = read_rto(writer(tmp_path / name))
    # "Sheet1" (headings, no car) is passed over; "Act Del List" is read.
    assert [c.customer for c in cars] == ["SOUDHA BEGAM", "MONIKA", "LATHA"]
    assert [c.delivered for c in cars] == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 4)]
    assert [c.oe_value for c in cars] == [4947.5, 0, 9303.38]       # "(NDP)" heading read
    assert cars[0].vin6 == "271295" and cars[1].model_group == "VENUE"
    assert not dns_given(cars) and not any(c.dns_columns for c in cars)
    assert all(c.dns_value == 0 and not c.has_dns for c in cars)


def test_old_list_still_has_its_dns_columns(tmp_path):
    cars = read_rto(write_list(tmp_path / "RTO.xlsx"))
    assert dns_given(cars) and all(c.dns_columns for c in cars)


def test_headings_without_cars_and_repeated_headings(tmp_path):
    only_head = tmp_path / "empty.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(SALES_HEAD)
    wb.save(only_head)
    with pytest.raises(RtoFileError, match="no car in it"):
        read_rto(only_head)
    # A list grouped by executive repeats the heading row above each group.
    grouped = tmp_path / "grouped.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in (["OCT DELIVERY REPORT"], ["RIYAS - HO"], SALES_HEAD, SALES_CARS[0],
                [None], ["KARTHICK - CBE"], SALES_HEAD, SALES_CARS[2]):
        ws.append(row)
    wb.save(grouped)
    assert [c.customer for c in read_rto(grouped)] == ["SOUDHA BEGAM", "LATHA"]


def test_workbook_from_the_car_sales_report(world):
    """No DNS columns: penetration comes from the invoices and every 'as per
    list' DNS figure is left out (not shown as 0)."""
    masters, irepo, tmp_path = world
    out = tmp_path / "out"
    out.mkdir()
    r = generate(masters, irepo, InputsRepo(masters), 2026, 9, out, ["Profit & loss"],
                 rto_path=str(write_sales_report(tmp_path / "Car_Sales_Report.xlsx")))
    wb = openpyxl.load_workbook(r.path)
    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(values_only=True) if row[0]}
    assert summary["Cars delivered"] == 3
    assert summary["Cars fitted with DNS accessories"] == 2           # from the invoices
    assert summary["OE accessories value as per list"] == 14250.88
    assert "DNS value as per list" not in summary
    assert "DNS value per car delivered" not in summary
    assert not any("list shows no DNS value" in str(k) for k in summary)

    def cells(sheet):
        return [v for row in wb[sheet].iter_rows(values_only=True) for v in row if v]
    pen = cells("13 New-car penetration")
    assert "Took DNS" in pen and "Invoiced (with GST)" in pen
    assert "DNS value (list)" not in pen and "DNS value per car delivered" not in pen
    assert any("no DNS columns" in str(v) for v in pen)
    rec = cells("15 RTO list vs invoices")
    assert any("nothing to compare" in str(v) for v in rec) and "Agrees" not in rec
    missed = cells("14 Missed opportunity")
    assert "MONIKA" in missed and "By remark" not in missed and "Remark" not in missed
    card = cells("17 Consultant scorecard")
    assert "Incentive (tool)" in card
    assert "Incentive (list)" not in card and "DNS value (list)" not in card

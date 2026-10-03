"""
test_rto.py - Delivery (RTO) list, new-car sheets and executive summary (v0.9.0)
================================================================================

The dealership's list of cars delivered is linked to the invoices by the
last six digits of the VIN, giving penetration, missed opportunities, a
list-vs-invoice check and a consultant scorecard.
"""

from datetime import date

import openpyxl
import pytest

from app.data.database import connect
from app.data.inputs_repo import InputsRepo
from app.data.masters_repo import MastersRepo, RowChange
from app.data.rto_list import RtoFileError, model_key, read_rto, vin6
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
    assert summary["Cars that took DNS accessories"] == 3
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

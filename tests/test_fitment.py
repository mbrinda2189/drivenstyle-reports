"""
test_fitment.py - v0.33.0: floor mat and sunfilm against the cars delivered
==========================================================================

The client (via Brinda, 10-11-2026) asked for, every month: cars delivered;
OE full mat and non-OE (DNS) full mat - qty and % of cars delivered; sunfilm
side & rear and front - qty and % of cars delivered.

The delivery list below is shaped like the dealership's Car Sales Report:
"Act Del List" with the cars, "Part Wise - List" with the dealer's own
accessory lines (WIN = VIN, Invoice Status C = cancelled) and a counter
sale sheet with "VIN No". Three DNS invoices: two on delivered cars, one
walk-in (not counted - it is not a car delivered this month).
"""

from datetime import date

import openpyxl
import pytest

from app.data.database import connect
from app.data.inputs_repo import InputsRepo
from app.data.masters_repo import MastersRepo, RowChange
from app.data.rto_list import read_rto
from app.reports.data import build_month
from app.reports.fitment import dns_kind, fitments, oe_full_mat
from app.reports.generate import generate
from app.reports.pdf_book import write_pdf_workbook
from app.reports.rto_reports import Linked
from tests.test_counter_sales import month, product
from tests.test_invoice_export import line
from tests.test_rto import SALES_CARS, SALES_HEAD

MAT = "Creta - PVC Full Floor Mat + Labour Extra"
SIDE = "Sunfilm - Side and Rear - GEN"
FRONT = "Sunfilm - Nano Ceramic - Front (SK)"
ROLL = "Sunfilm-Blaupunkt-70(1000sqft Roll)"
PART_HEAD = ["SEQ", "Invoice No RO Bill No", "RO NO", "WIN", "Sales Date", "Invoice Status",
             "Part Name", "Qty", "Unit Price"]
PARTS = [  # the dealer's accessory lines
    [1, "B1", "R1", "MALB281CYTM271295", date(2026, 9, 1), "N ", "FULL FLOOR MAT   ", 1, 900],
    [2, "B2", "R2", "MALFG81ALTD128360", date(2026, 9, 2), "C ", "FULL FLOOR MAT", 1, 900],
    [3, "B2", "R2", "MALFG81ALTD128360", date(2026, 9, 2), "N ", "3D MAT", 1, 2500],
    [4, "B3", "R3", "MALBH512TTM447779", date(2026, 9, 4), "F ", "FULL FLOOR MAT - NIOS & AURA",
     1, 0],
    [5, "B4", "R4", "MALXX000000999999", date(2026, 9, 5), "N ", "FULL FLOOR MAT", 1, 900],
]
COUNTER_HEAD = ["SEQ", "Invoice No RO Bill No", "Sales Date", "VIN No", "Part Name", "Qty"]
COUNTER = [[1, "S1", date(2026, 9, 3), "MALB281CYTM271295   ", "3D BOOT MAT", 1]]


def write_report(path):
    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    wb.active.append(SALES_HEAD)
    for name, head, rows in (("Act Del List", SALES_HEAD, SALES_CARS),
                             ("Part Wise - List", PART_HEAD, PARTS),
                             ("CBE - CS SEP'26", COUNTER_HEAD, COUNTER)):
        ws = wb.create_sheet(name)
        ws.append(head)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


def test_rules():
    assert oe_full_mat("FULL FLOOR MAT - NIOS & AURA") and oe_full_mat("full  floor mat")
    assert not oe_full_mat("3D MAT") and not oe_full_mat("DUAL LAYER MAT")
    assert dns_kind(MAT) == "dns_mat"
    assert dns_kind(SIDE) == "film_side" and dns_kind("Sunfilm Diamond70 Side & Rear -(SK)") \
        == "film_side"
    assert dns_kind(FRONT) == "film_front"
    assert dns_kind("Lumar Sunfilm – Front Windshield (All Cars)") == "film_front"
    assert dns_kind("Sunfilm Diamond-70 Windshield (SK)") == "film_front"
    assert dns_kind(ROLL) is None                                  # a roll is neither
    assert dns_kind("Labour Charges for Sunfilm - Front") is None  # a labour charge
    assert dns_kind("Labour Charges PVC/MLF/Luxury Floor Mat (Venue / Exter / Creta)") is None
    assert dns_kind("Horn") is None


def test_dealer_parts_are_read_per_car(tmp_path):
    cars = read_rto(write_report(tmp_path / "Car_Sales_Report.xlsx"))
    by = {c.customer: c.oe_parts for c in cars}
    assert by["SOUDHA BEGAM"] == {"FULL FLOOR MAT": 1, "3D BOOT MAT": 1}   # both sheets
    assert by["MONIKA"] == {"3D MAT": 1}                                   # "C" left out
    assert by["LATHA"] == {"FULL FLOOR MAT - NIOS & AURA": 1}              # "F" counts


@pytest.fixture
def world(tmp_path):
    masters = MastersRepo(connect(":memory:"))
    for name in (MAT, SIDE, FRONT, ROLL):
        product(masters, name)
    masters.save("executives", [RowChange(None, dict(
        name="Nandha Kumar", phone="9876543210", branch="HO", active=True))])
    masters.save("cars", [RowChange(None, dict(make="Hyundai", model="Creta",
                                               segment="SUV", active=True))])

    def bill(no, customer, vin, items):
        total = sum(q * 1000 for _, q in items)
        rows = [line(no, "2026-09-06", "Nandha Kumar", "Creta", item, "", "", "goods",
                     q, 1000, q * 1000, inv_total=total) for item, q in items]
        for r in rows:
            r["Customer Name"], r["CF.VIN / Registration Number"] = customer, vin
        return rows
    rows = (bill("DNS-1-2627", "SOUDHA BEGAM 271295", "271295",
                 [(MAT, 1), (SIDE, 1), (FRONT, 1), (ROLL, 1)])
            + bill("DNS-2-2627", "LATHA 447779", "447779", [(MAT, 2)])
            + bill("DNS-3-2627", "WALK IN TN45 BK5353", "TN45 BK5353", [(MAT, 1), (SIDE, 1)]))
    return masters, month(tmp_path, masters, rows), tmp_path


def test_fitment_figures(world):
    masters, irepo, tmp_path = world
    d = build_month(masters, irepo, InputsRepo(masters), 2026, 9)
    assert len(d.invoices) == 3 and not d.left_out
    link = Linked(d, read_rto(write_report(tmp_path / "Car_Sales_Report.xlsx")))
    rows = {r["key"]: r for r in fitments(link)}
    assert (rows["oe_mat"]["cars"], rows["oe_mat"]["qty"]) == (2, 2)      # SOUDHA, LATHA
    assert (rows["dns_mat"]["cars"], rows["dns_mat"]["qty"]) == (2, 3)    # walk-in not counted
    assert (rows["film_side"]["cars"], rows["film_front"]["cars"]) == (1, 1)
    assert rows["oe_mat"]["pct"] == 2 / 3 and rows["film_side"]["delivered"] == 3


def test_fitment_in_the_workbook_pdf_and_trend(world):
    masters, irepo, tmp_path = world
    out = tmp_path / "out"
    out.mkdir()
    inputs = InputsRepo(masters)
    report = write_report(tmp_path / "Car_Sales_Report.xlsx")
    r = generate(masters, irepo, inputs, 2026, 9, out,
                 ["Profit & loss", "Trend analysis (month on month)"], rto_path=str(report))
    wb = openpyxl.load_workbook(r.path)

    pen = list(wb["13 New-car penetration"].iter_rows(values_only=True))
    at = [row[0] for row in pen].index("Floor mat and sunfilm - cars delivered")
    head = pen[at + 2]
    assert head[:5] == ("Particulars", "Cars", "% of cars delivered", "Qty", "Cars delivered")
    body = {row[0]: row for row in pen[at + 3:at + 7]}
    assert body["Full floor mat – OE (dealer)"][1] == 2
    assert body["Full floor mat – DNS"][3] == 3
    assert str(body["Sunfilm front – DNS"][2]).startswith("=IF(")          # % as a formula

    summary = {row[0]: row for row in wb["Summary"].iter_rows(values_only=True) if row[0]}
    assert summary["Full floor mat – DNS"][1:4] == (2, 2 / 3, 3)
    assert summary["Sunfilm side & rear – DNS"][1] == 1

    saved = inputs.rto_months()["2026-09"]
    assert (saved["oe_mat"], saved["dns_mat"], saved["film_side"], saved["film_front"]) \
        == (2, 2, 1, 1)
    trend = {row[0]: row for row in wb["4 Trend"].iter_rows(values_only=True) if row[0]}
    assert trend["Full floor mat – OE (dealer) %"][1] == 2 / 3

    d = build_month(masters, irepo, inputs, 2026, 9)
    pdf = openpyxl.load_workbook(write_pdf_workbook(d, [d], None, tmp_path / "p.xlsx",
                                                    rto=read_rto(report)))["Report"]
    text = [row[0] for row in pdf.iter_rows(values_only=True)]
    at = text.index("Floor mat and sunfilm - cars delivered")
    assert "Full floor mat – OE (dealer)" in text[at:at + 8]


def test_months_before_v033_show_blank_in_the_trend():
    """A month generated before v0.33.0 has no counts: blank, not 0 %."""
    from app.reports.trend import ROWS, _total
    figures = [dict(cars=10, oe_mat=None, dns_mat=None, film_side=None, film_front=None),
               dict(cars=20, oe_mat=4, dns_mat=2, film_side=1, film_front=0)]
    get = dict((label, key) for label, key, *_ in ROWS)["Full floor mat – OE (dealer) %"]
    assert get(figures[0]) == "" and get(figures[1]) == 0.2
    full = {k: None for k in ("invoices", "sales", "discount", "product", "service", "cost",
                              "labour", "gp", "indirect", "net", "packages", "incentive",
                              "internal", "took")}
    total = _total([dict(full, **f) for f in figures])
    assert get(total) == 0.2                     # 4 of the 20 cars that HAVE the figures

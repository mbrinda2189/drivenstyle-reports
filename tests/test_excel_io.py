"""
test_excel_io.py - Tests for reading and exporting master sheets
================================================================
"""

import pytest
from openpyxl import Workbook

from app.data.excel_io import (
    ImportFileError, convert_rows, convert_value, export_rows, read_sheet,
    suggest_mapping)
from app.data.master_defs import CARS, EXECUTIVES, PRODUCTS


def make_xlsx(path, rows):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    wb.save(path)
    return path


def test_finds_heading_row_below_a_title(tmp_path):
    f = make_xlsx(tmp_path / "p.xlsx", [
        ["Drive N Style - Product Master"], [],
        ["Item Name", "HSN Code", "Rate", "Cost", "Labour (Y/N)", "Labour Charges"],
        ["Dash Cam", 8525.0, 8900, 5200, "Y", 400],
        [None, None, None, None, None, None]])
    sheet = read_sheet(f, PRODUCTS)
    assert sheet.header_row == 3 and len(sheet.rows) == 1
    mapping = suggest_mapping(PRODUCTS, sheet.headers)
    assert mapping["name"] == "Item Name"
    assert mapping["selling_price"] == "Rate"
    assert mapping["has_labour"] == "Labour (Y/N)"
    assert mapping["labour_charge"] == "Labour Charges"
    assert mapping["sku"] is None
    [rec], problems = convert_rows(PRODUCTS, sheet, mapping)
    assert problems == []
    assert rec["hsn_sac"] == "8525" and rec["has_labour"] is True
    assert rec["selling_price"] == 8900.0 and "sku" not in rec


def test_remembered_mapping_wins(tmp_path):
    f = make_xlsx(tmp_path / "e.xlsx", [["Staff", "Contact"], ["Arun", 98765]])
    sheet = read_sheet(f, EXECUTIVES)
    mapping = suggest_mapping(EXECUTIVES, sheet.headers,
                              {"name": "Staff", "phone": "Contact"})
    assert mapping["name"] == "Staff" and mapping["phone"] == "Contact"


def test_bad_values_are_reported_with_row_numbers(tmp_path):
    f = make_xlsx(tmp_path / "p.xlsx", [
        ["Product name", "Selling price", "Category"],
        ["A", "abc", "Goods"], ["B", "₹ 1,200.50", "services"]])
    sheet = read_sheet(f, PRODUCTS)
    records, problems = convert_rows(PRODUCTS, sheet,
                                     suggest_mapping(PRODUCTS, sheet.headers))
    assert len(records) == 1 and records[0]["selling_price"] == 1200.5
    assert records[0]["category"] == "Service"
    assert problems[0].startswith("Row 2:") and "not an amount" in problems[0]


@pytest.mark.parametrize("value, expected", [
    ("Yes", True), ("n", False), ("✓", True), (None, False), (1, True)])
def test_yes_no_values(value, expected):
    assert convert_value(PRODUCTS.get_field("has_labour"), value) is expected


def test_open_choice_accepts_new_segment():
    assert convert_value(CARS.get_field("segment"), "Crossover") == "Crossover"
    assert convert_value(CARS.get_field("segment"), "suv") == "SUV"


def test_old_xls_and_other_files_are_refused(tmp_path):
    for name in ("m.xls", "m.pdf"):
        (tmp_path / name).write_bytes(b"x")
        with pytest.raises(ImportFileError):
            read_sheet(tmp_path / name, PRODUCTS)


def test_csv_import(tmp_path):
    f = tmp_path / "cars.csv"
    f.write_text("Brand,Car Model,Body Type\nTata,Nexon,Compact SUV\n",
                 encoding="utf-8")
    sheet = read_sheet(f, CARS)
    [rec], _ = convert_rows(CARS, sheet, suggest_mapping(CARS, sheet.headers))
    assert rec == {"_row": 2, "make": "Tata", "model": "Nexon",
                   "segment": "Compact SUV"}


def test_export_can_be_imported_back(tmp_path, repo):
    repo.import_records("products", [{"_row": 2, "name": "Mat", "sku": "M1",
                                      "hsn_sac": "5705", "selling_price": 900.0}])
    out = tmp_path / "export.xlsx"
    export_rows(PRODUCTS, repo.list_rows("products"), out)
    sheet = read_sheet(out, PRODUCTS)
    mapping = suggest_mapping(PRODUCTS, sheet.headers)
    [rec], problems = convert_rows(PRODUCTS, sheet, mapping)
    assert problems == [] and rec["selling_price"] == 900.0 and rec["sku"] == "M1"


def test_first_of_next_month_rolls_over_the_year():
    from datetime import date
    from app.utils import first_of_next_month
    assert first_of_next_month(date(2026, 12, 15)) == date(2027, 1, 1)
    assert first_of_next_month(date(2026, 9, 25)) == date(2026, 10, 1)

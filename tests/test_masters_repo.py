"""
test_masters_repo.py - Tests for saving, importing and dated rates
==================================================================

Run all tests from the project folder with:   python -m pytest
"""

from datetime import date

import pytest

from app.data.database import SCHEMA_VERSION, connect, schema_version
from app.data.masters_repo import (
    MasterError, RowChange, car_key, infer_category, name_key)


def product(name, sp=1000.0, cp=600.0, labour=100.0, **extra):
    """Full set of product values, as the Masters screen would send them."""
    values = dict(sku="", name=name, hsn_sac="", category="Product",
                  selling_price=sp, cost_price=cp, has_labour=labour > 0,
                  labour_charge=labour, active=True)
    values.update(extra)
    return values


# --- helpers -------------------------------------------------------------
def test_name_key_ignores_case_spaces_and_dash_style():
    assert name_key("Seat Cover – Premium") == name_key("seat  cover - premium")


def test_car_key_combines_make_and_model():
    assert car_key("Tata", " Nexon ") == "tata|nexon"


@pytest.mark.parametrize("code, expected", [
    ("998729", "Service"), ("9987", "Service"), ("8708", "Product"),
    ("", "Product"), ("87.08", "Product")])
def test_infer_category_from_hsn_sac(code, expected):
    assert infer_category(code) == expected


def test_new_database_is_at_current_schema(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert schema_version(conn) == SCHEMA_VERSION
    conn.close()
    assert schema_version(connect(tmp_path / "t.db")) == SCHEMA_VERSION


# --- saving from the screen ----------------------------------------------
def test_add_product_and_read_back(repo):
    repo.save("products", [RowChange(None, product("Dash Cam"), date(2026, 4, 1))])
    [row] = repo.list_rows("products")
    assert row["name"] == "Dash Cam"
    assert row["selling_price"] == 1000.0
    assert row["effective_from"] == date(2026, 4, 1)


def test_rate_change_keeps_history(repo):
    repo.save("products", [RowChange(None, product("Dash Cam"), date(2026, 4, 1))])
    pid = repo.list_rows("products")[0]["id"]
    repo.save("products", [RowChange(pid, product("Dash Cam", sp=1200.0),
                                     date(2026, 10, 1))])
    assert repo.rate_on(pid, date(2026, 9, 15))["selling_price"] == 1000.0
    assert repo.rate_on(pid, date(2026, 10, 1))["selling_price"] == 1200.0
    assert len(repo.rate_history(pid)) == 2
    assert repo.list_rows("products")[0]["selling_price"] == 1200.0


def test_rate_before_first_change_uses_first_rate(repo):
    repo.save("products", [RowChange(None, product("Dash Cam"), date(2026, 10, 1))])
    pid = repo.list_rows("products")[0]["id"]
    assert repo.rate_on(pid, date(2026, 5, 1))["selling_price"] == 1000.0


def test_duplicate_name_is_refused(repo):
    repo.save("products", [RowChange(None, product("Dash Cam"))])
    with pytest.raises(MasterError) as err:
        repo.save("products", [RowChange(None, product("dash  cam"))])
    assert "already exists" in err.value.messages[0]


def test_duplicate_sku_is_refused(repo):
    repo.save("products", [RowChange(None, product("A", sku="X1"))])
    with pytest.raises(MasterError):
        repo.save("products", [RowChange(None, product("B", sku="x1"))])


def test_required_and_negative_checks(repo):
    with pytest.raises(MasterError) as err:
        repo.save("products", [RowChange(None, product("", sp=-5))])
    text = " ".join(err.value.messages)
    assert "Product name is required" in text and "negative" in text


def test_nothing_saved_when_one_row_fails(repo):
    with pytest.raises(MasterError):
        repo.save("executives", [
            RowChange(None, dict(name="Arun", phone="", city="", active=True)),
            RowChange(None, dict(name="", phone="", city="", active=True))])
    assert repo.list_rows("executives") == []


def test_inactive_rows_are_listed_last(repo):
    repo.save("cars", [
        RowChange(None, dict(make="Tata", model="Nexon", segment="SUV", active=False)),
        RowChange(None, dict(make="Kia", model="Seltos", segment="SUV", active=True))])
    rows = repo.list_rows("cars")
    assert [r["model"] for r in rows] == ["Seltos", "Nexon"]
    assert repo.counts()["cars"] == 1


# --- importing -----------------------------------------------------------
def test_import_adds_then_updates_rates(repo):
    recs = [{"_row": 2, "name": "Dash Cam", "selling_price": 1000.0,
             "cost_price": 600.0, "labour_charge": 0.0}]
    first = repo.import_records("products", recs, date(2026, 4, 1))
    assert first.added == 1

    recs[0]["selling_price"] = 1100.0
    second = repo.import_records("products", recs, date(2026, 10, 1))
    assert (second.updated, second.rates_changed) == (1, 1)
    pid = repo.list_rows("products")[0]["id"]
    assert repo.rate_on(pid, date(2026, 6, 1))["selling_price"] == 1000.0

    third = repo.import_records("products", recs, date(2026, 11, 1))
    assert third.unchanged == 1 and third.rates_changed == 0


def test_import_keeps_unmatched_fields(repo):
    repo.import_records("products", [{"_row": 2, "name": "Mat", "sku": "M1",
                                      "hsn_sac": "5705", "cost_price": 500.0}],
                        date(2026, 4, 1))
    # Second sheet has no HSN or cost column: those must stay as they were.
    repo.import_records("products", [{"_row": 2, "name": "Mat", "sku": "M1",
                                      "selling_price": 900.0}], date(2026, 5, 1))
    row = repo.list_rows("products")[0]
    assert (row["hsn_sac"], row["cost_price"], row["selling_price"]) == \
        ("5705", 500.0, 900.0)


def test_import_matches_by_sku_before_name(repo):
    repo.import_records("products", [{"_row": 2, "name": "Old name", "sku": "S1"}])
    result = repo.import_records("products", [{"_row": 2, "name": "New name",
                                               "sku": "S1"}])
    assert result.updated == 1
    assert [r["name"] for r in repo.list_rows("products")] == ["New name"]


def test_import_infers_category_and_labour(repo):
    repo.import_records("products", [
        {"_row": 2, "name": "Film", "hsn_sac": "998729", "labour_charge": 300.0},
        {"_row": 3, "name": "Mat", "hsn_sac": "5705"}])
    rows = {r["name"]: r for r in repo.list_rows("products")}
    assert rows["Film"]["category"] == "Service" and rows["Film"]["has_labour"]
    assert rows["Mat"]["category"] == "Product" and not rows["Mat"]["has_labour"]


def test_import_reports_repeated_and_empty_rows(repo):
    result = repo.import_records("executives", [
        {"_row": 2, "name": "Arun", "city": "Tuticorin"},
        {"_row": 3, "name": ""},
        {"_row": 4, "name": "arun", "city": "Madurai"}])
    assert result.added == 1 and len(result.skipped) == 1
    assert "repeats row 2" in result.warnings[0]
    assert repo.list_rows("executives")[0]["city"] == "Madurai"


def test_import_reactivates_inactive_rows(repo):
    repo.save("executives", [RowChange(None, dict(name="Arun", phone="",
                                                  city="", active=False))])
    repo.import_records("executives", [{"_row": 2, "name": "Arun"}])
    assert repo.list_rows("executives")[0]["active"] is True


def test_mapping_is_remembered(repo):
    repo.set_mapping("cars", {"make": "Brand", "model": "Car Model", "segment": None})
    assert repo.get_mapping("cars") == {"make": "Brand", "model": "Car Model"}

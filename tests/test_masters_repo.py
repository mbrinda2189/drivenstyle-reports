"""
test_masters_repo.py - Tests for saving, importing, dated rates, duplicates,
bulk actions and the audit log
=========================================================================

Run all tests from the project folder with:   python -m pytest
"""

import sqlite3
from datetime import date

import pytest

from app.data.database import SCHEMA_VERSION, connect, schema_version
from app.data.masters_repo import (
    MasterError, RowChange, car_key, infer_category, name_key, phone_key)


def product(name, sp=1000.0, cp=600.0, labour=100.0, **extra):
    """Full set of product values, as the Masters screen would send them."""
    values = dict(sku="", name=name, hsn_sac="", category="Product",
                  incentive_group="", selling_price=sp, cost_price=cp,
                  has_labour=labour > 0, labour_charge=labour, active=True)
    values.update(extra)
    return values


def executive(name, phone, branch="Tuticorin", active=True):
    return dict(name=name, phone=phone, branch=branch, active=active)


def incentive(name, amount=300.0, bill=6000.0, active=True):
    return dict(name=name, incentive_amount=amount, bill_value=bill, active=active)


# --- helpers -------------------------------------------------------------
def test_name_key_ignores_case_spaces_and_dash_style():
    assert name_key("Seat Cover – Premium") == name_key("seat  cover - premium")


def test_car_key_combines_make_and_model():
    assert car_key("Tata", " Nexon ") == "tata|nexon"


@pytest.mark.parametrize("raw, key", [
    ("+91 98765 43210", "9876543210"), ("098765-43210", "9876543210"),
    ("9876543210", "9876543210"), ("", "")])
def test_phone_key(raw, key):
    assert phone_key(raw) == key


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
    assert row["name"] == "Dash Cam" and row["selling_price"] == 1000.0
    assert row["effective_from"] == date(2026, 4, 1)


def test_rate_change_keeps_history(repo):
    repo.save("products", [RowChange(None, product("Dash Cam"), date(2026, 4, 1))])
    pid = repo.list_rows("products")[0]["id"]
    repo.save("products", [RowChange(pid, product("Dash Cam", sp=1200.0),
                                     date(2026, 10, 1))])
    assert repo.rate_on("products", pid, date(2026, 9, 15))["selling_price"] == 1000.0
    assert repo.rate_on("products", pid, date(2026, 10, 1))["selling_price"] == 1200.0
    assert len(repo.rate_history("products", pid)) == 2


def test_rate_before_first_change_uses_first_rate(repo):
    repo.save("products", [RowChange(None, product("Dash Cam"), date(2026, 10, 1))])
    pid = repo.list_rows("products")[0]["id"]
    assert repo.rate_on("products", pid, date(2026, 5, 1))["selling_price"] == 1000.0


def test_duplicate_product_name_is_refused(repo):
    repo.save("products", [RowChange(None, product("Dash Cam"))])
    with pytest.raises(MasterError) as err:
        repo.save("products", [RowChange(None, product("dash  cam"))])
    assert "already used" in err.value.messages[0]


def test_duplicate_sku_is_refused(repo):
    repo.save("products", [RowChange(None, product("A", sku="X1"))])
    with pytest.raises(MasterError):
        repo.save("products", [RowChange(None, product("B", sku="x1"))])


def test_duplicates_within_one_save_are_refused(repo):
    with pytest.raises(MasterError) as err:
        repo.save("incentives", [RowChange(None, incentive("PPF")),
                                 RowChange(None, incentive("ppf"))])
    assert "entered twice" in " ".join(err.value.messages)


def test_required_and_negative_checks(repo):
    with pytest.raises(MasterError) as err:
        repo.save("products", [RowChange(None, product("", sp=-5))])
    text = " ".join(err.value.messages)
    assert "Product name is required" in text and "negative" in text


def test_nothing_saved_when_one_row_fails(repo):
    with pytest.raises(MasterError):
        repo.save("executives", [RowChange(None, executive("Arun", "9876543210")),
                                 RowChange(None, executive("", "9876500000"))])
    assert repo.list_rows("executives") == []


# --- sales executives: unique by contact number ---------------------------
def test_same_name_different_numbers_is_allowed(repo):
    repo.save("executives", [RowChange(None, executive("Arun", "9876543210")),
                             RowChange(None, executive("Arun", "9876500000", "Madurai"))])
    assert len(repo.list_rows("executives")) == 2


def test_same_number_written_differently_is_refused(repo):
    repo.save("executives", [RowChange(None, executive("Arun", "9876543210"))])
    with pytest.raises(MasterError) as err:
        repo.save("executives", [RowChange(None, executive("Karthik", "+91 98765 43210"))])
    assert "contact number is already used by “Arun" in err.value.messages[0]


def test_contact_no_is_required(repo):
    with pytest.raises(MasterError):
        repo.save("executives", [RowChange(None, executive("Arun", ""))])


# --- incentives and the product link ---------------------------------------
def test_product_links_to_incentive_group(repo):
    repo.save("incentives", [RowChange(None, incentive("Dashcam", 300, 12500))])
    repo.save("products", [RowChange(None, product("Dash Camera 4K",
                                                   incentive_group="dashcam"))])
    assert repo.list_rows("products")[0]["incentive_group"] == "Dashcam"


def test_unknown_incentive_group_is_refused(repo):
    with pytest.raises(MasterError) as err:
        repo.save("products", [RowChange(None, product("X", incentive_group="Nope"))])
    assert "not in the Incentives master" in err.value.messages[0]


def test_incentive_amounts_are_dated(repo):
    repo.save("incentives", [RowChange(None, incentive("PPF", 3000, 70000),
                                       date(2026, 4, 1))])
    iid = repo.list_rows("incentives")[0]["id"]
    repo.save("incentives", [RowChange(iid, incentive("PPF", 3500, 70000),
                                       date(2026, 10, 1))])
    assert repo.rate_on("incentives", iid, date(2026, 9, 30))["incentive_amount"] == 3000
    assert repo.rate_on("incentives", iid, date(2026, 10, 1))["incentive_amount"] == 3500


def test_deleting_incentive_unlinks_products(repo):
    repo.save("incentives", [RowChange(None, incentive("Dashcam"))])
    repo.save("products", [RowChange(None, product("Cam", incentive_group="Dashcam"))])
    iid = repo.list_rows("incentives")[0]["id"]
    assert repo.delete("incentives", [iid]) == 1
    assert repo.list_rows("products")[0]["incentive_group"] == ""
    unlink = repo.audit_entries(master="products", action="Edited")
    assert unlink[0]["field"] == "Incentive group" and unlink[0]["old_value"] == "Dashcam"


# --- bulk actions ------------------------------------------------------------
def test_delete_and_set_active(repo):
    repo.save("cars", [RowChange(None, dict(make="Tata", model="Nexon", segment="SUV", active=True)),
                       RowChange(None, dict(make="Kia", model="Seltos", segment="SUV", active=True))])
    ids = [r["id"] for r in repo.list_rows("cars")]
    assert repo.set_active("cars", ids, False) == 2
    assert repo.set_active("cars", ids, False) == 0          # already inactive
    assert repo.counts()["cars"] == 0
    assert repo.delete("cars", ids) == 2
    assert repo.list_rows("cars") == []


def test_deleting_product_removes_its_rate_history(repo):
    repo.save("products", [RowChange(None, product("Mat"))])
    pid = repo.list_rows("products")[0]["id"]
    repo.delete("products", [pid])
    assert repo.conn.execute("SELECT COUNT(*) FROM product_rates").fetchone()[0] == 0


# --- audit log ----------------------------------------------------------------
def test_every_change_is_logged(repo):
    repo.user = "brinda"
    repo.save("executives", [RowChange(None, executive("Arun", "9876543210"))])
    eid = repo.list_rows("executives")[0]["id"]
    repo.save("executives", [RowChange(eid, executive("Arun K", "9876543210", "Madurai"))])
    repo.set_active("executives", [eid], False)
    repo.delete("executives", [eid])
    log = repo.audit_entries(master="executives")
    actions = [(e["action"], e["field"]) for e in reversed(log)]
    assert actions == [("Added", ""), ("Edited", "Name"), ("Edited", "Branch"),
                       ("Deactivated", ""), ("Deleted", "")]
    edited_branch = next(e for e in log if e["field"] == "Branch")
    assert (edited_branch["old_value"], edited_branch["new_value"]) == ("Tuticorin", "Madurai")
    assert all(e["user"] == "brinda" for e in log)
    assert "Contact no: 9876543210" in log[0]["old_value"]      # Deleted row


def test_rate_change_logged_with_date(repo):
    repo.save("products", [RowChange(None, product("Mat"), date(2026, 4, 1))])
    pid = repo.list_rows("products")[0]["id"]
    repo.save("products", [RowChange(pid, product("Mat", sp=1100.0), date(2026, 10, 1))])
    [entry] = repo.audit_entries(master="products", action="Edited")
    assert entry["field"] == "Selling price (₹)"
    assert entry["new_value"] == "1,100.00 from 01-10-2026"


def test_unchanged_save_writes_no_log(repo):
    repo.save("cars", [RowChange(None, dict(make="Tata", model="Nexon", segment="", active=True))])
    cid = repo.list_rows("cars")[0]["id"]
    repo.save("cars", [RowChange(cid, dict(make="Tata", model="Nexon", segment="", active=True))])
    assert len(repo.audit_entries()) == 1


def test_audit_log_cannot_be_changed(repo):
    repo.save("cars", [RowChange(None, dict(make="Tata", model="Nexon", segment="", active=True))])
    for sql in ("UPDATE audit_log SET user = 'x'", "DELETE FROM audit_log"):
        with pytest.raises(sqlite3.DatabaseError):
            with repo.conn:
                repo.conn.execute(sql)
    assert len(repo.audit_entries()) == 1


def test_audit_filters(repo):
    repo.save("cars", [RowChange(None, dict(make="Tata", model="Nexon", segment="", active=True))])
    repo.save("incentives", [RowChange(None, incentive("PPF"))])
    assert len(repo.audit_entries(master="cars")) == 1
    assert len(repo.audit_entries(text="ppf")) == 1
    assert len(repo.audit_entries(date_from=date.today(), date_to=date.today())) == 2
    assert repo.audit_entries(date_to=date(2000, 1, 1)) == []


# --- importing -----------------------------------------------------------------
def test_import_adds_then_updates_rates(repo):
    recs = [{"_row": 2, "name": "Dash Cam", "selling_price": 1000.0,
             "cost_price": 600.0, "labour_charge": 0.0}]
    assert repo.import_records("products", recs, date(2026, 4, 1)).added == 1
    recs[0]["selling_price"] = 1100.0
    second = repo.import_records("products", recs, date(2026, 10, 1))
    assert (second.updated, second.rates_changed) == (1, 1)
    pid = repo.list_rows("products")[0]["id"]
    assert repo.rate_on("products", pid, date(2026, 6, 1))["selling_price"] == 1000.0
    third = repo.import_records("products", recs, date(2026, 11, 1))
    assert third.unchanged == 1 and third.rates_changed == 0


def test_import_keeps_unmatched_fields(repo):
    repo.import_records("products", [{"_row": 2, "name": "Mat", "sku": "M1",
                                      "hsn_sac": "5705", "cost_price": 500.0}],
                        date(2026, 4, 1))
    repo.import_records("products", [{"_row": 2, "name": "Mat", "sku": "M1",
                                      "selling_price": 900.0}], date(2026, 5, 1))
    row = repo.list_rows("products")[0]
    assert (row["hsn_sac"], row["cost_price"], row["selling_price"]) == \
        ("5705", 500.0, 900.0)


def test_import_matches_by_sku_before_name(repo):
    repo.import_records("products", [{"_row": 2, "name": "Old name", "sku": "S1"}])
    result = repo.import_records("products", [{"_row": 2, "name": "New name", "sku": "S1"}])
    assert result.updated == 1
    assert [r["name"] for r in repo.list_rows("products")] == ["New name"]


def test_import_infers_category_and_labour(repo):
    repo.import_records("products", [
        {"_row": 2, "name": "Film", "hsn_sac": "998729", "labour_charge": 300.0},
        {"_row": 3, "name": "Mat", "hsn_sac": "5705"}])
    rows = {r["name"]: r for r in repo.list_rows("products")}
    assert rows["Film"]["category"] == "Service" and rows["Film"]["has_labour"]
    assert rows["Mat"]["category"] == "Product" and not rows["Mat"]["has_labour"]


def test_import_executives_by_contact_number(repo):
    result = repo.import_records("executives", [
        {"_row": 2, "name": "Arun", "phone": "9876543210", "branch": "Tuticorin"},
        {"_row": 3, "name": "Priya", "phone": ""},
        {"_row": 4, "name": "Arun", "phone": "9876500000", "branch": "Madurai"},
        {"_row": 5, "name": "Arun Kumar", "phone": "+91 98765 43210"}])
    assert result.added == 2 and len(result.skipped) == 1
    assert "repeats row 2" in result.warnings[0]
    names = sorted(r["name"] for r in repo.list_rows("executives"))
    assert names == ["Arun", "Arun Kumar"]


def test_import_unknown_incentive_group_is_left_blank(repo):
    repo.import_records("incentives", [{"_row": 2, "name": "PPF",
                                        "incentive_amount": 3000.0,
                                        "bill_value": 70000.0}])
    result = repo.import_records("products", [
        {"_row": 2, "name": "PPF Full Body", "incentive_group": "ppf"},
        {"_row": 3, "name": "Mat", "incentive_group": "Mats"}])
    assert result.added == 2 and "Mats" in result.warnings[0]
    rows = {r["name"]: r["incentive_group"] for r in repo.list_rows("products")}
    assert rows == {"PPF Full Body": "PPF", "Mat": ""}


def test_import_reactivates_inactive_rows(repo):
    repo.save("executives", [RowChange(None, executive("Arun", "9876543210", active=False))])
    repo.import_records("executives", [{"_row": 2, "name": "Arun", "phone": "9876543210"}])
    assert repo.list_rows("executives")[0]["active"] is True


def test_import_is_logged_with_its_source(repo):
    repo.import_records("cars", [{"_row": 2, "make": "Tata", "model": "Nexon"}],
                        source="Import: cars.xlsx")
    [entry] = repo.audit_entries()
    assert entry["action"] == "Added" and entry["source"] == "Import: cars.xlsx"


def test_mapping_is_remembered(repo):
    repo.set_mapping("cars", {"make": "Brand", "model": "Car Model", "segment": None})
    assert repo.get_mapping("cars") == {"make": "Brand", "model": "Car Model"}


@pytest.mark.parametrize("number, ok", [
    ("9876543210", True), ("+91 98765 43210", True), ("098765-43210", True),
    ("919876543210", True), ("9876543210.0", True), ("994264555", False),
    ("98765432101", False), ("12345", False)])
def test_valid_mobile(number, ok):
    from app.data.masters_repo import valid_mobile
    assert valid_mobile(number) is ok


def test_nine_digit_number_is_refused(repo):
    with pytest.raises(MasterError) as err:
        repo.save("executives", [RowChange(None, executive("Naveendran", "994264555"))])
    assert "must have 10 digits" in err.value.messages[0]
    result = repo.import_records("executives", [{"_row": 5, "name": "Naveendran",
                                                 "phone": "994264555"}])
    assert result.added == 0 and "Row 5" in result.skipped[0]
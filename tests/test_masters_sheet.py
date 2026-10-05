"""
test_masters_sheet.py - The masters as a Google Sheet (payout app, v0.14.0)
==========================================================================

No test here touches Google: masters_sheet.py works on plain rows, and the
Sheets calls of google_api.py are run against a stand-in that records what
would have been sent.

What is checked:
* the tool's masters -> sheet rows -> masters again gives the same masters,
  including every dated amount;
* a rate change typed by the client as a new dated row applies from its date;
* every kind of mistake is reported with its tab and row, and then NOTHING
  from the sheet is used;
* the last good copy is used only when the sheet cannot be reached.
"""

from datetime import date, datetime

import pytest

from app.data.inputs_repo import InputsRepo
from app.data.masters_repo import RowChange
from payout_app import google_api, masters_sheet as ms, settings


@pytest.fixture
def filled(repo):
    """A small set of masters, with one labour charge changed on 1 October."""
    repo.save("incentives", [
        RowChange(None, dict(name="Underbody", incentive_amount=200, bill_value=3500,
                             active=True), date(2026, 4, 1)),
        RowChange(None, dict(name="Basic Package", incentive_amount=1000,
                             bill_value=15000, active=True), date(2026, 4, 1))])
    repo.save("products", [
        RowChange(None, dict(sku="SNC-F", name="Sunfilm - Front", hsn_sac="39206929",
                             category="Service", incentive_group="", selling_price=7000,
                             cost_price=2400, has_labour=True, labour_charge=300,
                             internal_incentive=0, vehicle_needed=True, active=True),
                  date(2026, 4, 1)),
        RowChange(None, dict(sku="", name="Underbody Coating", hsn_sac="870899",
                             category="Service", incentive_group="Underbody",
                             selling_price=3500, cost_price=900, has_labour=False,
                             labour_charge=0, internal_incentive=0, vehicle_needed=True,
                             active=True), date(2026, 4, 1)),
        RowChange(None, dict(sku="PERF", name="Car Perfume", hsn_sac="3303",
                             category="Product", incentive_group="", selling_price=400,
                             cost_price=150, has_labour=False, labour_charge=0,
                             internal_incentive=0, vehicle_needed=False, active=False),
                  date(2026, 4, 1))])
    sunfilm = next(p for p in repo.list_rows("products") if p["name"] == "Sunfilm - Front")
    repo.save("products", [RowChange(sunfilm["id"], dict(sunfilm, labour_charge=350.0),
                                     date(2026, 10, 1))])
    repo.save("executives", [
        RowChange(None, dict(name="Edhayan", phone="9000000004", branch="Ooty",
                             gets_incentive=True, active=True)),
        RowChange(None, dict(name="Nandha Kumar", phone="9000000003", branch="HO",
                             gets_incentive=False, active=True))])
    repo.save("cars", [RowChange(None, dict(make="Hyundai", model="i20",
                                            segment="Hatchback", active=True))])
    repo.save("package_items", [RowChange(None, dict(
        package="Basic Package", item="Sunfilm", product="Sunfilm - Front", active=True))])
    return repo


@pytest.fixture
def tabs(filled):
    return ms.to_tabs(filled, InputsRepo(filled))


def col(tabs, tab, heading):
    return tabs[tab][0].index(heading)


def row_of(tabs, tab, heading, value, nth=0):
    """Index (in the tab's rows) of the nth row holding `value` under `heading`."""
    c = col(tabs, tab, heading)
    return [i for i, r in enumerate(tabs[tab]) if i and r[c] == value][nth]


# --- tool -> sheet -> tool -------------------------------------------------
def test_sheet_has_one_row_per_dated_change(tabs):
    assert list(tabs) == ["Products", "Sales executives", "Cars", "Incentives",
                          "Packages", "Settings"]
    assert tabs["Products"][0] == [
        "SKU", "Product name", "HSN/SAC", "Category", "Incentive group",
        "Selling price", "Cost price", "Labour involved", "Labour charge",
        "Internal incentive", "Vehicle needed", "Effective from", "Active"]
    c = col(tabs, "Products", "Labour charge")
    d = col(tabs, "Products", "Effective from")
    sunfilm = [r for r in tabs["Products"][1:] if r[1] == "Sunfilm - Front"]
    assert [(r[c], r[d]) for r in sunfilm] == [
        (300.0, ms.date_to_serial(date(2026, 4, 1))),
        (350.0, ms.date_to_serial(date(2026, 10, 1)))]
    assert tabs["Settings"][1:] == [
        ["Breakage / returns / transport (% of COGS)", 4.0],
        ["Compliance GST (% of COGS)", 3.0]]


def test_round_trip_gives_the_same_masters(filled, tabs):
    result = ms.load_tabs(tabs)
    assert result.problems == [] and result.ok
    assert result.counts == {"Incentives": 2, "Products": 3, "Sales executives": 2,
                             "Cars": 1, "Packages": 1}
    assert result.settings == {"auto_breakage_pct": 4.0, "auto_compliance_pct": 3.0}
    new = result.masters
    for master in ("products", "executives", "cars", "incentives", "package_items"):
        strip = lambda rows: sorted(
            (tuple(sorted((k, str(v)) for k, v in r.items() if k != "id")) for r in rows))
        assert strip(new.list_rows(master)) == strip(filled.list_rows(master)), master
    sunfilm = next(p for p in new.list_rows("products") if p["name"] == "Sunfilm - Front")
    assert new.rate_on("products", sunfilm["id"], date(2026, 9, 30))["labour_charge"] == 300
    assert new.rate_on("products", sunfilm["id"], date(2026, 10, 1))["labour_charge"] == 350
    assert len(new.rate_history("products", sunfilm["id"])) == 2


def test_client_adds_a_dated_row_for_a_new_rate(tabs):
    first = tabs["Incentives"][row_of(tabs, "Incentives", "Product / Service", "Underbody")]
    later = list(first)
    later[col(tabs, "Incentives", "Incentive amount")] = "250"        # typed as text
    later[col(tabs, "Incentives", "Effective from")] = "01/11/2026"   # typed as text
    tabs["Incentives"].append(later)
    result = ms.load_tabs(tabs)
    assert result.ok, result.problems
    row = next(r for r in result.masters.list_rows("incentives") if r["name"] == "Underbody")
    on = lambda d: result.masters.rate_on("incentives", row["id"], d)["incentive_amount"]
    assert on(date(2026, 10, 31)) == 200 and on(date(2026, 11, 1)) == 250


def test_columns_are_found_by_heading_and_extra_ones_ignored(tabs):
    rows = tabs["Sales executives"]
    tabs["Sales executives"] = [list(reversed(r)) + ["x"] for r in rows]
    tabs["Sales executives"][0][-1] = "Remarks"
    # a contact number typed as a number arrives as 9000000004.0
    c = tabs["Sales executives"][0].index("Contact no")
    tabs["Sales executives"][1][c] = float(tabs["Sales executives"][1][c])
    result = ms.load_tabs(tabs)
    assert result.ok, result.problems
    assert "Sales executives: column “Remarks” is not used." in result.notes
    assert {r["phone"] for r in result.masters.list_rows("executives")} == \
        {"9000000004", "9000000003"}


def test_blank_date_is_allowed_on_a_single_row(tabs):
    r = row_of(tabs, "Incentives", "Product / Service", "Basic Package")
    tabs["Incentives"][r][col(tabs, "Incentives", "Effective from")] = ""
    result = ms.load_tabs(tabs)
    assert result.ok, result.problems
    row = next(x for x in result.masters.list_rows("incentives") if x["name"] == "Basic Package")
    assert result.masters.rate_on("incentives", row["id"], date(2026, 9, 1))["bill_value"] == 15000


# --- mistakes are reported and nothing is used -----------------------------
def problems_after(tabs, change):
    change(tabs)
    result = ms.load_tabs(tabs)
    assert result.masters is None and not result.ok
    return result.problems


def test_amount_that_is_not_a_number(tabs):
    def change(t):
        r = row_of(t, "Products", "Product name", "Underbody Coating")
        t["Products"][r][col(t, "Products", "Cost price")] = "mrp less 10%"
    assert problems_after(tabs, change) == [
        f"Products, row {row_of(tabs, 'Products', 'Product name', 'Underbody Coating') + 1}: "
        "Cost price “mrp less 10%” is not a number."]


def test_yes_no_and_date_cells(tabs):
    def change(t):
        t["Products"][1][col(t, "Products", "Labour involved")] = "maybe"
        t["Products"][2][col(t, "Products", "Effective from")] = "next month"
    problems = problems_after(tabs, change)
    assert "Products, row 2: Labour involved must be Yes or No, not “maybe”." in problems
    assert any(p.startswith("Products, row 3: Effective from “next month” is not a date")
               for p in problems)


def test_duplicate_and_short_contact_numbers(tabs):
    def change(t):
        c = col(t, "Sales executives", "Contact no")
        t["Sales executives"].append(["Someone Else", t["Sales executives"][1][c],
                                      "HO", "Yes", "Yes"])
        t["Sales executives"].append(["Naveendran", "900000001", "Ooty", "Yes", "Yes"])
    problems = problems_after(tabs, change)
    assert any(p.startswith("Sales executives, rows 2 and 4:") and "more than once" in p
               for p in problems)
    assert any(p.startswith("Sales executives, row 5:") and "10 digits" in p for p in problems)


def test_unknown_incentive_group_and_package_item(tabs):
    def change(t):
        r = row_of(t, "Products", "Product name", "Underbody Coating")
        t["Products"][r][col(t, "Products", "Incentive group")] = "Under body"
        t["Packages"][1][col(t, "Packages", "Zoho item name")] = "Sunfilm Front"
    problems = problems_after(tabs, change)
    assert any("Incentive group “Under body” is not in the Incentives master" in p
               for p in problems)
    assert any(p.startswith("Packages, row 2:") and "not in the Product master" in p
               for p in problems)


def test_same_name_same_date_and_missing_date(tabs):
    def change(t):
        first = t["Products"][row_of(t, "Products", "Product name", "Sunfilm - Front")]
        t["Products"].append(list(first))                       # same date again
        r = row_of(t, "Incentives", "Product / Service", "Underbody")
        extra = list(t["Incentives"][r])
        extra[col(t, "Incentives", "Effective from")] = ""
        t["Incentives"].append(extra)                           # second row, no date
    problems = problems_after(tabs, change)
    assert any("Sunfilm - Front” has two rows with the same Effective from date "
               "(01-04-2026)" in p for p in problems)
    assert any(p.startswith("Incentives, row 4:") and "each needs an Effective from date" in p
               for p in problems)


def test_duplicate_sku_car_and_required_cell(tabs):
    def change(t):
        r = row_of(t, "Products", "Product name", "Underbody Coating")
        t["Products"][r][col(t, "Products", "SKU")] = "snc-f"
        t["Cars"].append(["HYUNDAI", " I20 ", "Hatchback", "Yes"])
        t["Cars"].append(["Tata", "", "SUV", "Yes"])
    problems = problems_after(tabs, change)
    assert any("SKU" in p and p.startswith("Products, row") for p in problems)
    assert any(p.startswith("Cars, rows 2 and 3:") for p in problems)
    assert any(p.startswith("Cars, row 4:") and "Model is required" in p for p in problems)


def test_missing_tab_and_missing_column(tabs):
    def change(t):
        del t["Cars"]
        c = col(t, "Incentives", "Bill value")
        t["Incentives"] = [r[:c] + r[c + 1:] for r in t["Incentives"]]
    problems = problems_after(tabs, change)
    assert "The tab “Cars” is missing from the sheet." in problems
    assert "Incentives: the column “Bill value” is missing." in problems


def test_settings_percentage_out_of_range(tabs):
    def change(t):
        t["Settings"][1][1] = 140
    assert problems_after(tabs, change) == [
        "Settings, row 2: Breakage / returns / transport must be between 0 and 100."]


# --- last good copy --------------------------------------------------------
def offline():
    raise ConnectionError("no internet")


def test_refresh_saves_a_copy_and_uses_it_when_offline(tabs):
    fixed = lambda: datetime(2026, 10, 5, 9, 30)
    assert ms.refresh(offline).problems[0].startswith(
        "The masters sheet could not be read (no internet) and no earlier copy")
    good = ms.refresh(lambda: tabs, now=fixed)
    assert good.ok and not good.from_cache and good.read_at == "05-10-2026 09:30"
    later = ms.refresh(offline)
    assert later.ok and later.from_cache and later.read_at == "05-10-2026 09:30"
    assert "Using the copy read on 05-10-2026 09:30" in later.notes[0]
    assert later.counts == good.counts


def test_a_sheet_with_mistakes_is_never_replaced_by_the_copy(tabs):
    ms.refresh(lambda: tabs)
    broken = {k: [list(r) for r in v] for k, v in tabs.items()}
    broken["Cars"].append(["Tata", "", "SUV", "Yes"])
    result = ms.refresh(lambda: broken)
    assert not result.ok and result.masters is None and not result.from_cache
    assert ms.refresh(offline).ok          # the earlier good copy is still there


# --- settings file ---------------------------------------------------------
def test_settings_file_and_sheet_id_from_link():
    assert settings.load() == {} and settings.get("masters_sheet_id") == ""
    settings.save(masters_sheet_id="abc")
    settings.save(masters_sheet_url="https://x")
    assert settings.load() == {"masters_sheet_id": "abc", "masters_sheet_url": "https://x"}
    link = "https://docs.google.com/spreadsheets/d/1AbC_d-9/edit?usp=sharing#gid=0"
    assert settings.sheet_id_from(link) == "1AbC_d-9"
    assert settings.sheet_id_from(" 1AbC_d-9 ") == "1AbC_d-9"


# --- Google calls, against a stand-in --------------------------------------
class FakeRequest:
    def __init__(self, reply):
        self.reply = reply

    def execute(self):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class FakeSheets:
    """Records what would be sent to Google Sheets and answers like it."""

    def __init__(self, stored=None):
        self.calls, self.stored = [], stored or {}

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def create(self, body, fields):
        self.calls.append(("create", body))
        return FakeRequest({"spreadsheetId": "SHEET1", "spreadsheetUrl": "https://sheet/1",
                            "sheets": [{"properties": {"title": s["properties"]["title"],
                                                       "sheetId": 100 + i}}
                                       for i, s in enumerate(body["sheets"])]})

    def get(self, spreadsheetId, fields):
        return FakeRequest({"properties": {"title": "Drive N Style Masters"},
                            "sheets": [{"properties": {"title": t}} for t in self.stored]})

    def batchUpdate(self, spreadsheetId, body):
        self.calls.append(("values" if "data" in body else "format", body))
        return FakeRequest({})

    def batchGet(self, spreadsheetId, ranges, valueRenderOption, dateTimeRenderOption):
        self.calls.append(("read", ranges, valueRenderOption, dateTimeRenderOption))
        return FakeRequest({"valueRanges": [{"values": rows} if rows else {}
                                            for rows in self.stored.values()]})


def test_create_fills_and_formats_every_tab(tabs):
    fake = FakeSheets()
    sheet_id, url = google_api.SheetsClient(service=fake).create(
        ms.SHEET_TITLE, tabs, ms.tab_layout())
    assert (sheet_id, url) == ("SHEET1", "https://sheet/1")
    kinds = [c[0] for c in fake.calls]
    assert kinds == ["create", "values", "format"]
    body = fake.calls[0][1]
    assert body["properties"]["title"] == "Drive N Style Masters"
    assert [s["properties"]["title"] for s in body["sheets"]] == list(tabs)
    assert all(s["properties"]["gridProperties"]["frozenRowCount"] == 1 for s in body["sheets"])
    data = fake.calls[1][1]
    assert data["valueInputOption"] == "RAW"
    assert data["data"][1] == {"range": "'Sales executives'!A1",
                               "values": tabs["Sales executives"]}
    requests = fake.calls[2][1]["requests"]
    products = [r for r in requests
                if next(iter(r.values())).get("range", {}).get("sheetId") == 100]
    lists = [r["setDataValidation"] for r in products if "setDataValidation" in r]
    category = next(v for v in lists if v["range"]["startColumnIndex"] == 3)
    assert [v["userEnteredValue"] for v in category["rule"]["condition"]["values"]] == \
        ["Product", "Service"] and category["rule"]["strict"]
    yes_no = [v["range"]["startColumnIndex"] for v in lists
              if [x["userEnteredValue"] for x in v["rule"]["condition"]["values"]] == ["Yes", "No"]]
    assert yes_no == [7, 10, 12]            # Labour involved, Vehicle needed, Active
    dates = [r["repeatCell"] for r in products if "repeatCell" in r and
             r["repeatCell"]["cell"]["userEnteredFormat"].get("numberFormat", {}).get("type") == "DATE"]
    assert [d["range"]["startColumnIndex"] for d in dates] == [11]
    assert all(d["range"]["startRowIndex"] == 1 for d in dates)   # not the heading


def test_read_tabs_asks_for_stored_values_and_round_trips(tabs):
    stored = dict(tabs, Empty=[])
    fake = FakeSheets(stored)
    read = google_api.SheetsClient(service=fake).read_tabs("SHEET1")
    assert fake.calls[-1] == ("read", [f"'{t}'" for t in stored],
                              "UNFORMATTED_VALUE", "SERIAL_NUMBER")
    assert read["Empty"] == [] and ms.load_tabs(read).ok


def test_google_failure_is_a_plain_message():
    class Failing(FakeSheets):
        def get(self, spreadsheetId, fields):
            error = RuntimeError("boom")
            error.resp = type("R", (), {"status": 404})()
            return FakeRequest(error)
    with pytest.raises(google_api.GoogleError, match="the sheet was not found"):
        google_api.SheetsClient(service=Failing()).read_tabs("nope")

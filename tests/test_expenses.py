"""
test_expenses.py - v0.32.0: discounts in the reports, Zoho expense upload,
labour "tool vs Zoho" in the P&L
=========================================================================

Brinda (10-11-2026):
    * "why aren't the discounts calculated?" - they were (sales are after
      discount) but never shown. Now: P&L "Sales before discount / Less:
      discount given", Discount and Discount % on the invoice and executive
      sheets, and discount rows in the Summary and the Trend.
    * "instead of manually entering the expenses can we upload the expenses
      file and ask the tool to autocategorise?" - Zoho's Expense export is
      read per account, each account goes to a head (remembered), amounts
      are taken excluding GST.
    * labour: "take what the tool takes in the PL and also show the amount
      in zoho and indicate the difference" - only labour.

The expense file below copies the shape of Zoho's export (headings, the rent
row with GST, one account per staff member with "SALARY" in the
description, the labour accounts, Diesel A/C) with small amounts.
"""

import io
from datetime import datetime

import pytest
from openpyxl import Workbook, load_workbook

from app.data.expenses_io import (
    LABOUR, NOT_USED, ExpenseFileError, head_totals, labour_totals, read_expenses,
    suggest_head)

HEAD = ["Expense Date", "Expense Description", "Expense Account", "Paid Through",
        "Tax Amount", "Expense Amount", "Total"]
ROWS = [  # date, description, account, tax, total
    (datetime(2026, 9, 30), "RENT : 9000 TDS : 1000", "Rent Expense", 1800, 11800),
    (datetime(2026, 9, 30), "BEING CASH PAID TO SEP MONTH SALARY", "Aravind", 0, 3500),
    (datetime(2026, 9, 30), "BEING CASH PAID TO SEP MONTH SALARY", "Kowsalya", 0, 1800),
    (datetime(2026, 9, 6), "WEEKLY SUNFILM LABOUR", "Labour For Sunfilm Front", 0, 600),
    (datetime(2026, 9, 13), "WEEKLY SUNFILM LABOUR", "Labour for Sunfilm - Side and Rear", 0, 400),
    (datetime(2026, 9, 8), "MAT WEEKLY LABOUR", "Labour PVC/MLF/Luxury Floor Mat (Venue / Exter / Creta)", 0, 250),
    (datetime(2026, 9, 9), "PETROL", "Diesel A/C", 0, 300),
    (datetime(2026, 9, 8), "HOSE", "Repairs and Maintenance", 0, 40),
    (datetime(2026, 9, 7), "ES:358", "Incentive for Executives", 0, 700),
    (datetime(2026, 9, 5), "COFFEE", "Staff Welfare", 0, 120),
    (datetime(2026, 9, 5), "COFFEE", "Staff Welfare", 0, 30),
    (datetime(2026, 9, 30), "BANK", "Bank Fees and Charges", 0, 55.5),
    (datetime(2026, 9, 21), "SOMETHING NEW", "Pooja Expenses", 0, 99),
    (datetime(2026, 10, 2), "OCTOBER ROW", "Staff Welfare", 0, 9999),     # another month
]


def write_expenses(path, rows=ROWS):
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    for when, text, account, tax, total in rows:
        ws.append([when, text, account, "Undeposited Funds", tax, total, total])
    wb.save(path)
    return path


# ---------------------------------------------------------------------------
# Reading the file and the first suggestions
# ---------------------------------------------------------------------------
def test_expense_file_is_read_per_account_excluding_gst(tmp_path):
    f = read_expenses(write_expenses(tmp_path / "Expense.xlsx"), 2026, 9)
    by = {a.account: a for a in f.accounts}
    assert by["Rent Expense"].amount == 10000 and by["Rent Expense"].gst == 1800   # excl. GST
    assert by["Staff Welfare"].amount == 150 and by["Staff Welfare"].rows == 2
    assert f.other_months == 1 and "OCTOBER ROW" not in str(by["Staff Welfare"].descriptions)
    assert f.total == 10000 + 3500 + 1800 + 600 + 400 + 250 + 300 + 40 + 700 + 150 + 55.5 + 99
    assert by["Labour For Sunfilm Front"].labour_kind == "Sunfilm"
    assert by["Labour PVC/MLF/Luxury Floor Mat (Venue / Exter / Creta)"].labour_kind == "Floor mat"
    with pytest.raises(ExpenseFileError, match="no expense dated in this month"):
        read_expenses(tmp_path / "Expense.xlsx", 2026, 7)
    bad = tmp_path / "bad.xlsx"
    wb = Workbook()
    wb.active.append(["Invoice Number", "Total"])
    wb.save(bad)
    with pytest.raises(ExpenseFileError, match="Expense Account"):
        read_expenses(bad, 2026, 9)


def test_first_suggestions():
    known = ["Rent", "Salaries", "Electricity", "Staff Welfare"]
    assert suggest_head("Labour For Sunfilm Front", [], known) == LABOUR
    assert suggest_head("Incentive for Executives", [], known) == "Incentives"
    assert suggest_head("Rent Expense", [], known) == "Rent"
    assert suggest_head("Diesel A/C", [], known) == "Repairs and maintenance"
    assert suggest_head("Bank Fees and Charges", [], known) == "Bank Charges"
    assert suggest_head("Aravind", ["BEING CASH PAID TO OCT MONTH SALARY"], known) == "Salaries"
    assert suggest_head("staff welfare", [], known) == "Staff Welfare"      # a head already used
    assert suggest_head("Pooja Expenses", ["SOMETHING"], known) == "Pooja Expenses"


def test_totals_per_head_and_labour(tmp_path):
    f = read_expenses(write_expenses(tmp_path / "Expense.xlsx"), 2026, 9)
    matches = {a.account.lower(): suggest_head(a.account, a.descriptions, []) for a in f.accounts}
    matches["pooja expenses"] = NOT_USED
    heads = head_totals(f.accounts, matches)
    assert heads["Salaries"] == 5300 and heads["Repairs and maintenance"] == 340
    assert heads["Incentives"] == 700 and "Pooja Expenses" not in heads
    assert labour_totals(f.accounts, matches) == {"Sunfilm": 1000, "Floor mat": 250}


# ---------------------------------------------------------------------------
# Through the web server, then into the workbook
# ---------------------------------------------------------------------------
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("itsdangerous")

from tests.test_web_auth import ADMIN, H                     # noqa: E402
from tests.test_web_monthly import M, read_month, world      # noqa: E402,F401


def upload(client, data: bytes, name="Expense.xlsx", month=M):
    return client.post(f"{month}/expenses", params={"filename": name}, content=data, headers=H)


def test_expense_upload_apply_and_the_reports(world, tmp_path, monkeypatch):  # noqa: F811
    from app.reports import pdf_export
    monkeypatch.setattr(pdf_export, "find_libreoffice", lambda: None)
    settings, admin, staff, export = world
    data = write_expenses(tmp_path / "Expense.xlsx").read_bytes()

    assert admin.get(f"{M}/expenses").json() == {"file": None}
    assert upload(staff, data).status_code == 403                       # admins only
    assert upload(admin, b"x", "Expense.pdf").status_code == 400
    assert upload(admin, b"not a sheet", "Expense.csv").status_code == 400

    preview = upload(admin, data).json()
    assert preview["file"]["name"] == "Expense.xlsx" and preview["other_months"] == 1
    heads = {a["account"]: a["head"] for a in preview["accounts"]}
    assert heads["Aravind"] == heads["Kowsalya"] == "Salaries"
    assert heads["Labour For Sunfilm Front"] == preview["labour"] == LABOUR
    assert heads["Rent Expense"] == "Rent" and heads["Diesel A/C"] == "Repairs and maintenance"
    assert not any(a["saved"] for a in preview["accounts"])

    heads["Pooja Expenses"] = "Miscellaneous"                            # the user's choice
    assert admin.post(f"{M}/expenses/apply", headers=H,
                      json={"matches": {"Aravind": "Salaries"}}).status_code == 400   # not all chosen
    done = admin.post(f"{M}/expenses/apply", headers=H, json={"matches": heads})
    assert done.status_code == 200, done.text
    assert dict(map(tuple, done.json()["heads"]))["Salaries"] == 5300
    assert done.json()["labour"] == {"Sunfilm": 1000, "Floor mat": 250}
    saved = dict(map(tuple, admin.get(f"{M}/inputs").json()["costs"]))
    assert saved["Rent"] == 10000 and saved["Miscellaneous"] == 99 and saved["Incentives"] == 700
    assert not any("Labour" in h for h in saved)

    # remembered: the next month's file needs no decision for these accounts
    again = upload(admin, data, month="/api/monthly/2026-09").json()
    assert all(a["saved"] for a in again["accounts"])
    assert {a["account"]: a["head"] for a in again["accounts"]}["Pooja Expenses"] == "Miscellaneous"
    log = admin.get("/api/audit", params={"master": "inputs"}).json()["entries"]
    assert any(e["record"] == "Zoho expense account matches" and e["user"] == ADMIN for e in log)
    assert any(e["record"].startswith("Labour as per Zoho") for e in log)

    # the workbook: labour tool vs Zoho under the P&L (the invoices of this
    # small month are all still waiting on Scan review, so the tool's own
    # labour is 0 here - the discount lines are tested in test_discounts.py)
    read_month(admin, export)
    made = admin.post(f"{M}/generate", headers=H, json={"reports": ["Profit & loss"]})
    assert made.status_code == 200, made.text
    book = load_workbook(io.BytesIO(admin.get(
        f"/api/monthly/runs/{made.json()['run']['id']}/download").content))
    pnl = [r for r in book["12 Profit & loss"].iter_rows(values_only=True)]
    first = [r[0] for r in pnl]
    lab = first.index("Labour - tool vs Zoho")
    body = {r[0]: r for r in pnl[lab + 2:] if r[0]}
    assert body["Sunfilm"][2] == 1000 and body["Floor mat"][2] == 250
    assert body["Sunfilm"][1] == 0 and str(body["Sunfilm"][3]).startswith("=")

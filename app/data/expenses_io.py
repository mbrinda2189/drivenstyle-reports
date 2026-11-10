"""
expenses_io.py - Reading Zoho's Expense export for Monthly inputs (v0.32.0)
=========================================================================

WHAT THIS MODULE DOES
---------------------
Until v0.31 the month's indirect costs were typed head by head on Monthly
inputs. Brinda (10-11-2026): "instead of manually entering the expenses can
we upload the expenses file and ask the tool to autocategorise?". This
module reads the file and proposes, for every Zoho expense ACCOUNT, which
Monthly-inputs HEAD it goes to. The screen shows the proposal, the user
confirms or changes it, and inputs_repo.apply_expenses saves the heads and
remembers each account's head for every later month.

    read_expenses(path, year, month)  -> ExpenseFile
        The rows of Zoho's Expense export (.xlsx or .csv) dated in the month,
        added up per account. Rows dated in other months are counted and
        left out (an export for a longer period still works).

    suggest_head(account, descriptions, known_heads) -> head
        A FIRST suggestion for an account nobody has matched yet. Once the
        user has saved a head for the account, that saved head is used
        instead every month (inputs_repo.expense_matches). See RULES below.

AMOUNTS: EXCLUDING GST
----------------------
Each row's amount is Zoho's "Total" less its "Tax Amount", so the heads agree
with Zoho's Profit & Loss: October's rent row is 2,71,400 with GST 41,400,
and Zoho's P&L - like the tool - shows Rent 2,30,000.

RULES FOR THE FIRST SUGGESTION (in this order)
-----------------------------------------------
Only the account NAME decides, except rule 4, which also looks at the
descriptions - and every suggestion is shown to the user before anything is
saved, so nothing is filed without being seen.
    1. "labour" in the name             -> LABOUR. Not an expense head: the
                                           tool works labour out from the
                                           Product master. The amount is kept
                                           only to show beside the tool's
                                           labour in the P&L (by kind:
                                           Sunfilm / Floor mat / Other, from
                                           the account name).
    2. "incentive" in the name          -> "Incentives" (a direct cost in the
                                           P&L, as when it was typed).
    3. Zoho's usual account names       -> the heads used on Monthly inputs:
                                           Rent Expense -> Rent, Bank Fees and
                                           Charges -> Bank Charges, Diesel A/C
                                           -> Repairs and maintenance, ... (SYNONYMS)
    4. any of its descriptions says
       "salary"                         -> "Salaries" (Zoho keeps one account
                                           per staff member: Aravind,
                                           Balachandran, ...)
    5. a head already used, same name   -> that head (capitals ignored)
    6. otherwise                        -> a head with the account's own name

No database and no Qt code in this module.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from app.data.master_defs import header_key
from app.reports.data import labour_group
from app.utils import parse_inr

# The two non-head choices on the matching screen (also stored in the
# expense_accounts table as the "head").
LABOUR = "(labour)"
NOT_USED = "(not used)"

# Zoho account name (header_key form) -> Monthly-inputs head (rule 3).
SYNONYMS = {
    "rentexpense": "Rent",
    "rent": "Rent",
    "salariesandwages": "Salaries",
    "salaries": "Salaries",
    "salary": "Salaries",
    "electricity": "Electricity",
    "telephoneexpense": "Internet & phone",
    "internetexpense": "Internet & phone",
    "itandinternetexpenses": "Internet & phone",
    "advertisingandmarketing": "Advertising and marketing",
    "consumables": "Consumables",
    "printingandstationery": "Printing and Stationery",
    "postage": "Postage",
    "staffwelfare": "Staff Welfare",
    "transportationexpense": "Transportation",
    "travelexpense": "Travel Expense",
    "rawmaterialsandconsumables": "Raw materials and consumables",
    "otherexpenses": "Other expenses",
    "repairsandmaintenance": "Repairs and maintenance",
    "dieselac": "Repairs and maintenance",
    "bankfeesandcharges": "Bank Charges",
}

COLUMNS = {                       # our name -> accepted headings (header_key form)
    "date": ("expensedate", "date"),
    "account": ("expenseaccount", "account"),
    "description": ("expensedescription", "description"),
    "total": ("total",),
    "amount": ("expenseamount", "amount"),
    "tax": ("taxamount",),
}


class ExpenseFileError(Exception):
    """The file is not a usable Zoho Expense export."""


@dataclass
class Account:
    """One Zoho expense account's rows in the month, added up."""
    account: str
    amount: float = 0.0                         # excluding GST
    gst: float = 0.0
    rows: int = 0
    descriptions: list[str] = field(default_factory=list)

    @property
    def labour_kind(self) -> str:
        """Sunfilm / Floor mat / Other - the same rule as the Labour sheet."""
        return labour_group(self.account)


@dataclass
class ExpenseFile:
    accounts: list[Account]                     # in the order first met
    other_months: int = 0                       # rows dated outside the month, left out
    no_date: int = 0                            # rows without a readable date, left out

    @property
    def total(self) -> float:
        return round(sum(a.amount for a in self.accounts), 2)


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text[:11].strip(), fmt).date()
        except ValueError:
            continue
    return None


def _number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return parse_inr(str(value or "")) or 0.0


def table_rows(path: Path) -> list[list]:
    """Every row of a .csv or the first sheet of an .xlsx, as lists of cell
    values (also used for Zoho's COGS and FIFO reports, zoho_costs.py)."""
    ext = path.suffix.lower()
    if ext == ".csv":
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                with open(path, newline="", encoding=encoding) as fh:
                    return [r for r in csv.reader(fh)]
            except UnicodeDecodeError:
                continue
        raise ExpenseFileError("The CSV file's text encoding was not recognised.")
    if ext in (".xlsx", ".xlsm"):
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return [list(r) for r in wb.active.iter_rows(values_only=True)]
        finally:
            wb.close()
    raise ExpenseFileError("Choose Zoho's Expense export (.xlsx or .csv).")


_rows = table_rows        # the old name


def read_expenses(path: str | Path, year: int, month: int) -> ExpenseFile:
    """The month's rows of Zoho's Expense export, added up per account."""
    path = Path(path)
    try:
        rows = table_rows(path)
    except ExpenseFileError:
        raise
    except Exception as exc:
        raise ExpenseFileError(f"The expenses file could not be opened: {exc}") from exc
    if not rows:
        raise ExpenseFileError("The expenses file is empty.")
    heads = [header_key(h or "") for h in rows[0]]
    col: dict[str, int] = {}
    for name, accepted in COLUMNS.items():
        for i, h in enumerate(heads):
            if h in accepted and name not in col:
                col[name] = i
    if "account" not in col or ("total" not in col and "amount" not in col):
        raise ExpenseFileError("This does not look like Zoho's Expense export: the "
                               "Expense Account and Total columns are missing.")

    found: dict[str, Account] = {}
    other_months = no_date = 0
    for r in rows[1:]:
        def cell(name):
            i = col.get(name)
            return r[i] if i is not None and i < len(r) else None
        account = " ".join(str(cell("account") or "").split())
        if not account:
            continue
        when = _date(cell("date")) if "date" in col else None
        if "date" in col:
            if when is None:
                no_date += 1
                continue
            if (when.year, when.month) != (year, month):
                other_months += 1
                continue
        total = _number(cell("total")) if "total" in col else _number(cell("amount"))
        tax = _number(cell("tax"))
        a = found.setdefault(account.lower(), Account(account))
        a.amount = round(a.amount + total - tax, 2)       # excluding GST
        a.gst = round(a.gst + tax, 2)
        a.rows += 1
        text = str(cell("description") or "").strip()
        if text:
            a.descriptions.append(text)
    if not found:
        raise ExpenseFileError("The expenses file has no expense dated in this month.")
    return ExpenseFile(list(found.values()), other_months, no_date)


def suggest_head(account: str, descriptions: list[str], known_heads: list[str]) -> str:
    """A first suggestion for an account not matched before - see RULES."""
    key = header_key(account)
    low = account.lower()
    if "labour" in low or "labor" in low:
        return LABOUR
    if "incentive" in low:
        return "Incentives"
    if key in SYNONYMS:
        return SYNONYMS[key]
    if any("salary" in d.lower() for d in descriptions):
        return "Salaries"
    for h in known_heads:
        if header_key(h) == key:
            return h
    return account


def head_totals(accounts: list[Account], matches: dict[str, str]) -> dict[str, float]:
    """Head -> total (excluding GST) for the accounts matched to a head, in the
    order the heads are first met. LABOUR and NOT_USED accounts are left out."""
    out: dict[str, float] = defaultdict(float)
    for a in accounts:
        head = matches.get(a.account.lower()) or matches.get(a.account)
        if head and head not in (LABOUR, NOT_USED):
            out[head] = round(out[head] + a.amount, 2)
    return dict(out)


def labour_totals(accounts: list[Account], matches: dict[str, str]) -> dict[str, float]:
    """Kind (Sunfilm / Floor mat / Other) -> labour booked, for LABOUR accounts."""
    out: dict[str, float] = defaultdict(float)
    for a in accounts:
        if (matches.get(a.account.lower()) or matches.get(a.account)) == LABOUR:
            out[a.labour_kind] = round(out[a.labour_kind] + a.amount, 2)
    return dict(out)

"""
zoho_costs.py - Reading Zoho's cost of goods sold reports (v0.33.0)
===================================================================

WHAT THIS MODULE DOES
---------------------
The client asked (10-11-2026) for the cost of goods sold "at invoice level":
"Sale - COGS - item difference compared to master sheet. Zoho uses FIFO
inventory costing, so we have to check what costing it is taking for each
item, compared to the master sheet." The tool's product cost comes from the
Product master (cost price x qty). Zoho's comes from its FIFO stock lots.
Two Zoho reports give Zoho's side, and both are optional uploads on
Generate:

1. ACCOUNT TRANSACTIONS of the "Cost of Goods Sold" account
   (Zoho Books > Reports > Account Transactions, account = Cost of Goods
   Sold, the month, Export as XLSX / CSV)

       date | account_name | transaction_details | transaction_type |
       entity_number | debit | credit | net_amount | ...

   One row per posting. `transaction_type` "invoice" rows are the COGS
   Zoho posted for that invoice (`entity_number` = the invoice number). The
   rest - "bill" (a purchase booked straight to COGS), "vendor_credit",
   "journal" ... - are not invoices but are part of the P&L figure.
   Adding up net_amount gives exactly Zoho's P&L "Cost of Goods Sold"
   (October 2026: 7,65,567.18 on invoices + 4,510.00 bill - 6,003.79 vendor
   credits = 7,64,073.39).
   -> read_cogs(path) -> CogsFile

2. FIFO COST LOT TRACKING
   (Zoho Books > Reports > Inventory > FIFO Cost Lot Tracking, Export)

       Product In:  Date | Transactions | Received From | Item Name | SKU |
                    Quantity | Age | Remaining Qty | Cost Per Unit | Total
       Product Out: Date | Transactions | Disperse To | Dispersed Qty

   One row per lot used by a sale: the purchase lot (bill) and the
   invoice it went to, with the lot's cost per unit. A row with NO
   "Product In" date is a sale made with no stock in hand - Zoho costs it
   at 0 (Remaining Qty goes negative). Only stock-tracked items appear;
   services and items not tracked as stock never do.
   The report is filtered by the LOT's date (the bill), not the sale's, so
   export it FROM THE START OF THE BUSINESS (01-07-2026) TO TODAY: a bill
   entered later can still cost an October sale (October's file showed a
   bill dated 31-10 costing a September invoice), and with the period
   ending on the month's last day such lots would be missing.
   -> read_fifo(path) -> list[FifoOut]  (rows that went to an invoice)

Both readers find the heading row by its headings, take .xlsx or .csv, and
raise ZohoCostFileError with a plain message for a wrong file.

No database and no Qt code here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from app.data.expenses_io import ExpenseFileError, table_rows
from app.data.master_defs import header_key
from app.utils import parse_inr

EXTENSIONS = (".xlsx", ".csv")


class ZohoCostFileError(Exception):
    """The file is not the Zoho report it should be (plain-language text)."""


def _number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if text in ("", "-"):
        return 0.0
    return parse_inr(text) or 0.0


def _day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _rows(path: Path, what: str) -> list[list]:
    if path.suffix.lower() not in EXTENSIONS:
        raise ZohoCostFileError(f"{what}: choose Zoho's .xlsx or .csv export.")
    try:
        return table_rows(path)
    except ExpenseFileError as exc:
        raise ZohoCostFileError(f"{what}: {exc}") from exc
    except Exception as exc:
        raise ZohoCostFileError(f"{what}: the file could not be opened ({exc}).") from exc


def invoice_key(number: str) -> str:
    """Invoice numbers compared without spaces and capitals ("DNS-356-2627")."""
    return re.sub(r"\s+", "", str(number or "")).upper()


# ---------------------------------------------------------------------------
# 1. Account Transactions - Cost of Goods Sold
# ---------------------------------------------------------------------------
@dataclass
class CogsEntry:
    day: date | None
    kind: str              # Zoho's transaction_type: invoice, bill, vendor_credit ...
    number: str            # entity_number: the invoice / bill / credit number
    details: str           # transaction_details: customer or vendor
    amount: float          # net_amount (debit - credit)


KIND_NAMES = {"invoice": "Invoices", "bill": "Purchase bills booked to COGS",
              "vendor_credit": "Vendor credits", "journal": "Journals",
              "credit_note": "Credit notes", "inventory_adjustment": "Stock adjustments"}


@dataclass
class CogsFile:
    entries: list[CogsEntry]
    period: str = ""       # "From 01/10/2026 To 31/10/2026", from the title

    @property
    def total(self) -> float:
        """= Zoho's P&L "Cost of Goods Sold" for the period."""
        return round(sum(e.amount for e in self.entries), 2)

    def by_invoice(self) -> dict[str, float]:
        """Invoice number (invoice_key) -> COGS Zoho posted for it."""
        out: dict[str, float] = defaultdict(float)
        for e in self.entries:
            if e.kind == "invoice":
                out[invoice_key(e.number)] = round(out[invoice_key(e.number)] + e.amount, 2)
        return dict(out)

    def other_kinds(self) -> list[tuple[str, int, float]]:
        """(what, entries, amount) for every posting that is not an invoice."""
        out: dict[str, list] = {}
        for e in self.entries:
            if e.kind != "invoice":
                name = KIND_NAMES.get(e.kind, e.kind.replace("_", " ").capitalize() or "Other")
                g = out.setdefault(name, [0, 0.0])
                g[0] += 1
                g[1] = round(g[1] + e.amount, 2)
        return [(k, n, a) for k, (n, a) in out.items()]


COGS_COLUMNS = {"type": "transactiontype", "number": "entitynumber", "amount": "netamount",
                "debit": "debit", "credit": "credit", "date": "date",
                "details": "transactiondetails", "account": "accountname",
                "account_type": "accounttype"}
COGS_WHAT = "Zoho COGS (Account Transactions)"


def read_cogs(path: str | Path) -> CogsFile:
    """The postings of Zoho's Account Transactions report for the Cost of
    Goods Sold account (see module notes)."""
    rows = _rows(Path(path), COGS_WHAT)
    for h, heading in enumerate(rows[:10]):
        keys = [header_key(c or "") for c in heading]
        col = {name: keys.index(k) for name, k in COGS_COLUMNS.items() if k in keys}
        if {"type", "number"} <= col.keys() and ("amount" in col or "debit" in col):
            break
    else:
        raise ZohoCostFileError(
            f"{COGS_WHAT}: this is not Zoho's Account Transactions export - the "
            "transaction_type, entity_number and net_amount columns are missing.")
    period = ""
    for row in rows[:h]:
        m = re.search(r"From\s+\S+\s+To\s+\S+", str(row[0] or "") if row else "")
        if m:
            period = m.group(0)

    def cell(row, name):
        i = col.get(name)
        return row[i] if i is not None and i < len(row) else None

    entries = []
    for row in rows[h + 1:]:
        kind = str(cell(row, "type") or "").strip().lower()
        if not kind:
            continue                          # blank / closing rows
        # Only the Cost of Goods Sold account, should the report hold others.
        account = str(cell(row, "account") or "").lower()
        account_type = str(cell(row, "account_type") or "").lower()
        if (account or account_type) and "cost of goods" not in account \
                and account_type != "cost_of_goods_sold":
            continue
        if "amount" in col:
            amount = _number(cell(row, "amount"))
        else:
            amount = _number(cell(row, "debit")) - _number(cell(row, "credit"))
        entries.append(CogsEntry(_day(cell(row, "date")), kind,
                                 " ".join(str(cell(row, "number") or "").split()),
                                 " ".join(str(cell(row, "details") or "").split()),
                                 round(amount, 2)))
    if not entries:
        raise ZohoCostFileError(f"{COGS_WHAT}: the file has no Cost of Goods Sold postings.")
    return CogsFile(entries, period)


# ---------------------------------------------------------------------------
# 2. FIFO Cost Lot Tracking
# ---------------------------------------------------------------------------
@dataclass
class FifoOut:
    """Part of one invoice line costed from one lot (or from no stock)."""
    invoice_no: str
    item: str
    qty: float
    cost_per_unit: float   # the lot's; 0 when sold with no stock
    lot: str               # "Bill # 215" ... ; "" when sold with no stock
    lot_date: date | None
    sold_on: date | None

    @property
    def cost(self) -> float:
        return round(self.qty * self.cost_per_unit, 2)

    @property
    def no_stock(self) -> bool:
        return not self.lot


FIFO_WHAT = "Zoho FIFO Cost Lot Tracking"


def read_fifo(path: str | Path) -> list[FifoOut]:
    """The rows of Zoho's FIFO Cost Lot Tracking report that went to an
    invoice (see module notes). Headings appear twice ("Date",
    "Transactions"): the first is the lot (Product In), the second the sale."""
    rows = _rows(Path(path), FIFO_WHAT)
    for h, heading in enumerate(rows[:10]):
        keys = [header_key(c or "") for c in heading]
        if {"itemname", "costperunit", "dispersedqty"} <= set(keys):
            break
    else:
        raise ZohoCostFileError(
            f"{FIFO_WHAT}: this is not Zoho's FIFO Cost Lot Tracking export - the Item "
            "Name, Cost Per Unit and Dispersed Qty columns are missing.")
    dates = [i for i, k in enumerate(keys) if k == "date"]
    trans = [i for i, k in enumerate(keys) if k == "transactions"]
    if len(dates) < 2 or len(trans) < 2:
        raise ZohoCostFileError(f"{FIFO_WHAT}: the Product In / Product Out columns are "
                                "not both there.")
    at = {k: keys.index(k) for k in ("itemname", "costperunit", "dispersedqty")}

    def cell(row, i):
        return row[i] if i < len(row) else None

    out = []
    for row in rows[h + 1:]:
        sale = str(cell(row, trans[1]) or "").strip()
        m = re.match(r"Invoice\s*#\s*(.+)$", sale, re.I)
        item = " ".join(str(cell(row, at["itemname"]) or "").split())
        if not m or not item:
            continue                           # not a sale (vendor credit, transfer ...)
        lot = str(cell(row, trans[0]) or "").strip()
        lot_date = _day(cell(row, dates[0]))
        no_stock = not lot and lot_date is None
        out.append(FifoOut(
            invoice_no=" ".join(m.group(1).split()), item=item,
            qty=_number(cell(row, at["dispersedqty"])),
            cost_per_unit=0.0 if no_stock else _number(cell(row, at["costperunit"])),
            lot="" if no_stock else (lot or "lot"), lot_date=lot_date,
            sold_on=_day(cell(row, dates[1]))))
    if not out:
        raise ZohoCostFileError(f"{FIFO_WHAT}: the file has no sale (Invoice #) in it.")
    return out


@dataclass
class ZohoCosts:
    """What Generate was given: either file may be missing."""
    cogs: CogsFile | None = None
    fifo: list[FifoOut] | None = None
    names: dict[str, str] = field(default_factory=dict)   # kind -> uploaded file name

    @property
    def given(self) -> bool:
        return self.cogs is not None or self.fifo is not None

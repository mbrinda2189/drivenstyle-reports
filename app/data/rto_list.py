"""
rto_list.py - Reading the dealership's monthly delivery list ("RTO list")
=========================================================================

WHAT THE FILE IS
----------------
Drive N Style works inside a Hyundai dealership. Every month the dealership
gives a list of the new cars delivered ("RTO List - SEP.xlsx"), one row per
car:

    S.NO | DELIVERY DATE | CUSTOMER NAME | MODEL | VIN NO | SALES CONSULTANT |
    Location | OE Accessories List | OE Total Value | DNS Accessories List |
    DNS Total Value | Executive Contribution | DNS Team Contribution |
    Executive Incentive | Remarks

    OE  = the car maker's own (original equipment) accessories
    DNS = Drive N Style accessories sold on that car

WHY THE TOOL READS IT (v0.9.0)
------------------------------
The invoices only show the cars that BOUGHT something. This list shows every
car delivered, so together they answer: of the cars delivered, how many took
DNS accessories (penetration), which did not and why (remarks), and does the
list agree with what was actually invoiced.

HOW A CAR IS LINKED TO ITS INVOICE
----------------------------------
Zoho's invoice carries the last six digits of the VIN - in the "VIN /
Registration Number" field and at the end of the customer name ("SOUDHA
BEGAM 271295"). The list has the full VIN (MALB281CYTM271295) or just the
last six digits. `vin6` is those six digits on both sides.

READING RULES
-------------
* The heading row is found by its headings (not by position), so extra
  title rows above it do not matter. Empty columns are ignored.
* A row without a customer name is skipped, and so is a repeat of the
  heading row (a list grouped by executive repeats it above each group).
* Values are "-" or blank when there is nothing: read as 0 / empty.
* The delivery date is text like 01.09.26; a real Excel date also works.
* Model names are typed many ways ("I20", "I 20", "All New i20", "New
  Venue"): `model_key` reduces them to one name so they can be grouped.

THE DEALERSHIP'S OWN "CAR SALES REPORT" (v0.30.0)
-------------------------------------------------
From October 2026 the client sends the dealership's "Car Sales Report"
(Car_Sales_Report_-_Oct26.xls) instead of the hand-made RTO list. Its
"Act Del List" sheet has the same first nine columns as the September list
- S.NO up to OE Total Value - but NOT the six columns Drive N Style's staff
used to add by hand:

    DNS Accessories List | DNS Total Value | Executive Contribution |
    DNS Team Contribution | Executive Incentive | Remarks

Brinda's decision (10-11-2026): read this file as it is. So:

* Only Customer Name, Model and VIN No are REQUIRED headings. The DNS
  columns are optional; when they are missing, `RtoCar.dns_columns` is
  False for every car, and the reports leave the list's own DNS figures
  (DNS value as per list, Executive Incentive, the list-vs-invoice check)
  out instead of showing zeros. Whether a car TOOK DNS accessories still
  comes from the Zoho invoices linked to it by the VIN - so penetration,
  missed opportunity, new-car vs other business and OE figures all work.
* The OE heading may carry a note in brackets: "OE Total Value (NDP)" (NDP
  = the dealer's net price) is read as OE Total Value.
* The file is an old-style Excel file (.xls, made by WPS Sheets). openpyxl
  reads only .xlsx, so .xls files are read with the small `xlrd` library;
  the rows come out the same way, so the rest of this module is shared.
* The report's first sheet ("Sheet1") holds the heading row and nothing
  else. A sheet whose headings match but which has no car in it is passed
  over, and the next sheet is tried - otherwise the list would be read as
  "no cars delivered".
* Its other sheets ("Part Wise - List", "CBE - CS OCT'26" ...) are the
  dealership's own accessory invoices, line by line. They are not used:
  the OE total per car is already on "Act Del List".

This module has no database and no Qt code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook


class RtoFileError(Exception):
    """The file could not be read as a delivery list (plain-language text)."""


@dataclass
class RtoCar:
    row: int                    # row number in the sheet
    delivered: date | None
    customer: str
    model: str                  # as typed
    model_group: str            # standard name, see model_key
    vin: str
    vin6: str                   # last six digits, "" if not six digits
    consultant: str
    location: str               # upper case; "(not given)" if blank
    oe_list: str
    oe_value: float
    dns_list: str
    dns_value: float
    executive_contribution: str
    team_contribution: str
    incentive: float            # "Executive Incentive" column
    remarks: str
    # v0.30.0: False when the file has no DNS columns at all (the
    # dealership's Car Sales Report). The DNS fields above are then empty
    # because nobody filled them, NOT because the car took nothing - the
    # reports use `dns_given` below to leave those figures out.
    dns_columns: bool = True

    @property
    def has_dns(self) -> bool:
        return self.dns_value > 0 or bool(self.dns_list)

    @property
    def has_oe(self) -> bool:
        return self.oe_value > 0 or bool(self.oe_list)


def dns_given(cars: list[RtoCar]) -> bool:
    """True when the delivery list carries Drive N Style's own columns (DNS
    Total Value and the rest). False for the dealership's Car Sales Report,
    which has only the car and OE columns (v0.30.0)."""
    return any(c.dns_columns for c in cars)


# heading (letters and digits only, lower case) -> field
HEADINGS = {
    "sno": "sno", "deliverydate": "delivered", "customername": "customer",
    "model": "model", "vinno": "vin", "vin": "vin",
    "salesconsultant": "consultant", "location": "location",
    "oeaccessorieslist": "oe_list", "oetotalvalue": "oe_value",
    "dnsaccessorieslist": "dns_list", "dnstotalvalue": "dns_value",
    "executivecontribution": "executive_contribution",
    "dnsteamcontribution": "team_contribution",
    "executiveincentive": "incentive", "remarks": "remarks",
}
REQUIRED = ("customer", "model", "vin")
# The columns Drive N Style's staff add by hand. If none of them is in the
# file, the list "has no DNS columns" (see RtoCar.dns_columns).
DNS_FIELDS = ("dns_list", "dns_value", "executive_contribution", "team_contribution",
              "incentive", "remarks")


def _key(text) -> str:
    """Heading -> lookup key: letters and digits only, lower case, and a note
    in brackets at the end dropped ("OE Total Value  (NDP)" -> "oetotalvalue")."""
    text = re.sub(r"\([^)]*\)\s*$", "", str(text or ""))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _text(value) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return "" if text == "-" else text


def _amount(value) -> float:
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = re.sub(r"[^0-9.\-]", "", str(value or ""))
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def _day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = re.match(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", str(value or ""))
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y + 2000 if y < 100 else y, mo, d)
    except ValueError:
        return None


def vin6(text) -> str:
    """
    The six digits that identify the car: the end of a 17-character VIN, or
    a 6-digit number standing at the end of the text ("SOUDHA BEGAM 271295",
    "310221"). A registration number (TN45 BK5353) or a phone number gives
    "" - those are not delivered-car invoices.
    """
    text = str(text if text is not None else "").replace(" ", "").upper()
    if len(text) == 17 and text[-6:].isdigit():
        return text[-6:]
    m = re.search(r"(?<!\d)(\d{6})$", text)
    return m.group(1) if m else ""


def model_key(model: str) -> str:
    """
    One name per car model: "All New i20", "I 20", "I20" -> I20; "New Venue"
    -> VENUE; "Grand i10 Nios", "Nios" -> NIOS. Variants that are sold as
    different cars keep their own name (I20 N LINE, CRETA EV).
    """
    text = re.sub(r"\s+", " ", str(model or "").upper()).strip()
    text = re.sub(r"^(ALL NEW|NEW)\s+", "", text)
    text = re.sub(r"\bI\s+(\d+)", r"I\1", text)
    if "NIOS" in text:
        return "NIOS"
    return text or "(not given)"


def _sheets(path: Path) -> list[list[tuple]]:
    """
    Every sheet of the workbook as a list of rows (tuples of cell values),
    in the workbook's order. .xlsx is read with openpyxl; old-style .xls
    (the dealership's Car Sales Report) with xlrd, whose dates are turned
    into real dates so both kinds of file give the same values.
    """
    if path.suffix.lower() == ".xls":
        import xlrd                         # only needed for .xls files
        book = xlrd.open_workbook(str(path))

        def value(cell):
            if cell.ctype == xlrd.XL_CELL_DATE:
                try:
                    return xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
                except (ValueError, OverflowError):
                    return cell.value
            if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                return None
            return cell.value
        return [[tuple(value(c) for c in sheet.row(r)) for r in range(sheet.nrows)]
                for sheet in book.sheets()]
    wb = load_workbook(str(path), data_only=True, read_only=True)
    try:
        return [list(ws.iter_rows(values_only=True)) for ws in wb.worksheets]
    finally:
        wb.close()


def read_rto(path: str | Path) -> list[RtoCar]:
    """
    Read the delivery list; raises RtoFileError with a plain message.

    The first sheet whose heading row has Customer Name, Model and VIN No
    AND at least one car under it is used. A sheet with the headings but no
    car (the Car Sales Report's "Sheet1") is passed over.
    """
    path = Path(path)
    try:
        sheets = _sheets(path)
    except Exception as exc:
        raise RtoFileError(f"“{path.name}” could not be opened as an Excel "
                           f"file ({exc}).") from exc
    found_headings = False
    for rows in sheets:
        for h, heading_row in enumerate(rows[:15]):
            cols = {HEADINGS[_key(c)]: i for i, c in enumerate(heading_row)
                    if _key(c) in HEADINGS}
            if all(f in cols for f in REQUIRED):
                found_headings = True
                cars = _cars(rows[h + 1:], cols, h + 2)
                if cars:
                    return cars
                break                       # headings but no car: next sheet
    if found_headings:
        raise RtoFileError(f"“{path.name}” has the delivery list's headings but no car "
                           "in it.")
    raise RtoFileError(
        f"“{path.name}” does not look like the delivery (RTO) list: no row "
        "with the headings Customer Name, Model and VIN No was found.")


def _cars(rows: list[tuple], cols: dict[str, int], first_row: int) -> list[RtoCar]:
    def get(row, field):
        i = cols.get(field)
        return row[i] if i is not None and i < len(row) else None

    has_dns = any(f in cols for f in DNS_FIELDS)
    out = []
    for n, row in enumerate(rows, start=first_row):
        customer = _text(get(row, "customer"))
        if not customer or _key(customer) == "customername":
            continue                        # empty, or the heading row repeated
                                            # (lists grouped by executive repeat it)
        vin = _text(get(row, "vin"))
        model = _text(get(row, "model"))
        out.append(RtoCar(
            row=n, delivered=_day(get(row, "delivered")), customer=customer,
            model=model, model_group=model_key(model), vin=vin, vin6=vin6(vin),
            consultant=_text(get(row, "consultant")),
            location=_text(get(row, "location")).upper() or "(not given)",
            oe_list=_text(get(row, "oe_list")), oe_value=_amount(get(row, "oe_value")),
            dns_list=_text(get(row, "dns_list")), dns_value=_amount(get(row, "dns_value")),
            executive_contribution=_text(get(row, "executive_contribution")),
            team_contribution=_text(get(row, "team_contribution")),
            incentive=_amount(get(row, "incentive")), remarks=_text(get(row, "remarks")),
            dns_columns=has_dns))
    return out

"""
masters_sheet.py - The masters as a Google Sheet (layout, write, read + check)
==============================================================================

WHAT THIS MODULE DOES
---------------------
The client edits the masters directly in ONE Google Sheet ("Drive N Style
Masters"); the staff can only view it. This module knows the layout of
that sheet and turns it into masters the calculation can use. It contains
NO Google code - it works on plain rows (lists of cell values), so it can
be tested without the internet. google_api.py fetches and sends the rows.

    to_tabs(masters, inputs)   the masters now in the tool -> rows per tab
                               (used once, to fill the new sheet)
    load_tabs(tabs)            rows per tab -> checked masters (LoadResult)
    refresh(read, ...)         read the sheet, check it, remember the last
                               good copy; fall back to that copy when the
                               sheet cannot be reached (no internet)

THE SHEET
---------
One tab per master, headings in row 1, one row per record below:

    Products          SKU | Product name | HSN/SAC | Category |
                      Incentive group | Selling price | Cost price |
                      Labour involved | Labour charge | Internal incentive |
                      Vehicle needed | Effective from | Active
    Sales executives  Name | Contact no | Branch | Gets incentive | Active
    Cars              Make | Model | Segment | Active
    Incentives        Product / Service | Incentive amount | Bill value |
                      Effective from | Active
    Packages          Package | Package item | Zoho item name | Active
    Settings          Setting | Value   (the two "% of COGS" percentages)

The headings and their order come from app/data/master_defs.py, the same
list that drives the monthly tool's Masters screen. Columns are found by
their HEADING, so the client may move a column or add one of their own
(an unknown column is ignored and mentioned).

DATED ROWS (rate history)
-------------------------
Selling price, cost price, labour charge (Products) and incentive amount,
bill value (Incentives) change over time. A change is NOT typed over the
old amount: the client adds a NEW ROW with the same name and a later
"Effective from" date. Example:

    Product name     Labour charge   Effective from
    Sunfilm - Front        500        01-04-2026
    Sunfilm - Front        600        01-11-2026    <- applies from 1 Nov

An invoice uses the amounts in force on its own date, so an invoice already
calculated never changes when a rate changes later. Rules:
    * the other columns (category, incentive group, labour involved ...)
      are taken from the row with the LATEST date;
    * two rows of the same name with the same date are an error;
    * "Effective from" may be left blank only when the name has ONE row
      (the amounts then apply to every date).

VALIDATE ON READ - NOTHING IS USED FROM A SHEET WITH A MISTAKE
--------------------------------------------------------------
A sheet typed by hand can hold mistakes that the monthly tool's Masters
screen would have refused. So every read runs the same checks:
    * a tab or a required column is missing
    * an amount that is not a number, a Yes/No cell holding something else,
      a date that cannot be read
    * a required cell is blank; an amount is negative
    * duplicates: product name / SKU, executive contact number, car make +
      model, incentive name, package row
    * contact number is not a 10-digit mobile
    * a product's incentive group is not in the Incentives tab; a package's
      Zoho item is not in the Products tab
The checks themselves are the monthly tool's own (MastersRepo): the rows
are loaded into a fresh, empty, in-memory database exactly as if they had
been typed on the Masters screen, and whatever it refuses is reported with
the tab and row number. If there is ANY problem the result is "not ok" and
carries no masters - the app then shows the list and calculates nothing,
so a wrong master can never produce a wrong payout silently.
(A blank amount counts as 0, as on the Masters screen.)

LAST GOOD COPY
--------------
Each successful read is saved as `masters_sheet_cache.json` in the data
folder. When the sheet cannot be reached, `refresh` uses that copy and
says from when it is. A sheet that WAS read but has problems is never
replaced by the copy - the problems must be fixed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from app.data.database import connect
from app.data.inputs_repo import AUTO_HEADS, InputsRepo
from app.data.master_defs import ALL_MASTERS, FieldDef, MasterDef, header_key
from app.data.masters_repo import MasterError, MastersRepo, RowChange
from app.data.paths import data_dir
from app.utils import parse_inr

SHEET_TITLE = "Drive N Style Masters"
SETTINGS_TAB = "Settings"
SETTINGS_HEADERS = ("Setting", "Value")
CACHE_FILE = "masters_sheet_cache.json"
SOURCE = "Masters sheet"

# Masters are loaded in this order because later ones refer to earlier
# ones: a product names its incentive group, a package names its products.
LOAD_ORDER = ("incentives", "products", "executives", "cars", "package_items")
MASTERS: dict[str, MasterDef] = {m.key: m for m in ALL_MASTERS}

# Amounts on a name's only row with no date apply to every date. The
# calculation uses the first dated row for any earlier day anyway
# (MastersRepo.rate_on), so the exact day does not matter.
ALWAYS = date(2000, 1, 1)
# Google Sheets (like Excel) stores a date as the number of days since
# 30-12-1899; a real date cell is read as that number.
SERIAL_DAY_ZERO = date(1899, 12, 30)
DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d",
                "%d-%b-%Y", "%d %b %Y", "%d-%m-%y", "%d/%m/%y")
YES = {"yes", "y", "true", "1"}
NO = {"no", "n", "false", "0"}


def tab_name(master: str) -> str:
    """The tab's name = the master's title ("Products", "Sales executives")."""
    return MASTERS[master].title


def headers(master: str) -> list[str]:
    """Row 1 of a master's tab: the field labels without the rupee sign."""
    return [_heading(f) for f in MASTERS[master].fields]


def _heading(f: FieldDef) -> str:
    return f.label.replace(" (₹)", "")


def date_to_serial(day: date) -> int:
    return (day - SERIAL_DAY_ZERO).days


# ---------------------------------------------------------------------------
# Tool -> sheet rows
# ---------------------------------------------------------------------------
def to_tabs(masters: MastersRepo, inputs: InputsRepo | None = None
            ) -> dict[str, list[list]]:
    """
    The masters now in the tool as rows per tab (row 1 = headings), with
    one row per dated change for Products and Incentives (oldest first).
    Cell values: text as text, amounts as numbers, Yes / No, and dates as
    date serial numbers (the sheet shows them as dd-mm-yyyy).
    """
    tabs: dict[str, list[list]] = {}
    for mdef in ALL_MASTERS:
        rows: list[list] = [headers(mdef.key)]
        records = sorted(masters.list_rows(mdef.key),
                         key=lambda r: MastersRepo.display_name(mdef.key, r).lower())
        for rec in records:
            if mdef.has_rates:
                history = sorted(masters.rate_history(mdef.key, rec["id"]),
                                 key=lambda h: h["effective_from"])
                for rate in history or [{}]:
                    rows.append([_cell(f, {**rec, **rate}.get(f.key))
                                 for f in mdef.fields])
            else:
                rows.append([_cell(f, rec.get(f.key)) for f in mdef.fields])
        tabs[mdef.title] = rows
    rates = inputs.auto_rates() if inputs is not None else \
        {key: default for key, _, default, _ in AUTO_HEADS}
    tabs[SETTINGS_TAB] = [list(SETTINGS_HEADERS)] + [
        [_setting_label(head), rates[key]] for key, head, _, _ in AUTO_HEADS]
    return tabs


def _setting_label(head: str) -> str:
    return f"{head} (% of COGS)"


def _cell(f: FieldDef, value):
    """One value as it is written into the sheet."""
    if f.kind == "bool":
        return "Yes" if value else "No"
    if f.kind == "money":
        return round(float(value or 0), 2)
    if f.kind == "date":
        return date_to_serial(value) if value else ""
    return str(value or "")


def tab_layout() -> dict[str, list[dict]]:
    """
    How each column of each tab is formatted in a NEW sheet (see
    google_api.format_requests): amounts as numbers with two decimals,
    dates as dd-mm-yyyy, Yes/No and fixed lists as drop-downs (a list that
    also takes new values, like the car segment, only suggests), and
    everything else as plain text so contact numbers and codes stay as typed.
    """
    layout: dict[str, list[dict]] = {}
    for mdef in ALL_MASTERS:
        columns = []
        for f in mdef.fields:
            if f.kind == "bool":
                columns.append({"kind": "yesno", "choices": (), "strict": True})
            elif f.kind == "choice":
                columns.append({"kind": "choice", "choices": tuple(f.choices),
                                "strict": not f.open_choice})
            elif f.kind in ("money", "date"):
                columns.append({"kind": f.kind, "choices": (), "strict": True})
            else:
                columns.append({"kind": "text", "choices": (), "strict": True})
        layout[mdef.title] = columns
    layout[SETTINGS_TAB] = [{"kind": "text", "choices": (), "strict": True},
                            {"kind": "money", "choices": (), "strict": True}]
    return layout


# ---------------------------------------------------------------------------
# Sheet rows -> checked masters
# ---------------------------------------------------------------------------
@dataclass
class LoadResult:
    """Outcome of reading the masters sheet."""
    problems: list[str] = field(default_factory=list)   # must be fixed
    notes: list[str] = field(default_factory=list)      # for information
    counts: dict[str, int] = field(default_factory=dict)  # tab -> records
    settings: dict[str, float] = field(default_factory=dict)
    masters: MastersRepo | None = None   # only when there is no problem
    from_cache: bool = False             # True = the last good copy was used
    read_at: str = ""                    # when the rows were read from Google

    @property
    def ok(self) -> bool:
        return not self.problems and self.masters is not None


class _Bad(Exception):
    """A cell that cannot be read; the message says why."""


def _is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _text(value) -> str:
    """A cell as text. A number typed for a phone / code loses its ".0"."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def _money(value) -> float:
    if _is_blank(value):
        return 0.0
    if isinstance(value, bool):
        raise _Bad("must be a number")
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    number = parse_inr(str(value))
    if number is None:
        raise _Bad(f"“{value}” is not a number")
    return round(number, 2)


def _yes_no(value, default: bool) -> bool:
    if _is_blank(value):
        return bool(default)
    if isinstance(value, bool):
        return value
    word = _text(value).lower()
    if word in YES:
        return True
    if word in NO:
        return False
    raise _Bad(f"must be Yes or No, not “{value}”")


def parse_sheet_date(value) -> date | None:
    """A date cell (serial number) or typed text -> date; blank -> None."""
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 20000 <= value <= 80000:              # years 1954 - 2119
            return SERIAL_DAY_ZERO + timedelta(days=int(value))
        raise _Bad(f"“{value}” is not a date")
    text = _text(value)
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise _Bad(f"“{value}” is not a date (use dd-mm-yyyy)")


def _convert(f: FieldDef, value):
    """One cell -> the field's value, or _Bad."""
    if f.kind == "money":
        return _money(value)
    if f.kind == "bool":
        return _yes_no(value, f.default)
    if f.kind == "date":
        return parse_sheet_date(value)
    text = _text(value)
    if f.kind == "choice" and text:
        # "product" / "PRODUCT" are the choice "Product"
        for choice in f.choices:
            if choice.lower() == text.lower():
                return choice
    if f.kind == "choice" and not text and not f.open_choice:
        return f.default
    return text


def _read_tab(mdef: MasterDef, rows: list[list], result: LoadResult
              ) -> list[tuple[int, dict]]:
    """
    One tab's rows -> [(sheet row number, values)], converting every cell.
    Problems are added to `result`; rows with a bad cell are left out (the
    result is "not ok" anyway).
    """
    tab = mdef.title
    if not rows or all(_is_blank(c) for c in rows[0]):
        result.problems.append(f"{tab}: the headings are missing in row 1.")
        return []
    by_key = {}
    for f in mdef.fields:
        by_key[header_key(_heading(f))] = f
        by_key[header_key(f.key)] = f
    columns: dict[int, FieldDef] = {}
    for i, head in enumerate(rows[0]):
        if _is_blank(head):
            continue
        f = by_key.get(header_key(head))
        if f is None:
            result.notes.append(f"{tab}: column “{head}” is not used.")
        elif f.key in {c.key for c in columns.values()}:
            result.problems.append(f"{tab}: the heading “{head}” appears twice.")
        else:
            columns[i] = f
    found = {f.key for f in columns.values()}
    for f in mdef.fields:
        if f.key not in found and (f.required or f.dated or f.kind == "date"):
            result.problems.append(f"{tab}: the column “{_heading(f)}” is missing.")
        elif f.key not in found:
            result.notes.append(f"{tab}: no column “{_heading(f)}” - "
                                "the usual value is used.")
    if any(p.startswith(f"{tab}:") and "missing" in p for p in result.problems):
        return []

    out: list[tuple[int, dict]] = []
    for n, row in enumerate(rows[1:], start=2):
        cells = {f.key: (row[i] if i < len(row) else None) for i, f in columns.items()}
        if all(_is_blank(v) for v in cells.values()):
            continue                                  # empty row
        values = {f.key: f.default for f in mdef.fields}
        bad = False
        for f in columns.values():
            try:
                values[f.key] = _convert(f, cells[f.key])
            except _Bad as exc:
                result.problems.append(f"{tab}, row {n}: {_heading(f)} {exc}.")
                bad = True
        if not bad:
            out.append((n, values))
    return out


def _group(mdef: MasterDef, records: list[tuple[int, dict]], result: LoadResult
           ) -> list[tuple[list[int], dict, list[tuple[date, dict]]]]:
    """
    Put the rows of one name together (see DATED ROWS above).
    Returns one entry per record: (its sheet rows, its values, its dated
    amounts oldest first). Tabs without dated values: one row per record;
    a repeated record is a problem.
    """
    tab = mdef.title
    groups: dict[str, list[tuple[int, dict]]] = {}
    for n, values in records:
        key = MastersRepo.key_of(mdef.key, values)
        if not key.strip("|"):
            key = f"row {n}"         # blank name: reported as "required" later
        groups.setdefault(key, []).append((n, values))

    out = []
    for rows in groups.values():
        numbers = [n for n, _ in rows]
        name = MastersRepo.display_name(mdef.key, rows[0][1]) or "(no name)"
        if not mdef.has_rates:
            if len(rows) > 1:
                result.problems.append(
                    f"{tab}, rows {_list(numbers)}: “{name}” is entered more than "
                    "once. Duplicates are not allowed.")
            out.append((numbers, rows[0][1], []))
            continue
        if len(rows) > 1 and any(v["effective_from"] is None for _, v in rows):
            blank = [n for n, v in rows if v["effective_from"] is None]
            result.problems.append(
                f"{tab}, row{'s' if len(blank) > 1 else ''} {_list(blank)}: “{name}” "
                "has several rows, so each needs an Effective from date.")
            continue
        dated: dict[date, int] = {}
        clash = False
        for n, v in rows:
            day = v["effective_from"] or ALWAYS
            if day in dated:
                result.problems.append(
                    f"{tab}, rows {dated[day]} and {n}: “{name}” has two rows "
                    f"with the same Effective from date ({day:%d-%m-%Y}).")
                clash = True
            dated[day] = n
        if clash:
            continue
        rows = sorted(rows, key=lambda r: r[1]["effective_from"] or ALWAYS)
        latest = rows[-1][1]
        rates = [(v["effective_from"] or ALWAYS,
                  {f.key: v[f.key] for f in mdef.dated_fields}) for _, v in rows]
        out.append((numbers, latest, rates))
    return out


def _list(numbers: list[int]) -> str:
    numbers = [str(n) for n in numbers]
    return numbers[0] if len(numbers) == 1 else \
        ", ".join(numbers[:-1]) + " and " + numbers[-1]


def _read_settings(rows: list[list] | None, result: LoadResult) -> None:
    """The Settings tab: the two percentages, 0 - 100. Missing = defaults."""
    result.settings = {key: default for key, _, default, _ in AUTO_HEADS}
    if not rows:
        result.notes.append(f"{SETTINGS_TAB}: tab not found - the usual "
                            "percentages are used.")
        return
    wanted = {header_key(head): (key, head) for key, head, _, _ in AUTO_HEADS}
    for n, row in enumerate(rows[1:], start=2):
        if not row or _is_blank(row[0]):
            continue
        hit = next((v for k, v in wanted.items() if header_key(row[0]).startswith(k)), None)
        if hit is None:
            result.notes.append(f"{SETTINGS_TAB}, row {n}: “{row[0]}” is not used.")
            continue
        key, head = hit
        try:
            pct = _money(row[1] if len(row) > 1 else None)
        except _Bad as exc:
            result.problems.append(f"{SETTINGS_TAB}, row {n}: {head} {exc}.")
            continue
        if not 0 <= pct <= 100:
            result.problems.append(f"{SETTINGS_TAB}, row {n}: {head} must be "
                                   "between 0 and 100.")
        else:
            result.settings[key] = pct


def load_tabs(tabs: dict[str, list[list]]) -> LoadResult:
    """
    Check the sheet's rows and build the masters from them.
    `tabs` maps a tab's name to its rows (row 1 = headings), as read from
    Google or produced by `to_tabs`. See VALIDATE ON READ above.
    """
    result = LoadResult()
    by_name = {header_key(name): rows for name, rows in tabs.items()}
    repo = MastersRepo(connect(":memory:"), user=SOURCE)

    for master in LOAD_ORDER:
        mdef = MASTERS[master]
        tab = mdef.title
        rows = by_name.get(header_key(tab))
        if rows is None:
            result.problems.append(f"The tab “{tab}” is missing from the sheet.")
            continue
        entries = _group(mdef, _read_tab(mdef, rows, result), result)
        seen_sku: dict[str, int] = {}
        loaded = 0
        for numbers, values, rates in entries:
            where = f"{tab}, row {numbers[-1]}"
            sku = str(values.get("sku", "")).strip().lower() if master == "products" else ""
            if sku and sku in seen_sku:
                result.problems.append(
                    f"{tab}, rows {seen_sku[sku]} and {numbers[-1]}: SKU "
                    f"{values['sku']} is used by two products.")
                continue
            first_day, first_amounts = rates[0] if rates else (None, {})
            try:
                repo.save(master, [RowChange(None, {**values, **first_amounts},
                                             first_day)], source=SOURCE)
                row_id = repo.find_id(master, values)
                for day, amounts in rates[1:]:
                    repo.save(master, [RowChange(row_id, {**values, **amounts}, day)],
                              source=SOURCE)
            except MasterError as exc:
                for message in exc.messages:
                    # "Name: what is wrong" -> "Products, row 12: Name: what ..."
                    result.problems.append(f"{where}: {message}")
                continue
            if sku:
                seen_sku[sku] = numbers[-1]
            loaded += 1
        result.counts[tab] = loaded

    _read_settings(by_name.get(header_key(SETTINGS_TAB)), result)
    result.problems = list(dict.fromkeys(result.problems))
    result.notes = list(dict.fromkeys(result.notes))
    if not result.problems:
        result.masters = repo
    return result


# ---------------------------------------------------------------------------
# Last good copy, and the one call the app uses
# ---------------------------------------------------------------------------
def cache_path() -> Path:
    return data_dir() / CACHE_FILE


def save_cache(tabs: dict[str, list[list]], read_at: str) -> None:
    cache_path().write_text(json.dumps({"read_at": read_at, "tabs": tabs}),
                            encoding="utf-8")


def load_cache() -> tuple[dict[str, list[list]], str] | None:
    """(rows per tab, when read) of the last good copy, or None."""
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
        return data["tabs"], str(data.get("read_at", ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def refresh(read: Callable[[], dict[str, list[list]]],
            now: Callable[[], datetime] = datetime.now) -> LoadResult:
    """
    Read the masters sheet with `read()` (google_api does the fetching),
    check it and return the result.

        sheet read, no problem   -> masters from the sheet; copy saved
        sheet read, problems     -> the problems; NO masters (not even the
                                    saved copy - the sheet must be fixed)
        sheet cannot be reached  -> the last good copy, marked from_cache,
                                    with a note saying from when; if there
                                    is no copy yet, a problem saying so
    """
    try:
        tabs = read()
    except Exception as exc:                      # no internet, sign-in failed ...
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else \
            exc.__class__.__name__
        cached = load_cache()
        if cached is None:
            result = LoadResult()
            result.problems.append(
                f"The masters sheet could not be read ({reason}) and no earlier "
                "copy is saved on this PC yet.")
            return result
        result = load_tabs(cached[0])
        result.from_cache = True
        result.read_at = cached[1]
        result.notes.insert(0, f"The masters sheet could not be read ({reason}). "
                               f"Using the copy read on {cached[1]}.")
        return result
    result = load_tabs(tabs)
    result.read_at = now().strftime("%d-%m-%Y %H:%M")
    if result.ok:
        save_cache(tabs, result.read_at)
    return result

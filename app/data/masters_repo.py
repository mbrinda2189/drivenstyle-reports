"""
masters_repo.py - Reading and saving the masters (with audit log)
=================================================================

WHAT THIS MODULE DOES
---------------------
All reading and writing of the Product, Sales executive, Car and Incentive
masters goes through `MastersRepo`. The screens never write SQL themselves.

    list_rows(master)              rows for the Masters screen
    get(master, id)                one row
    save(master, changes)          store rows added / edited on screen
    import_records(master, ...)    store rows read from the client's sheet
    delete(master, ids)            delete rows (bulk "Delete selected / all")
    set_active(master, ids, flag)  bulk "Mark active / inactive"
    rate_on(master, id, day)       dated values that applied on a given day
    rate_history(master, id)       every dated change of one row
    lookup_names(master)           names offered in a lookup drop-down
    counts()                       number of active rows per master
    audit_entries(...)             read the audit log, with filters
    get_mapping / set_mapping      remember the column matches of an import

AUDIT LOG
---------
Every change is written to `audit_log` in the SAME transaction as the
change itself, so a change can never be saved without its log entry (or
the other way round). One entry per changed field:

    Added        new row; "New value" lists all its values
    Edited       one field changed: old value -> new value. For dated
                 values the new value shows the date it applies from,
                 e.g. "9,500.00 from 01-10-2026".
    Activated / Deactivated
    Deleted      "Old value" lists everything the row held

Each entry also records the time, the Windows user name and the source
("Masters screen", "Import: product_master.xlsx").
The database refuses any change to or deletion of audit rows.

HOW DATED VALUES WORK
---------------------
Product selling price / cost price / labour charge and incentive amount /
bill value are stored in a rate table, one row per change, each with an
`effective_from` date.
    * The value on a given day is the row with the latest effective_from
      on or before that day.
    * For a day before the first row, the first row is used (so months
      before the masters were first loaded still have values).
    * The Masters screen shows the most recent row, with its date.

NO DUPLICATES
-------------
    Product          product name, and SKU when given
    Sales executive  contact no (digits only, last 10: "+91 98765 43210"
                     and "9876543210" are the same number). It must be a
                     10-digit mobile number (valid_mobile); a short or long
                     number is refused on save and left out on import.
    Car              make + model
    Incentive        product / service name
Names are compared in a standard form (`name_key`): lower case, single
spaces, all dash characters as "-". Duplicates are refused on save (with a
message naming the existing row) and on import (the row is left out and
listed; repeated rows inside one sheet: the later row is used and noted).

ERRORS
------
Problems the user must fix raise `MasterError` with plain-language
messages. Nothing is saved when that happens: each save runs in one
transaction.
"""

from __future__ import annotations

import getpass
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

from app.data.master_defs import (
    MASTERS_BY_KEY, FieldDef, MasterDef, counter_item_default)
from app.utils import format_inr


# ---------------------------------------------------------------------------
# Standard forms used to spot duplicates
# ---------------------------------------------------------------------------
def name_key(text: str) -> str:
    """Standard form of a name, used to spot the same item written twice."""
    text = str(text or "").strip().lower()
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)   # all dashes -> "-"
    return re.sub(r"\s+", " ", text)


def car_key(make: str, model: str) -> str:
    """Standard form of make + model, e.g. 'tata|nexon'."""
    return f"{name_key(make)}|{name_key(model)}"


def phone_key(text: str) -> str:
    """
    Contact number as digits only; numbers longer than 10 digits (with
    +91 or a leading 0) are cut to the last 10. Empty if no digits.
    """
    digits = re.sub(r"\D", "", str(text or ""))
    return digits[-10:] if len(digits) > 10 else digits


def valid_mobile(text: str) -> bool:
    """
    True for an Indian mobile number: exactly 10 digits, optionally written
    with +91 / 91 in front or a leading 0, and with spaces or dashes
    ("+91 98765 43210", "098765-43210", "9876543210"). Excel sometimes
    stores numbers as 9876543210.0; the ".0" is ignored.
    """
    raw = str(text or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return len(digits) == 10


def infer_category(hsn_sac: str) -> str:
    """
    Guess Product / Service from an HSN/SAC code when the sheet has no
    category column. In India, service codes (SAC) are 6 digits starting
    with 99; goods codes (HSN) never start with 99.
    """
    digits = re.sub(r"\D", "", str(hsn_sac or ""))
    return "Service" if digits.startswith("99") else "Product"


def _iso(day: date) -> str:
    return day.isoformat()


def _from_iso(text: str) -> date:
    return date.fromisoformat(text)


# ---------------------------------------------------------------------------
# How each master is stored
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Store:
    """Database layout of one master."""
    table: str
    key_column: str                  # unique matching key column
    columns: tuple[str, ...]         # fields stored directly in the table
    order_by: str                    # list order (after active rows first)
    rate_table: str = ""             # table of dated values, if any
    rate_fk: str = ""                # its column pointing at the row


STORES = {
    "products": Store("products", "name_key",
                      ("sku", "name", "hsn_sac", "category", "has_labour",
                       "vehicle_needed", "active"),
                      "t.name COLLATE NOCASE", "product_rates", "product_id"),
    "executives": Store("executives", "phone_key",
                        ("name", "phone", "branch", "active"),
                        "t.name COLLATE NOCASE, t.phone"),
    "cars": Store("cars", "car_key", ("make", "model", "segment", "active"),
                  "t.make COLLATE NOCASE, t.model COLLATE NOCASE"),
    "incentives": Store("incentives", "name_key", ("name", "active"),
                        "t.name COLLATE NOCASE", "incentive_rates",
                        "incentive_id"),
}


class MasterError(Exception):
    """Raised with a list of plain-language problems; nothing was saved."""

    def __init__(self, messages: list[str]):
        super().__init__("\n".join(messages))
        self.messages = messages


@dataclass
class RowChange:
    """
    One row added or edited on the Masters screen.

    id         database id, or None for a new row
    values     field key -> value, for every field of the master
    rate_date  the date changed dated values apply from (None = today)
    """
    id: int | None
    values: dict
    rate_date: date | None = None


@dataclass
class ImportResult:
    """What an import did, shown to the user as a summary."""
    added: int = 0
    updated: int = 0
    rates_changed: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)   # rows not imported
    warnings: list[str] = field(default_factory=list)  # imported, but note this
    not_added: int = 0             # new names left out because add_new=False


def _windows_user() -> str:
    try:
        return getpass.getuser()
    except Exception:                                  # no user name available
        return ""


# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------
class MastersRepo:
    """Read and write the masters in an open SQLite connection."""

    def __init__(self, conn: sqlite3.Connection, user: str | None = None):
        self.conn = conn
        self.user = _windows_user() if user is None else user

    @staticmethod
    def definition(master: str) -> MasterDef:
        return MASTERS_BY_KEY[master]

    # ==================================================================
    # Reading
    # ==================================================================
    def _select(self, master: str, where: str = "", params: tuple = ()):
        """Rows of `master` with their latest dated values (and, for
        products, the incentive group's name)."""
        st = STORES[master]
        mdef = self.definition(master)
        cols, joins = ["t.*"], []
        if st.rate_table:
            cols.append("r.effective_from")
            cols += [f"r.{f.key}" for f in mdef.dated_fields]
            joins.append(
                f"LEFT JOIN {st.rate_table} r ON r.id = (SELECT id FROM "
                f"{st.rate_table} WHERE {st.rate_fk} = t.id "
                "ORDER BY effective_from DESC LIMIT 1)")
        if master == "products":
            cols.append("i.name AS incentive_group")
            joins.append("LEFT JOIN incentives i ON i.id = t.incentive_id")
        sql = (f"SELECT {', '.join(cols)} FROM {st.table} t {' '.join(joins)} "
               f"{where} ORDER BY t.active DESC, {st.order_by}")
        return self.conn.execute(sql, params).fetchall()

    def list_rows(self, master: str) -> list[dict]:
        """
        All rows of a master as dicts (field key -> value, plus "id"),
        active rows first, then by name.
        """
        return [self._row_to_dict(master, r) for r in self._select(master)]

    def get(self, master: str, row_id: int) -> dict | None:
        rows = self._select(master, "WHERE t.id = ?", (row_id,))
        return self._row_to_dict(master, rows[0]) if rows else None

    def _row_to_dict(self, master: str, row: sqlite3.Row) -> dict:
        """Convert a database row into field values of the right types."""
        out = {"id": row["id"]}
        for f in self.definition(master).fields:
            value = row[f.key] if f.key in row.keys() else None
            if f.kind == "bool":
                value = bool(value)
            elif f.kind == "money":
                value = float(value or 0)
            elif f.kind == "date":
                value = _from_iso(value) if value else None
            else:
                value = value or ""
            out[f.key] = value
        return out

    def lookup_names(self, master: str, active_only: bool = True) -> list[str]:
        """Names of a master's rows, for a lookup drop-down (A-Z)."""
        where = "WHERE active = 1" if active_only else ""
        return [r["name"] for r in self.conn.execute(
            f"SELECT name FROM {STORES[master].table} {where} "
            "ORDER BY name COLLATE NOCASE")]

    def rate_history(self, master: str, row_id: int) -> list[dict]:
        """Every dated row of a product / incentive, newest first."""
        st, mdef = STORES[master], self.definition(master)
        rows = self.conn.execute(
            f"SELECT * FROM {st.rate_table} WHERE {st.rate_fk} = ? "
            "ORDER BY effective_from DESC", (row_id,)).fetchall()
        return [self._rate_dict(mdef, r) for r in rows]

    def rate_on(self, master: str, row_id: int, day: date) -> dict | None:
        """
        The dated values that applied on `day`: the latest change on or
        before that day, or the first one if `day` is earlier than all.
        None if the row has no dated values at all.
        """
        st, mdef = STORES[master], self.definition(master)
        row = self.conn.execute(
            f"SELECT * FROM {st.rate_table} WHERE {st.rate_fk} = ? "
            "AND effective_from <= ? ORDER BY effective_from DESC LIMIT 1",
            (row_id, _iso(day))).fetchone()
        if row is None:
            row = self.conn.execute(
                f"SELECT * FROM {st.rate_table} WHERE {st.rate_fk} = ? "
                "ORDER BY effective_from ASC LIMIT 1", (row_id,)).fetchone()
        return self._rate_dict(mdef, row) if row else None

    @staticmethod
    def _rate_dict(mdef: MasterDef, row: sqlite3.Row) -> dict:
        return {"effective_from": _from_iso(row["effective_from"]),
                **{f.key: float(row[f.key]) for f in mdef.dated_fields}}

    def counts(self) -> dict[str, int]:
        """Number of ACTIVE rows in each master (for the Generate screen)."""
        return {m: self.conn.execute(
                    f"SELECT COUNT(*) FROM {st.table} WHERE active = 1"
                ).fetchone()[0] for m, st in STORES.items()}

    # ==================================================================
    # Remembered column matches
    # ==================================================================
    def get_mapping(self, master: str) -> dict[str, str]:
        """field key -> sheet column heading, as matched at the last import."""
        rows = self.conn.execute(
            "SELECT field, column_header FROM import_mappings WHERE master = ?",
            (master,)).fetchall()
        return {r["field"]: r["column_header"] for r in rows}

    def set_mapping(self, master: str, mapping: dict[str, str]) -> None:
        """Replace the remembered matches for `master`."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM import_mappings WHERE master = ?", (master,))
            self.conn.executemany(
                "INSERT INTO import_mappings(master, field, column_header) "
                "VALUES (?, ?, ?)",
                [(master, f, h) for f, h in mapping.items() if h])

    # ==================================================================
    # Checks shared by save and import
    # ==================================================================
    @staticmethod
    def key_of(master: str, v: dict) -> str:
        """The value that must be unique for this master."""
        if master == "cars":
            return car_key(v.get("make", ""), v.get("model", ""))
        if master == "executives":
            return phone_key(v.get("phone", ""))
        return name_key(v.get("name", ""))

    @staticmethod
    def display_name(master: str, v: dict) -> str:
        """How a row is named in messages and in the audit log."""
        if master == "cars":
            return " ".join(p for p in (str(v.get("make", "")).strip(),
                                        str(v.get("model", "")).strip()) if p)
        name = str(v.get("name", "")).strip()
        if master == "executives" and str(v.get("phone", "")).strip():
            return f"{name} ({str(v['phone']).strip()})"
        return name

    def _find_id(self, master: str, key: str) -> int | None:
        """Database id of the row with this unique key, or None."""
        if not key.strip("|"):
            return None
        st = STORES[master]
        row = self.conn.execute(
            f"SELECT id FROM {st.table} WHERE {st.key_column} = ?",
            (key,)).fetchone()
        return row["id"] if row else None

    def _incentive_id(self, name: str) -> int | None:
        return self._find_id("incentives", name_key(name)) if name else None

    def _row_problems(self, master: str, row_id: int | None, v: dict) -> list[str]:
        """Everything wrong with one row (empty list = fine)."""
        mdef = self.definition(master)
        label = self.display_name(master, v) or f"New {mdef.singular}"
        problems = []
        for f in mdef.fields:
            value = v.get(f.key)
            if f.required and not str(value or "").strip():
                problems.append(f"{label}: {f.label} is required.")
            elif f.kind == "money" and float(value or 0) < 0:
                problems.append(f"{label}: {f.label} cannot be negative.")
            elif (f.kind == "choice" and not f.open_choice
                    and value not in f.choices):
                problems.append(f"{label}: {f.label} must be one of "
                                f"{', '.join(f.choices)}.")
            elif f.kind == "lookup" and str(value or "").strip() \
                    and self._incentive_id(value) is None:
                problems.append(f"{label}: {f.label} “{value}” is not in the "
                                f"{self.definition(f.lookup).title} master.")

        if master == "executives" and str(v.get("phone", "")).strip() \
                and not valid_mobile(v["phone"]):
            problems.append(f"{label}: contact number “{v['phone']}” must have "
                            "10 digits (+91 or a leading 0 may be added).")

        clash = self._find_id(master, self.key_of(master, v))
        if clash is not None and clash != row_id:
            other = self.display_name(master, self.get(master, clash))
            what = {"executives": "contact number",
                    "cars": "make and model"}.get(master, "name")
            problems.append(
                f"{label}: the {what} is already used by “{other}”. "
                "Duplicates are not allowed.")

        if master == "products":
            sku = str(v.get("sku", "")).strip()
            if sku:
                other = self.conn.execute(
                    "SELECT id, name FROM products WHERE sku = ? "
                    "COLLATE NOCASE", (sku,)).fetchone()
                if other is not None and other["id"] != row_id:
                    problems.append(
                        f"{label}: SKU {sku} already belongs to "
                        f"“{other['name']}”.")
        return problems

    # ==================================================================
    # Writing one row (used by save and import) - with audit entries
    # ==================================================================
    @staticmethod
    def _db_value(f: FieldDef, value):
        """A field value as stored in the database."""
        if f.kind == "bool":
            return int(bool(value))
        if f.kind == "money":
            return round(float(value or 0), 2)
        return " ".join(str(value or "").split())

    @staticmethod
    def _show(f: FieldDef, value) -> str:
        """A field value as written in the audit log."""
        if f.kind == "bool":
            return "Yes" if value else "No"
        if f.kind == "money":
            return format_inr(float(value or 0))
        if f.kind == "date":
            return value.strftime("%d-%m-%Y") if value else ""
        return " ".join(str(value or "").split())

    def _summary(self, master: str, v: dict) -> str:
        """All values of a row in one line, for Added / Deleted entries."""
        parts = []
        for f in self.definition(master).fields:
            if f.kind == "date":
                continue
            shown = self._show(f, v.get(f.key))
            if shown and not (f.kind == "money" and not v.get(f.key)):
                parts.append(f"{f.label}: {shown}")
        return "; ".join(parts)

    def _audit(self, master: str, record_id, record: str, action: str,
               field_label: str = "", old: str = "", new: str = "",
               source: str = "") -> None:
        self.conn.execute(
            "INSERT INTO audit_log(at, user, master, record_id, record, action, "
            "field, old_value, new_value, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), self.user, master,
             record_id, record, action, field_label, old, new, source))

    def _put_rate(self, master: str, row_id: int, day: date, v: dict) -> None:
        """Insert a dated row, or overwrite the one already on that date."""
        st, mdef = STORES[master], self.definition(master)
        keys = [f.key for f in mdef.dated_fields]
        self.conn.execute(
            f"INSERT INTO {st.rate_table}({st.rate_fk}, effective_from, "
            f"{', '.join(keys)}) VALUES (?, ?, {', '.join('?' * len(keys))}) "
            f"ON CONFLICT({st.rate_fk}, effective_from) DO UPDATE SET "
            + ", ".join(f"{k} = excluded.{k}" for k in keys),
            (row_id, _iso(day), *[round(float(v.get(k) or 0), 2) for k in keys]))

    def _write_row(self, master: str, row_id: int | None, v: dict,
                   rate_date: date | None, source: str,
                   replace_later: bool = False) -> tuple[int, str, bool]:
        """
        Insert or update one row and log what changed.
        Returns (id, "added" / "updated" / "unchanged", dated values changed).
        The caller has already checked the row with _row_problems.
        """
        st, mdef = STORES[master], self.definition(master)
        cols = {c: self._db_value(mdef.get_field(c), v.get(c)) for c in st.columns}
        cols[st.key_column] = self.key_of(master, v)
        if master == "products":
            cols["incentive_id"] = self._incentive_id(
                str(v.get("incentive_group") or "").strip())
        label = self.display_name(master, v)
        day = rate_date or date.today()

        if row_id is None:
            cur = self.conn.execute(
                f"INSERT INTO {st.table}({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
            new_id = cur.lastrowid
            summary = self._summary(master, v)
            if st.rate_table:
                self._put_rate(master, new_id, day, v)
                summary += f" (amounts from {day:%d-%m-%Y})"
            self._audit(master, new_id, label, "Added", new=summary, source=source)
            return new_id, "added", False

        old = self.get(master, row_id)
        changed = False
        for f in mdef.fields:
            if f.kind == "date" or f.dated:
                continue
            before, after = self._show(f, old.get(f.key)), self._show(f, v.get(f.key))
            if before == after:
                continue
            changed = True
            if f.key == "active":
                self._audit(master, row_id, label,
                            "Activated" if v.get("active") else "Deactivated",
                            source=source)
            else:
                self._audit(master, row_id, label, "Edited", f.label,
                            before, after, source)
        if changed:
            self.conn.execute(
                f"UPDATE {st.table} SET {', '.join(c + ' = ?' for c in cols)} "
                "WHERE id = ?", (*cols.values(), row_id))

        rate_changed = False
        if st.rate_table:
            # replace_later (v0.7.1, Zoho item list): Zoho's prices are
            # final FROM `day` ONWARDS. So the amounts are compared with
            # those in force on `day` (not the latest ones), and dated rows
            # after `day` are removed - otherwise a later row holding the
            # staff sheet's old price would still win for later months.
            base = (self.rate_on(master, row_id, day) or old) if replace_later else old
            diffs = [f for f in mdef.dated_fields
                     if abs(float(v.get(f.key) or 0)
                            - float(base.get(f.key) or 0)) > 0.004]
            old = base
            if replace_later:
                later = self.conn.execute(
                    f"DELETE FROM {st.rate_table} WHERE {st.rate_fk} = ? "
                    "AND effective_from > ?", (row_id, _iso(day))).rowcount
                if later and not diffs:
                    # the day's amounts are right but later rows were dropped:
                    # keep a row on the day so the values stay dated correctly
                    self._put_rate(master, row_id, day, v)
                    rate_changed = True
                    self._audit(master, row_id, label, "Edited",
                                "Amounts apply from", "",
                                f"{day:%d-%m-%Y} (later dated amounts removed)",
                                source)
            if diffs:
                self._put_rate(master, row_id, day, v)
                rate_changed = True
                for f in diffs:
                    self._audit(master, row_id, label, "Edited", f.label,
                                self._show(f, old.get(f.key)),
                                f"{self._show(f, v.get(f.key))} from {day:%d-%m-%Y}",
                                source)
        return row_id, ("updated" if changed or rate_changed else "unchanged"), \
            rate_changed

    # ==================================================================
    # Saving edits from the Masters screen
    # ==================================================================
    def save(self, master: str, changes: list[RowChange],
             source: str = "Masters screen") -> None:
        """
        Store added and edited rows in one transaction, with audit entries.
        Raises MasterError (and saves nothing) if any row has a problem.
        """
        problems: list[str] = []
        seen: dict[str, str] = {}
        seen_sku: set[str] = set()
        for ch in changes:
            problems += self._row_problems(master, ch.id, ch.values)
            key = self.key_of(master, ch.values)
            label = self.display_name(master, ch.values)
            if key.strip("|"):
                if key in seen:
                    problems.append(f"“{label}” is entered twice (same as "
                                    f"“{seen[key]}”).")
                seen[key] = label
            sku = str(ch.values.get("sku", "")).strip().lower()
            if sku:
                if sku in seen_sku:
                    problems.append(f"SKU {ch.values['sku']} is entered twice.")
                seen_sku.add(sku)
        if problems:
            raise MasterError(list(dict.fromkeys(problems)))   # no repeats
        try:
            with self.conn:
                for ch in changes:
                    old_cat = (self.get(master, ch.id) or {}).get("category") \
                        if master == "products" and ch.id is not None else None
                    new_id, _, _ = self._write_row(master, ch.id, ch.values,
                                                   ch.rate_date, source)
                    # A category chosen on the Masters screen (new product, or
                    # category changed) is final: Zoho's item type never
                    # overrides it (v0.6.5).
                    if master == "products" and source == "Masters screen" and (
                            ch.id is None or old_cat != ch.values.get("category")):
                        self._fix_category(new_id)
        except sqlite3.IntegrityError as exc:       # safety net
            raise MasterError([f"Could not save: {exc}"]) from exc

    # ==================================================================
    # Bulk actions
    # ==================================================================
    def delete(self, master: str, ids: list[int],
               source: str = "Masters screen") -> int:
        """
        Permanently delete rows (and their dated history). Each deletion is
        logged with everything the row held. Deleting an incentive row
        clears the Incentive group of the products linked to it (logged
        too). Returns the number of rows deleted.
        """
        st = STORES[master]
        done = 0
        with self.conn:
            for row_id in ids:
                row = self.get(master, row_id)
                if row is None:
                    continue
                label = self.display_name(master, row)
                if master == "incentives":
                    for p in self.conn.execute(
                            "SELECT id, name FROM products WHERE incentive_id = ?",
                            (row_id,)).fetchall():
                        self._audit("products", p["id"], p["name"], "Edited",
                                    "Incentive group", row["name"], "",
                                    f"{source} (incentive deleted)")
                self._audit(master, row_id, label, "Deleted",
                            old=self._summary(master, row), source=source)
                self.conn.execute(f"DELETE FROM {st.table} WHERE id = ?", (row_id,))
                done += 1
        return done

    def set_active(self, master: str, ids: list[int], active: bool,
                   source: str = "Masters screen") -> int:
        """Mark rows active / inactive. Returns how many actually changed."""
        st = STORES[master]
        done = 0
        with self.conn:
            for row_id in ids:
                row = self.get(master, row_id)
                if row is None or bool(row["active"]) == active:
                    continue
                self.conn.execute(f"UPDATE {st.table} SET active = ? WHERE id = ?",
                                  (int(active), row_id))
                self._audit(master, row_id, self.display_name(master, row),
                            "Activated" if active else "Deactivated",
                            source=source)
                done += 1
        return done

    # ==================================================================
    # Importing rows read from the client's sheet
    # ==================================================================
    def import_records(self, master: str, records: list[dict],
                       effective_from: date | None = None,
                       source: str = "Import", add_new: bool = True,
                       replace_later: bool = False) -> ImportResult:
        """
        Add new rows and update existing ones from an imported sheet.

        records         dicts produced by excel_io.convert_rows: only the
                        fields the user matched to a column are present,
                        plus "_row" (the row number in the sheet).
        replace_later   True (Zoho item list): the amounts are final from
                        `effective_from` onwards - see _write_row.
        add_new         False = only update rows already in the master;
                        rows with a new name are left out and counted
                        (v0.7.0: the staff sheet then only supplies labour /
                        incentive for the items of Zoho's list, without
                        bringing its own item names back).
        effective_from  the date new or changed dated values apply from.

        Existing rows are found by their unique key (products: SKU first,
        then name). Fields not matched to any column keep their current
        value; for new rows they take their default. A row that is inactive
        but appears in the sheet is made active again. Rows with a problem
        are left out and listed; everything else is saved in one
        transaction, with audit entries.
        """
        mdef = self.definition(master)
        result = ImportResult()
        if master == "products":
            records = self._drop_shared_codes(records, result)
        outcome_of: dict[int, str] = {}   # id -> best outcome (repeats count once)
        first_row: dict[int, object] = {}
        rank = {"added": 3, "updated": 2, "unchanged": 1}
        with self.conn:
            for rec in records:
                row_no = rec.get("_row", "?")
                row_id, problem = self._find_for_import(master, rec)
                if problem:
                    result.skipped.append(f"Row {row_no}: {problem}")
                    continue

                if row_id is None and not add_new:
                    result.not_added += 1
                    continue
                # Start from the stored row (or defaults) and overlay the sheet.
                if row_id is None:
                    merged = {f.key: f.default for f in mdef.fields}
                else:
                    merged = dict(self.get(master, row_id))
                for key, value in rec.items():
                    if key == "_row":
                        continue
                    kind = mdef.get_field(key).kind
                    if kind in ("money", "bool") or str(value or "").strip():
                        merged[key] = value
                if "active" not in rec:
                    merged["active"] = True
                if master == "products" and row_id is None:
                    if not rec.get("category"):
                        merged["category"] = infer_category(merged.get("hsn_sac"))
                    if "vehicle_needed" not in rec:
                        merged["vehicle_needed"] = counter_item_default(merged.get("name"))
                if master == "products" and "has_labour" not in rec and (
                        row_id is None or "labour_charge" in rec):
                    # No "Labour involved" column: Yes when the labour charge
                    # is above zero. Also for an EXISTING product whose labour
                    # charge the sheet gives (v0.7.0: the staff sheet adds
                    # labour to items that came from Zoho's list).
                    merged["has_labour"] = float(merged.get("labour_charge") or 0) > 0
                if master == "products" and merged.get("incentive_group") and \
                        self._incentive_id(merged["incentive_group"]) is None:
                    result.warnings.append(
                        f"Row {row_no}: incentive group “{merged['incentive_group']}”"
                        " is not in the Incentive master; left blank.")
                    merged["incentive_group"] = "" if row_id is None else \
                        self.get(master, row_id)["incentive_group"]

                problems = self._row_problems(master, row_id, merged)
                if problems:
                    result.skipped.append(f"Row {row_no}: " + " ".join(
                        p.split(": ", 1)[-1] for p in problems))
                    continue

                new_id, what, rate_changed = self._write_row(
                    master, row_id, merged, effective_from, source,
                    replace_later=replace_later)
                if master == "products" and rec.get("category"):
                    # The sheet gave a category: it is the client's choice
                    # and Zoho's item type must not change it (v0.6.5).
                    self._fix_category(new_id)
                result.rates_changed += int(rate_changed)
                if new_id in first_row:
                    result.warnings.append(
                        f"Row {row_no} repeats row {first_row[new_id]} "
                        f"(“{self.display_name(master, merged)}”); the later "
                        "row was used.")
                else:
                    first_row[new_id] = row_no
                if rank[what] > rank.get(outcome_of.get(new_id, ""), 0):
                    outcome_of[new_id] = what
        for what in outcome_of.values():
            setattr(result, what, getattr(result, what) + 1)
        return result

    # ------------------------------------------------------------------
    # Zoho's item list as the Product master (v0.7.0)
    # ------------------------------------------------------------------
    @staticmethod
    def split_zoho_items(records: list[dict]) -> tuple[list[dict], list[str]]:
        """
        (records to import, names of the Rs. 1 labour items left out).
        Zoho's item list also holds the labour marker items ("Labour Charges
        for Sunfilm - Front" ...). They are not products - the reports
        ignore those invoice lines - so they are not imported.
        """
        from app.data.invoices_repo import is_labour_marker   # avoid a cycle
        keep, markers = [], []
        for rec in records:
            if is_labour_marker(str(rec.get("name", ""))):
                markers.append(str(rec.get("name")))
            else:
                keep.append(rec)
        return keep, markers

    def products_not_in(self, names: list[str]) -> list[dict]:
        """Products of the master whose name is not in `names` (Zoho's list)."""
        wanted = {name_key(n) for n in names}
        return [p for p in self.list_rows("products")
                if name_key(p["name"]) not in wanted]

    @staticmethod
    def _drop_shared_codes(records: list[dict], result: ImportResult) -> list[dict]:
        """
        A CODE (SKU) used on rows with DIFFERENT item names in one sheet
        cannot identify an item: matching by it made each such row
        overwrite the previous one, so only the last survived (the client's
        sheet had e.g. the HSN 87089900 typed as the CODE of four items).
        Those rows are imported without the CODE - each as its own item,
        found by name - and a warning lists them (v0.6.5). A CODE repeated
        on rows with the SAME name is left alone (a genuine repeat).
        """
        names: dict[str, set[str]] = {}
        rows: dict[str, list] = {}
        for rec in records:
            sku = str(rec.get("sku") or "").strip().lower()
            if sku:
                names.setdefault(sku, set()).add(name_key(rec.get("name", "")))
                rows.setdefault(sku, []).append(rec.get("_row", "?"))
        shared = {s for s, n in names.items() if len(n) > 1}
        if not shared:
            return records
        out = []
        for rec in records:
            sku = str(rec.get("sku") or "").strip().lower()
            if sku in shared:
                rec = dict(rec, sku="")
            out.append(rec)
        for sku in sorted(shared):
            original = next(str(r.get("sku")) for r in records
                            if str(r.get("sku") or "").strip().lower() == sku)
            result.warnings.append(
                f"CODE {original} is used for {len(names[sku])} different items "
                f"(rows {', '.join(str(r) for r in rows[sku])}): each was imported "
                "as its own item, without the CODE.")
        return out

    def _fix_category(self, product_id: int) -> None:
        """Mark a product's Category as final (client's sheet / Masters screen)."""
        self.conn.execute("UPDATE products SET category_fixed = 1 WHERE id = ?",
                          (product_id,))

    def _find_for_import(self, master: str, rec: dict) -> tuple[int | None, str]:
        """
        (existing id or None, problem text or ""). Products are found by SKU
        first, then by name; a name that already belongs to a product with a
        DIFFERENT SKU is a problem, not a match.
        """
        mdef = self.definition(master)
        if master != "products":
            if not self.key_of(master, rec).strip("|"):
                missing = [f.label for f in mdef.fields if f.required
                           and not str(rec.get(f.key) or "").strip()]
                return None, f"{', '.join(missing) or 'Key'} is empty."
            return self._find_id(master, self.key_of(master, rec)), ""

        name = str(rec.get("name", "")).strip()
        sku = str(rec.get("sku", "")).strip()
        if sku:
            row = self.conn.execute(
                "SELECT id FROM products WHERE sku = ? COLLATE NOCASE",
                (sku,)).fetchone()
            if row is not None:
                return row["id"], ""
        if not name:
            return None, "Product name is empty."
        row = self.conn.execute("SELECT id, sku FROM products WHERE name_key = ?",
                                (name_key(name),)).fetchone()
        if row is None:
            return None, ""
        if sku and row["sku"] and row["sku"].lower() != sku.lower():
            return None, (f"“{name}” already exists with SKU {row['sku']}, "
                          f"but the sheet gives SKU {sku}.")
        return row["id"], ""

    # ==================================================================
    # Audit log
    # ==================================================================
    def audit_entries(self, master: str | None = None, action: str | None = None,
                      date_from: date | None = None, date_to: date | None = None,
                      text: str = "", limit: int | None = None) -> list[dict]:
        """
        Audit entries, newest first. All filters are optional:
        master, action, a date range (inclusive) and free text searched in
        record, field, old/new value, user and source.
        """
        where, params = [], []
        if master:
            where.append("master = ?")
            params.append(master)
        if action:
            where.append("action = ?")
            params.append(action)
        if date_from:
            where.append("at >= ?")
            params.append(_iso(date_from))
        if date_to:
            where.append("at < ?")
            params.append(_iso(date.fromordinal(date_to.toordinal() + 1)))
        if text.strip():
            where.append("(record || ' ' || field || ' ' || old_value || ' ' || "
                         "new_value || ' ' || user || ' ' || source) LIKE ?")
            params.append(f"%{text.strip()}%")
        sql = "SELECT * FROM audit_log"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY at DESC, id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
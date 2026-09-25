"""
masters_repo.py - Reading and saving the masters
================================================

WHAT THIS MODULE DOES
---------------------
All reading and writing of the Product, Sales executive and Car masters
goes through `MastersRepo`. The screens never write SQL themselves.

    list_rows(master)            rows for the Masters screen
    save(master, changes)        store edits made on screen
    import_records(master, ...)  store rows read from the client's sheet
    rate_on(product_id, day)     the rates that applied on a given day
    rate_history(product_id)     every rate change of one product
    counts()                     number of active rows per master
    get_mapping / set_mapping    remember the column matches of an import

HOW RATES AND DATES WORK
------------------------
A product's selling price, cost price and labour charge are stored in
`product_rates`, one row per change, each with an `effective_from` date.

    * The rate on a given day is the row with the latest effective_from on
      or before that day.
    * If the day is before the product's first rate (e.g. the masters were
      first imported in October but September is being re-run), the first
      known rate is used. Without this, every month before the first import
      would have no rates at all.
    * The Masters screen shows the most recent row, together with its date.

IDENTIFYING THE SAME ITEM TWICE
-------------------------------
Names are compared in a standard form (`name_key`): lower case, single
spaces, all dash characters as "-". So "Seat Cover – Premium" and
"seat cover - premium" are the same product.

    Product          matched by SKU when the row has one, otherwise by name
    Sales executive  matched by name
    Car              matched by make + model

NOTHING IS DELETED
------------------
Rows are never deleted, only marked inactive (Active = No). Past invoices
still refer to old products, staff and cars, and re-running an earlier month
must still find them. An inactive row that appears again in an imported
sheet is made active again automatically.

ERRORS
------
Problems the user must fix (missing name, duplicate name, negative amount)
raise `MasterError` with a plain-language list of messages. Nothing is
saved when that happens: each save or import runs in one transaction.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from app.data.master_defs import CARS, EXECUTIVES, PRODUCTS, MasterDef

RATE_FIELDS = ("selling_price", "cost_price", "labour_charge")
_MASTERS = {m.key: m for m in (PRODUCTS, EXECUTIVES, CARS)}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def name_key(text: str) -> str:
    """Standard form of a name, used to spot the same item written twice."""
    text = str(text or "").strip().lower()
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)   # all dashes -> "-"
    return re.sub(r"\s+", " ", text)


def car_key(make: str, model: str) -> str:
    """Standard form of make + model, e.g. 'tata|nexon'."""
    return f"{name_key(make)}|{name_key(model)}"


def infer_category(hsn_sac: str) -> str:
    """
    Guess Product / Service from an HSN/SAC code when the sheet has no
    category column. In India, service codes (SAC) are 6 digits starting
    with 99; goods codes (HSN) never start with 99.
    Blank codes are treated as products; the user can correct any row on
    the Masters screen.
    """
    digits = re.sub(r"\D", "", str(hsn_sac or ""))
    return "Service" if digits.startswith("99") else "Product"


def _iso(day: date) -> str:
    return day.isoformat()


def _from_iso(text: str) -> date:
    return date.fromisoformat(text)


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
    rate_date  for products: the date the (changed) rates apply from.
               None when no rate was changed.
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


# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------
class MastersRepo:
    """Read and write the masters in an open SQLite connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def definition(master: str) -> MasterDef:
        return _MASTERS[master]

    # ==================================================================
    # Reading
    # ==================================================================
    def list_rows(self, master: str) -> list[dict]:
        """
        All rows of a master as dicts (field key -> value, plus "id"),
        active rows first, then by name. Products include their most recent
        rates and the date those apply from ("effective_from", a date).
        """
        if master == "products":
            rows = self.conn.execute("""
                SELECT p.*, r.effective_from, r.selling_price, r.cost_price,
                       r.labour_charge
                FROM products p
                LEFT JOIN product_rates r ON r.id = (
                    SELECT id FROM product_rates
                    WHERE product_id = p.id
                    ORDER BY effective_from DESC LIMIT 1)
                ORDER BY p.active DESC, p.name COLLATE NOCASE
            """).fetchall()
        elif master == "executives":
            rows = self.conn.execute(
                "SELECT * FROM executives "
                "ORDER BY active DESC, name COLLATE NOCASE").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM cars ORDER BY active DESC, "
                "make COLLATE NOCASE, model COLLATE NOCASE").fetchall()
        return [self._row_to_dict(master, r) for r in rows]

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

    def rate_history(self, product_id: int) -> list[dict]:
        """Every rate row of a product, newest first."""
        rows = self.conn.execute(
            "SELECT effective_from, selling_price, cost_price, labour_charge "
            "FROM product_rates WHERE product_id = ? "
            "ORDER BY effective_from DESC", (product_id,)).fetchall()
        return [{"effective_from": _from_iso(r["effective_from"]),
                 **{k: float(r[k]) for k in RATE_FIELDS}} for r in rows]

    def rate_on(self, product_id: int, day: date) -> dict | None:
        """
        The rates that applied on `day`: the latest change on or before
        that day, or the product's first rate if `day` is earlier than all
        of them. None if the product has no rates at all.
        """
        row = self.conn.execute(
            "SELECT * FROM product_rates WHERE product_id = ? "
            "AND effective_from <= ? ORDER BY effective_from DESC LIMIT 1",
            (product_id, _iso(day))).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM product_rates WHERE product_id = ? "
                "ORDER BY effective_from ASC LIMIT 1",
                (product_id,)).fetchone()
        if row is None:
            return None
        return {"effective_from": _from_iso(row["effective_from"]),
                **{k: float(row[k]) for k in RATE_FIELDS}}

    def counts(self) -> dict[str, int]:
        """Number of ACTIVE rows in each master (for the Generate screen)."""
        return {m: self.conn.execute(
                    f"SELECT COUNT(*) FROM {m} WHERE active = 1").fetchone()[0]
                for m in _MASTERS}

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
    # Saving edits from the Masters screen
    # ==================================================================
    def save(self, master: str, changes: list[RowChange]) -> None:
        """
        Store added and edited rows in one transaction. Raises MasterError
        (and saves nothing) if any row has a problem.
        """
        problems = self._validate(master, changes)
        if problems:
            raise MasterError(problems)
        try:
            with self.conn:
                for ch in changes:
                    if master == "products":
                        self._save_product(ch)
                    else:
                        self._save_simple(master, ch)
        except sqlite3.IntegrityError as exc:       # safety net
            raise MasterError([f"Could not save: {exc}"]) from exc

    def _validate(self, master: str, changes: list[RowChange]) -> list[str]:
        """Check required fields, amounts and duplicates before saving."""
        mdef = self.definition(master)
        problems: list[str] = []
        seen: dict[str, str] = {}          # key -> display name, within batch
        seen_sku: dict[str, str] = {}
        for ch in changes:
            v = ch.values
            label = self._display_name(master, v) or f"New {mdef.singular}"
            for f in mdef.fields:
                if f.required and not str(v.get(f.key, "")).strip():
                    problems.append(f"{label}: {f.label} is required.")
                if f.kind == "money" and float(v.get(f.key) or 0) < 0:
                    problems.append(f"{label}: {f.label} cannot be negative.")
                if (f.kind == "choice" and not f.open_choice
                        and v.get(f.key) not in f.choices):
                    problems.append(
                        f"{label}: {f.label} must be one of "
                        f"{', '.join(f.choices)}.")

            key = self._key(master, v)
            if not key.strip("|"):
                continue
            if key in seen:
                problems.append(f"“{label}” is entered twice.")
            seen[key] = label
            clash = self._find_id(master, key)
            if clash is not None and clash != ch.id:
                problems.append(
                    f"A {mdef.singular} called “{label}” already exists. "
                    "If it is marked inactive, tick Active on that row instead.")

            if master == "products":
                sku = str(v.get("sku", "")).strip()
                if sku:
                    if sku.lower() in seen_sku:
                        problems.append(f"SKU {sku} is used twice.")
                    seen_sku[sku.lower()] = label
                    other = self.conn.execute(
                        "SELECT id, name FROM products WHERE sku = ? "
                        "COLLATE NOCASE", (sku,)).fetchone()
                    if other is not None and other["id"] != ch.id:
                        problems.append(
                            f"SKU {sku} already belongs to “{other['name']}”.")
        return problems

    def _save_product(self, ch: RowChange) -> None:
        v = ch.values
        cols = dict(sku=str(v.get("sku", "")).strip(),
                    name=str(v["name"]).strip(),
                    name_key=name_key(v["name"]),
                    hsn_sac=str(v.get("hsn_sac", "")).strip(),
                    category=v.get("category") or "Product",
                    has_labour=int(bool(v.get("has_labour"))),
                    active=int(bool(v.get("active", True))))
        if ch.id is None:
            cur = self.conn.execute(
                f"INSERT INTO products({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
            product_id = cur.lastrowid
            rate_date = ch.rate_date or date.today()
        else:
            product_id = ch.id
            self.conn.execute(
                f"UPDATE products SET {', '.join(c + ' = ?' for c in cols)} "
                "WHERE id = ?", (*cols.values(), product_id))
            rate_date = ch.rate_date
        if rate_date is not None:
            self._put_rate(product_id, rate_date,
                           {k: float(v.get(k) or 0) for k in RATE_FIELDS})

    def _put_rate(self, product_id: int, day: date, rates: dict) -> None:
        """Insert a rate row, or overwrite the one already on that date."""
        self.conn.execute(
            "INSERT INTO product_rates(product_id, effective_from, "
            "selling_price, cost_price, labour_charge) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(product_id, effective_from) DO UPDATE SET "
            "selling_price = excluded.selling_price, "
            "cost_price = excluded.cost_price, "
            "labour_charge = excluded.labour_charge",
            (product_id, _iso(day), rates["selling_price"],
             rates["cost_price"], rates["labour_charge"]))

    def _save_simple(self, master: str, ch: RowChange) -> None:
        """Insert or update a Sales executive or Car row."""
        cols = self._simple_columns(master, ch.values)
        if ch.id is None:
            self.conn.execute(
                f"INSERT INTO {master}({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
        else:
            self.conn.execute(
                f"UPDATE {master} SET {', '.join(c + ' = ?' for c in cols)} "
                "WHERE id = ?", (*cols.values(), ch.id))

    @staticmethod
    def _simple_columns(master: str, v: dict) -> dict:
        """Database columns (including the matching key) for exec / car rows."""
        if master == "executives":
            return dict(name=str(v["name"]).strip(),
                        name_key=name_key(v["name"]),
                        phone=str(v.get("phone", "")).strip(),
                        city=str(v.get("city", "")).strip(),
                        active=int(bool(v.get("active", True))))
        return dict(make=str(v.get("make", "")).strip(),
                    model=str(v["model"]).strip(),
                    car_key=car_key(v.get("make", ""), v["model"]),
                    segment=str(v.get("segment", "")).strip(),
                    active=int(bool(v.get("active", True))))

    # ------------------------------------------------------------------
    @staticmethod
    def _display_name(master: str, v: dict) -> str:
        if master == "cars":
            return " ".join(p for p in (str(v.get("make", "")).strip(),
                                        str(v.get("model", "")).strip()) if p)
        return str(v.get("name", "")).strip()

    @staticmethod
    def _key(master: str, v: dict) -> str:
        if master == "cars":
            return car_key(v.get("make", ""), v.get("model", ""))
        return name_key(v.get("name", ""))

    def _find_id(self, master: str, key: str) -> int | None:
        """Database id of the row with this matching key, or None."""
        column = "car_key" if master == "cars" else "name_key"
        row = self.conn.execute(
            f"SELECT id FROM {master} WHERE {column} = ?", (key,)).fetchone()
        return row["id"] if row else None

    # ==================================================================
    # Importing rows read from the client's sheet
    # ==================================================================
    def import_records(self, master: str, records: list[dict],
                       effective_from: date | None = None) -> ImportResult:
        """
        Add new rows and update existing ones from an imported sheet.

        records         dicts produced by excel_io.convert_rows: only the
                        fields the user matched to a column are present,
                        plus "_row" (the row number in the sheet).
        effective_from  products only: the date new or changed rates apply
                        from.

        Fields that were not matched to any column are left as they are for
        existing rows, and take their default for new rows. Everything is
        done in one transaction.
        """
        result = ImportResult()
        touched: dict[int, str] = {}      # id -> outcome, so repeats count once
        first_row: dict[str, int] = {}    # matching key -> first sheet row
        with self.conn:
            for rec in records:
                row_no = rec.get("_row", "?")
                if master == "products":
                    outcome, key = self._import_product(
                        rec, effective_from or date.today(), result, row_no)
                else:
                    outcome, key = self._import_simple(master, rec, result,
                                                       row_no)
                if outcome is None:
                    continue
                pid, what = outcome
                if key in first_row:
                    result.warnings.append(
                        f"Row {row_no} repeats row {first_row[key]} "
                        f"(“{self._display_name(master, rec)}”); "
                        "the later row was used.")
                else:
                    first_row[key] = row_no
                # "added" beats "updated" beats "unchanged" for repeated rows
                rank = {"added": 3, "updated": 2, "unchanged": 1}
                if rank[what] > rank.get(touched.get(pid, ""), 0):
                    touched[pid] = what
        for what in touched.values():
            setattr(result, what, getattr(result, what) + 1)
        return result

    def _import_product(self, rec: dict, day: date, result: ImportResult,
                        row_no) -> tuple[tuple[int, str] | None, str]:
        name = str(rec.get("name", "")).strip()
        if not name:
            result.skipped.append(f"Row {row_no}: product name is empty.")
            return None, ""
        sku = str(rec.get("sku", "")).strip()
        key = name_key(name)

        # Find the existing product: by SKU first, then by name.
        existing = None
        if sku:
            existing = self.conn.execute(
                "SELECT * FROM products WHERE sku = ? COLLATE NOCASE",
                (sku,)).fetchone()
        if existing is None:
            existing = self.conn.execute(
                "SELECT * FROM products WHERE name_key = ?", (key,)).fetchone()
            if existing is not None and sku and existing["sku"] \
                    and existing["sku"].lower() != sku.lower():
                result.skipped.append(
                    f"Row {row_no}: “{name}” already exists with SKU "
                    f"{existing['sku']}, but the sheet gives SKU {sku}.")
                return None, ""

        if any(float(rec.get(k) or 0) < 0 for k in RATE_FIELDS):
            result.skipped.append(f"Row {row_no}: “{name}” has a negative amount.")
            return None, ""

        if existing is None:
            # ---- new product -------------------------------------------
            hsn = str(rec.get("hsn_sac", "")).strip()
            category = rec.get("category") or infer_category(hsn)
            labour = float(rec.get("labour_charge") or 0)
            has_labour = rec["has_labour"] if "has_labour" in rec else labour > 0
            cur = self.conn.execute(
                "INSERT INTO products(sku, name, name_key, hsn_sac, category, "
                "has_labour, active) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (sku, name, key, hsn, category, int(bool(has_labour))))
            self._put_rate(cur.lastrowid, day,
                           {k: float(rec.get(k) or 0) for k in RATE_FIELDS})
            return (cur.lastrowid, "added"), key

        # ---- existing product ------------------------------------------
        pid = existing["id"]
        updates = {}
        for col in ("sku", "hsn_sac", "category"):
            if col in rec and rec[col] not in (None, "") \
                    and str(rec[col]).strip() != existing[col]:
                updates[col] = str(rec[col]).strip()
        if name != existing["name"]:
            updates["name"], updates["name_key"] = name, key
        if "has_labour" in rec and int(bool(rec["has_labour"])) != existing["has_labour"]:
            updates["has_labour"] = int(bool(rec["has_labour"]))
        if not existing["active"]:
            updates["active"] = 1          # back in the client's sheet
        if "sku" in updates:
            # The SKU must not already belong to a different product.
            other = self.conn.execute(
                "SELECT name FROM products WHERE sku = ? COLLATE NOCASE "
                "AND id <> ?", (updates["sku"], pid)).fetchone()
            if other is not None:
                result.skipped.append(
                    f"Row {row_no}: SKU {updates['sku']} already belongs to "
                    f"“{other['name']}”.")
                return None, ""
        if updates:
            self.conn.execute(
                f"UPDATE products SET {', '.join(c + ' = ?' for c in updates)} "
                "WHERE id = ?", (*updates.values(), pid))

        latest = self.conn.execute(
            "SELECT * FROM product_rates WHERE product_id = ? "
            "ORDER BY effective_from DESC LIMIT 1", (pid,)).fetchone()
        new_rates = {k: float(rec[k]) if k in rec and rec[k] is not None
                     else float(latest[k] if latest else 0)
                     for k in RATE_FIELDS}
        rate_changed = latest is None or any(
            abs(new_rates[k] - float(latest[k])) > 0.004 for k in RATE_FIELDS)
        if rate_changed:
            self._put_rate(pid, day, new_rates)
            result.rates_changed += 1
        return (pid, "updated" if (updates or rate_changed) else "unchanged"), key

    def _import_simple(self, master: str, rec: dict, result: ImportResult,
                       row_no) -> tuple[tuple[int, str] | None, str]:
        mdef = self.definition(master)
        required = [f for f in mdef.fields if f.required]
        missing = [f.label for f in required if not str(rec.get(f.key, "")).strip()]
        if missing:
            result.skipped.append(
                f"Row {row_no}: {', '.join(missing)} is empty.")
            return None, ""
        key = self._key(master, rec)
        pid = self._find_id(master, key)
        if pid is None:
            values = {f.key: rec.get(f.key, f.default) for f in mdef.fields}
            if "active" not in rec:
                values["active"] = True
            cols = self._simple_columns(master, values)
            cur = self.conn.execute(
                f"INSERT INTO {master}({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
            return (cur.lastrowid, "added"), key

        existing = self.conn.execute(
            f"SELECT * FROM {master} WHERE id = ?", (pid,)).fetchone()
        values = {f.key: existing[f.key] for f in mdef.fields}
        for f in mdef.fields:
            if f.key in rec and rec[f.key] not in (None, ""):
                values[f.key] = rec[f.key]
        if "active" not in rec:
            values["active"] = True        # back in the client's sheet
        cols = self._simple_columns(master, values)
        changed = any(str(cols[c]) != str(existing[c]) for c in cols)
        if changed:
            self.conn.execute(
                f"UPDATE {master} SET {', '.join(c + ' = ?' for c in cols)} "
                "WHERE id = ?", (*cols.values(), pid))
        return (pid, "updated" if changed else "unchanged"), key

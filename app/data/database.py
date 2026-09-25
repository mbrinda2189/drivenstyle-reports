"""
database.py - The tool's SQLite database
========================================

WHAT THIS MODULE DOES
---------------------
Opens (or creates) the SQLite database file and makes sure its tables exist
and are at the current layout ("schema version").

SQLite is a single file on disk - no server to install - which suits a
desktop tool used on one PC. The file lives in the folder given by
app/data/paths.py.

TABLES (schema version 1)
-------------------------
    products          one row per product / service
        id, sku, name, name_key, hsn_sac, category, has_labour, active
        name_key is the name in a standard form (lower case, single
        spaces) and is unique, so "Seat Cover" and "seat  cover" cannot be
        entered twice.

    product_rates     the dated rate history of each product
        product_id, effective_from (YYYY-MM-DD), selling_price,
        cost_price, labour_charge
        One row per change. The rate for a given day is the row with the
        latest effective_from on or before that day (see masters_repo.py).

    executives        sales executives: id, name, name_key, phone, city, active
    cars              cars: id, make, model, car_key, segment, active
                      car_key = make + model in standard form, unique

    import_mappings   remembers which sheet column the user matched to each
                      field last time, so the next import is pre-filled
        master, field, column_header

    meta              small key/value settings, e.g. schema_version

UPGRADING
---------
`SCHEMA_VERSION` is stored in the meta table. When a later version of the
tool needs new tables or columns, it adds a step to `_MIGRATIONS`; opening
an older database then upgrades it in place without losing data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.data.paths import database_path

SCHEMA_VERSION = 1

# Each entry upgrades the database from version (index) to (index + 1).
_MIGRATIONS: list[str] = [
    # --- 0 -> 1 : masters -------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS products (
        id          INTEGER PRIMARY KEY,
        sku         TEXT    NOT NULL DEFAULT '',
        name        TEXT    NOT NULL,
        name_key    TEXT    NOT NULL UNIQUE,
        hsn_sac     TEXT    NOT NULL DEFAULT '',
        category    TEXT    NOT NULL DEFAULT 'Product',
        has_labour  INTEGER NOT NULL DEFAULT 0,
        active      INTEGER NOT NULL DEFAULT 1
    );
    -- An SKU, when given, must be unique; empty SKUs are allowed many times.
    CREATE UNIQUE INDEX IF NOT EXISTS ux_products_sku
        ON products(sku) WHERE sku <> '';

    CREATE TABLE IF NOT EXISTS product_rates (
        id              INTEGER PRIMARY KEY,
        product_id      INTEGER NOT NULL
                        REFERENCES products(id) ON DELETE CASCADE,
        effective_from  TEXT    NOT NULL,          -- YYYY-MM-DD
        selling_price   REAL    NOT NULL DEFAULT 0,
        cost_price      REAL    NOT NULL DEFAULT 0,
        labour_charge   REAL    NOT NULL DEFAULT 0,
        UNIQUE (product_id, effective_from)
    );

    CREATE TABLE IF NOT EXISTS executives (
        id        INTEGER PRIMARY KEY,
        name      TEXT    NOT NULL,
        name_key  TEXT    NOT NULL UNIQUE,
        phone     TEXT    NOT NULL DEFAULT '',
        city      TEXT    NOT NULL DEFAULT '',
        active    INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS cars (
        id       INTEGER PRIMARY KEY,
        make     TEXT    NOT NULL DEFAULT '',
        model    TEXT    NOT NULL,
        car_key  TEXT    NOT NULL UNIQUE,
        segment  TEXT    NOT NULL DEFAULT '',
        active   INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS import_mappings (
        master         TEXT NOT NULL,
        field          TEXT NOT NULL,
        column_header  TEXT NOT NULL,
        PRIMARY KEY (master, field)
    );
    """,
]


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """
    Open the database (the default file unless `path` is given; ":memory:"
    gives a throw-away in-memory database for tests) and bring it up to the
    current schema version.

    Rows are returned as sqlite3.Row, so columns can be read by name:
    row["name"].
    """
    conn = sqlite3.connect(str(path or database_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _upgrade(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the schema version stored in the database (0 if brand new)."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if not has_meta:
        return 0
    row = conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row["value"]) if row else 0


def _upgrade(conn: sqlite3.Connection) -> None:
    """Apply any migration steps the database has not had yet."""
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"The data file was created by a newer version of the tool "
            f"(schema {current}). Please install the latest version.")
    for step in range(current, SCHEMA_VERSION):
        # Every statement uses IF NOT EXISTS, so a step that was interrupted
        # part-way (e.g. power cut) simply runs again next time.
        with conn:
            conn.executescript(_MIGRATIONS[step])
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) "
                "VALUES('schema_version', ?)", (str(step + 1),))

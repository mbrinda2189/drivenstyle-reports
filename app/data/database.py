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

TABLES (schema version 5)
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

        incentive_id links the product to its Incentive group (may be
        empty; set to empty automatically if that incentive row is deleted)

    executives        sales executives: id, name, phone, phone_key, branch,
                      active. phone_key is the contact number as digits only
                      (last 10 digits), unique when filled in.
    cars              cars: id, make, model, car_key, segment, active
                      car_key = make + model in standard form, unique

    incentives        incentive groups: id, name, name_key (unique), active
    incentive_rates   dated history of each group's incentive amount and
                      bill value (same rules as product_rates)

    audit_log         one row per change made to any master: when, which
                      Windows user, master, record, action (Added / Edited /
                      Activated / Deactivated / Deleted), field, old value,
                      new value, and source (screen or imported file name).
                      Database triggers refuse any change to or deletion of
                      an audit row, so the log cannot be altered.

    Scanned invoices (step 3, see invoices_repo.py):
    invoices          one row per invoice read, with everything printed on
                      it (month = YYYY-MM it was scanned for)
    invoice_lines     its item lines, with the per-line split of discount
                      and GST (worked out at scan time for PDFs; taken as
                      they are from Zoho's export from v0.6.0)
    invoice_checks    arithmetic differences found on an invoice
    scan_files        every PDF in the month's folder: read / skipped /
                      error, and why
    scan_runs         when each month was last scanned, and from where
    match_aliases     fixes that apply to every invoice: "this printed item
                      name / salesperson / vehicle means this master row"
    invoice_overrides fixes for one invoice only (e.g. which of two
                      executives with the same name)
    issue_acks        totals / labour notes accepted as correct
    Fixes and acknowledgements are kept when a month is scanned again.

    Monthly inputs and reports (step 4, see inputs_repo.py):
    monthly_costs     indirect cost heads and amounts per month
    monthly_settings  per-month settings, e.g. the high-profit threshold
    report_runs       every workbook generated: month, file, when, by whom,
                      invoices, sales and gross profit, and the payments
                      export used (so History can regenerate it)

    import_mappings   remembers which sheet column the user matched to each
                      field last time, so the next import is pre-filled
        master, field, column_header

    meta              small key/value settings, e.g. schema_version

UPGRADING
---------
`SCHEMA_VERSION` is stored in the meta table. When a later version of the
tool needs new tables or columns, it adds a step to `_MIGRATIONS`; opening
an older database then upgrades it in place without losing data.

    step 1 (v0.2.0)  masters: products, product_rates, executives, cars
    step 2 (v0.3.0)  executives: "city" becomes "branch", unique by contact
                     number instead of name; incentives + incentive_rates;
                     products.incentive_id; audit_log (read-only)
    step 3 (v0.4.0)  scanned invoices and Scan review fixes
    step 4 (v0.5.0)  monthly inputs and generated-report history
    step 5 (v0.6.0)  invoices read from Zoho's invoice export: invoices get
                     source (pdf / export), status (Closed / Overdue ...)
                     and branch (CF.Branch); invoice lines get item_type
                     (Zoho goods / service)

A step is either a block of SQL or a Python function taking the connection
(used when values must be worked out in Python, e.g. contact-number keys).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typing import Callable, Union

from app.data.paths import database_path

SCHEMA_VERSION = 5


def _step_2(conn: sqlite3.Connection) -> None:
    """
    v0.2.0 -> v0.3.0

    1. Sales executives: rebuild the table (SQLite cannot drop a UNIQUE
       rule in place) so that "city" becomes "branch" and the contact
       number, not the name, must be unique. Existing rows are copied.
       If two existing executives share a contact number, only the first
       keeps it as its key; the other must be corrected on screen (saving
       it will ask for a unique contact number).
    2. Incentive master tables and the product -> incentive link.
    3. Audit log, protected by triggers against UPDATE and DELETE.
    4. Remembered import column matches: executives "city" -> "branch".
    """
    # Imported here: masters_repo imports this module.
    from app.data.masters_repo import phone_key

    conn.executescript("""
        CREATE TABLE executives_v2 (
            id         INTEGER PRIMARY KEY,
            name       TEXT    NOT NULL,
            phone      TEXT    NOT NULL DEFAULT '',
            phone_key  TEXT    NOT NULL DEFAULT '',
            branch     TEXT    NOT NULL DEFAULT '',
            active     INTEGER NOT NULL DEFAULT 1
        );
        INSERT INTO executives_v2(id, name, phone, branch, active)
            SELECT id, name, phone, city, active FROM executives;
        DROP TABLE executives;
        ALTER TABLE executives_v2 RENAME TO executives;
    """)
    used: set[str] = set()
    for row in conn.execute("SELECT id, phone FROM executives ORDER BY id").fetchall():
        key = phone_key(row["phone"])
        if key and key not in used:
            used.add(key)
            conn.execute("UPDATE executives SET phone_key = ? WHERE id = ?",
                         (key, row["id"]))
    conn.executescript("""
        CREATE UNIQUE INDEX ux_executives_phone
            ON executives(phone_key) WHERE phone_key <> '';

        CREATE TABLE IF NOT EXISTS incentives (
            id        INTEGER PRIMARY KEY,
            name      TEXT    NOT NULL,
            name_key  TEXT    NOT NULL UNIQUE,
            active    INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS incentive_rates (
            id                INTEGER PRIMARY KEY,
            incentive_id      INTEGER NOT NULL
                              REFERENCES incentives(id) ON DELETE CASCADE,
            effective_from    TEXT    NOT NULL,          -- YYYY-MM-DD
            incentive_amount  REAL    NOT NULL DEFAULT 0,
            bill_value        REAL    NOT NULL DEFAULT 0,
            UNIQUE (incentive_id, effective_from)
        );

        ALTER TABLE products ADD COLUMN incentive_id INTEGER
            REFERENCES incentives(id) ON DELETE SET NULL;

        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY,
            at         TEXT NOT NULL,        -- YYYY-MM-DDTHH:MM:SS, local time
            user       TEXT NOT NULL DEFAULT '',
            master     TEXT NOT NULL,        -- products / executives / ...
            record_id  INTEGER,
            record     TEXT NOT NULL DEFAULT '',
            action     TEXT NOT NULL,        -- Added / Edited / Deleted / ...
            field      TEXT NOT NULL DEFAULT '',
            old_value  TEXT NOT NULL DEFAULT '',
            new_value  TEXT NOT NULL DEFAULT '',
            source     TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_log(at);
        CREATE TRIGGER IF NOT EXISTS audit_log_no_update
            BEFORE UPDATE ON audit_log
            BEGIN SELECT RAISE(ABORT, 'The audit log cannot be changed.'); END;
        CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
            BEFORE DELETE ON audit_log
            BEGIN SELECT RAISE(ABORT, 'The audit log cannot be changed.'); END;

        UPDATE import_mappings SET field = 'branch'
            WHERE master = 'executives' AND field = 'city';
    """)


# Each entry upgrades the database from version (index) to (index + 1).
_MIGRATIONS: list[Union[str, Callable[[sqlite3.Connection], None]]] = [
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

    -- (replaced in step 2: see _step_2)
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
    # --- 1 -> 2 : branch, unique contact no, incentives, audit log --------
    _step_2,
    # --- 2 -> 3 : scanned invoices and Scan review fixes -------------------
    """
    CREATE TABLE IF NOT EXISTS invoices (
        id               INTEGER PRIMARY KEY,
        month            TEXT NOT NULL,                  -- YYYY-MM
        file_name        TEXT NOT NULL,
        invoice_no       TEXT NOT NULL UNIQUE,
        invoice_date     TEXT NOT NULL,                  -- YYYY-MM-DD
        seller           TEXT NOT NULL DEFAULT '',
        gstin            TEXT NOT NULL DEFAULT '',
        customer         TEXT NOT NULL DEFAULT '',
        customer_type    TEXT NOT NULL DEFAULT '',
        salesperson      TEXT NOT NULL DEFAULT '',       -- as printed
        vehicle          TEXT NOT NULL DEFAULT '',       -- as printed
        vin              TEXT NOT NULL DEFAULT '',
        po_no            TEXT NOT NULL DEFAULT '',
        terms            TEXT NOT NULL DEFAULT '',
        place_of_supply  TEXT NOT NULL DEFAULT '',
        payment_mode     TEXT NOT NULL DEFAULT '',       -- if printed
        sub_total        REAL NOT NULL DEFAULT 0,        -- tax inclusive
        discount         REAL NOT NULL DEFAULT 0,
        discount_base    REAL NOT NULL DEFAULT 0,
        taxes_json       TEXT NOT NULL DEFAULT '{}',     -- {"CGST 9%": 633.04, ...}
        tax_total        REAL NOT NULL DEFAULT 0,
        tax_rate         REAL NOT NULL DEFAULT 0,        -- 18, 0 = no GST, -1 = mixed
        rounding         REAL NOT NULL DEFAULT 0,
        total            REAL NOT NULL DEFAULT 0,
        payment_made     REAL NOT NULL DEFAULT 0,
        balance_due      REAL NOT NULL DEFAULT 0,
        scanned_at       TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_invoices_month ON invoices(month);

    CREATE TABLE IF NOT EXISTS invoice_lines (
        id                INTEGER PRIMARY KEY,
        invoice_id        INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        line_no           INTEGER NOT NULL,
        description       TEXT NOT NULL,
        sku               TEXT NOT NULL DEFAULT '',
        hsn_sac           TEXT NOT NULL DEFAULT '',
        qty               REAL NOT NULL DEFAULT 0,
        unit              TEXT NOT NULL DEFAULT '',
        rate              REAL NOT NULL DEFAULT 0,
        amount            REAL NOT NULL DEFAULT 0,       -- tax inclusive
        is_labour_marker  INTEGER NOT NULL DEFAULT 0,
        before_tax        REAL NOT NULL DEFAULT 0,
        discount_share    REAL NOT NULL DEFAULT 0,
        net_value         REAL NOT NULL DEFAULT 0,       -- after discount, before GST
        gst               REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS ix_lines_invoice ON invoice_lines(invoice_id);

    CREATE TABLE IF NOT EXISTS invoice_checks (
        id          INTEGER PRIMARY KEY,
        invoice_id  INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        message     TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scan_files (
        month       TEXT NOT NULL,
        file_name   TEXT NOT NULL,
        status      TEXT NOT NULL,                       -- read / skipped / error
        reason      TEXT NOT NULL DEFAULT '',
        invoice_no  TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (month, file_name)
    );

    CREATE TABLE IF NOT EXISTS scan_runs (
        month       TEXT PRIMARY KEY,
        folder      TEXT NOT NULL,
        scanned_at  TEXT NOT NULL,
        files       INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS match_aliases (
        kind        TEXT NOT NULL,                       -- product / executive / car
        raw_key     TEXT NOT NULL,                       -- printed text, standard form
        target_id   INTEGER NOT NULL,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (kind, raw_key)
    );

    CREATE TABLE IF NOT EXISTS invoice_overrides (
        invoice_no  TEXT NOT NULL,
        kind        TEXT NOT NULL,                       -- executive / car
        target_id   INTEGER NOT NULL,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (invoice_no, kind)
    );

    CREATE TABLE IF NOT EXISTS issue_acks (
        invoice_no  TEXT NOT NULL,
        kind        TEXT NOT NULL,                       -- totals / labour
        note        TEXT NOT NULL DEFAULT '',
        at          TEXT NOT NULL,
        PRIMARY KEY (invoice_no, kind)
    );
    """,
    # --- 3 -> 4 : monthly inputs and generated reports ---------------------
    """
    CREATE TABLE IF NOT EXISTS monthly_costs (
        month     TEXT    NOT NULL,                      -- YYYY-MM
        head      TEXT    NOT NULL,
        amount    REAL    NOT NULL DEFAULT 0,
        position  INTEGER NOT NULL DEFAULT 0,            -- order on screen
        PRIMARY KEY (month, head)
    );
    CREATE TABLE IF NOT EXISTS monthly_settings (
        month  TEXT NOT NULL,
        key    TEXT NOT NULL,                            -- e.g. high_profit_pct
        value  TEXT NOT NULL,
        PRIMARY KEY (month, key)
    );
    CREATE TABLE IF NOT EXISTS report_runs (
        id             INTEGER PRIMARY KEY,
        month          TEXT NOT NULL,
        file_path      TEXT NOT NULL,
        generated_at   TEXT NOT NULL,
        user           TEXT NOT NULL DEFAULT '',
        invoices       INTEGER NOT NULL DEFAULT 0,       -- included in reports
        left_out       INTEGER NOT NULL DEFAULT 0,
        sales          REAL NOT NULL DEFAULT 0,
        gross_profit   REAL NOT NULL DEFAULT 0,
        payments_path  TEXT NOT NULL DEFAULT '',
        reports_json   TEXT NOT NULL DEFAULT '[]'        -- reports included
    );
    CREATE INDEX IF NOT EXISTS ix_report_runs_month ON report_runs(month);
    """,
    # --- 4 -> 5 : invoices from Zoho's invoice export -----------------------
    """
    ALTER TABLE invoices ADD COLUMN source TEXT NOT NULL DEFAULT 'pdf';
    ALTER TABLE invoices ADD COLUMN status TEXT NOT NULL DEFAULT '';
    ALTER TABLE invoices ADD COLUMN branch TEXT NOT NULL DEFAULT '';
    ALTER TABLE invoice_lines ADD COLUMN item_type TEXT NOT NULL DEFAULT '';
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
    if current < SCHEMA_VERSION and current > 0:
        _backup(conn, current)
    for step in range(current, SCHEMA_VERSION):
        with conn:
            migration = _MIGRATIONS[step]
            if callable(migration):
                migration(conn)
            else:
                conn.executescript(migration)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) "
                "VALUES('schema_version', ?)", (str(step + 1),))


def _backup(conn: sqlite3.Connection, version: int) -> None:
    """
    Before upgrading an existing database, save a copy next to it
    (e.g. drivenstyle.schema1.bak.db), so the data can be recovered if an
    upgrade ever goes wrong. Skipped for in-memory databases.
    """
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row["file"] if row else ""
    if not path:
        return
    target = Path(path).with_suffix(f".schema{version}.bak.db")
    if target.exists():
        return
    backup = sqlite3.connect(str(target))
    with backup:
        conn.backup(backup)
    backup.close()
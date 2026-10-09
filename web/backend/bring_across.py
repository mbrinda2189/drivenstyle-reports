"""
bring_across.py - Copy the desktop tool's data into the web tool, once (v0.24.0)
================================================================================

WHAT THIS DOES
--------------
The web tool starts with an empty database. This command copies the
DESKTOP tool's database into it, so the web tool begins with exactly what
the desktop tool has today (Brinda, 09-10-2026: the desktop database is the
truth, not the payout app's Google Sheet):

    masters with their dated rate history, saved matches and Scan review
    fixes, the months already read, monthly inputs, History, the audit log

    python -m web.backend.bring_across
    python -m web.backend.bring_across --from "D:\\copy\\drivenstyle.db"

    --from PATH   the database to copy (default: the desktop tool's own,
                  %LOCALAPPDATA%\\Drive N Style Reports\\drivenstyle.db)
    --replace     allow it although the web tool already has masters

WHAT IS SAFE ABOUT IT
    * The desktop database is only READ. It is never changed.
    * The web tool's present database is first kept as
      drivenstyle.before-bring-across-<date-time>.db in the same folder.
    * The web tool's USERS are kept: the people who can sign in are the
      same after the copy as before it.
    * If the web tool already has masters it refuses, unless --replace is
      given - so a second run cannot wipe work done on the web by mistake.

Stop the server before running it, and start it again afterwards.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from app.data.database import connect
from app.data.paths import database_path
from web.backend import config

MASTER_TABLES = ("products", "executives", "cars", "incentives", "package_items")


class BringAcrossError(Exception):
    """A plain-language reason nothing was copied."""


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def bring_across(source: Path, target: Path, replace: bool = False) -> dict:
    """
    Copy `source` (desktop database) to `target` (web database), keeping the
    web tool's users. Returns the number of rows per master and of users.
    """
    source, target = Path(source), Path(target)
    if not source.is_file():
        raise BringAcrossError(f"There is no database at {source}.")
    if source.resolve() == target.resolve():
        raise BringAcrossError("The source is the web tool's own database.")

    users: list[tuple] = []
    if target.is_file():
        conn = connect(target)
        try:
            if not replace and any(_count(conn, t) for t in MASTER_TABLES):
                raise BringAcrossError(
                    "The web tool already has masters. Nothing was copied. "
                    "Add --replace only if they may be replaced.")
            users = [tuple(r) for r in conn.execute(
                "SELECT email, name, role, active, created_at, last_login FROM users")]
        finally:
            conn.close()
        stamp = datetime.now().strftime("%d-%m-%Y_%H%M%S")
        shutil.copy2(target, target.with_name(
            f"{target.stem}.before-bring-across-{stamp}.db"))
        for extra in ("-wal", "-shm"):               # leftovers of the old file
            Path(str(target) + extra).unlink(missing_ok=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    # sqlite's own backup gives a clean, complete copy even if the desktop
    # tool happens to be open; the source is opened read-only.
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()

    conn = connect(target)                # brings an older layout up to date
    try:
        with conn:
            for row in users:
                conn.execute(
                    "INSERT INTO users(email, name, role, active, created_at, last_login) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET "
                    "name = excluded.name, role = excluded.role, active = excluded.active",
                    row)
        return {**{t: _count(conn, t) for t in MASTER_TABLES},
                "users": _count(conn, "users")}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy the desktop tool's data into the web tool.")
    parser.add_argument("--from", dest="source", default="")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    settings = config.load()
    source = Path(args.source) if args.source else database_path()
    try:
        done = bring_across(source, settings.db_path, args.replace)
    except BringAcrossError as exc:
        print(exc)
        return 1
    print(f"Copied {source}\n    to {settings.db_path}")
    for table, label in zip(MASTER_TABLES, ("Products", "Sales executives", "Cars",
                                            "Incentives", "Package items")):
        print(f"  {label:<18}{done[table]}")
    print(f"  {'Users kept':<18}{done['users']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

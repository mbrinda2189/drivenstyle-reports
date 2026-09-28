"""
test_database_upgrade.py - A v0.2.0 database is upgraded without data loss
==========================================================================
"""

import sqlite3

from app.data import database
from app.data.database import SCHEMA_VERSION, connect
from app.data.masters_repo import MastersRepo


def make_v1_database(path):
    """Create a database exactly as v0.2.0 left it (schema 1) with data."""
    conn = sqlite3.connect(path)
    conn.executescript(database._MIGRATIONS[0])
    conn.executescript("""
        INSERT INTO meta VALUES ('schema_version', '1');
        INSERT INTO executives(name, name_key, phone, city, active)
            VALUES ('Arun', 'arun', '98765 43210', 'Tuticorin', 1),
                   ('Priya', 'priya', '+91 9876543210', 'Tirunelveli', 1),
                   ('Selvam', 'selvam', '', 'Tuticorin', 0);
        INSERT INTO products(sku, name, name_key) VALUES ('M1', 'Mat', 'mat');
        INSERT INTO import_mappings VALUES ('executives', 'city', 'City');
    """)
    conn.commit()
    conn.close()


def test_upgrade_from_v020(tmp_path):
    db = tmp_path / "drivenstyle.db"
    make_v1_database(db)
    repo = MastersRepo(connect(db))

    rows = {r["name"]: r for r in repo.list_rows("executives")}
    assert rows["Arun"]["branch"] == "Tuticorin"               # city -> branch
    assert rows["Selvam"]["active"] is False
    # Priya's number is the same as Arun's: only Arun keeps it as the key,
    # so saving Priya unchanged is refused until the number is corrected.
    keys = dict(repo.conn.execute("SELECT name, phone_key FROM executives").fetchall())
    assert keys == {"Arun": "9876543210", "Priya": "", "Selvam": ""}

    assert repo.list_rows("products")[0]["incentive_group"] == ""
    assert repo.get_mapping("executives") == {"branch": "City"}
    assert (tmp_path / "drivenstyle.schema1.bak.db").exists()   # safety copy
    ver = repo.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert int(ver) == SCHEMA_VERSION
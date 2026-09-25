"""
paths.py - Where the tool keeps its data
========================================

WHAT THIS MODULE DOES
---------------------
Decides the folder that holds the tool's SQLite database (masters, rate
history and, in later versions, processed months).

    1. If the environment variable DNS_REPORTS_DATA_DIR is set, that folder
       is used. The automated tests use this so they never touch real data.
    2. Otherwise, on Windows: %LOCALAPPDATA%\\Drive N Style Reports
       e.g. C:\\Users\\<name>\\AppData\\Local\\Drive N Style Reports
    3. On any other system: ~/.drivenstyle_reports

Keeping the data outside the program folder means the .exe can be replaced
with a newer version without losing the masters. To back up the tool's data,
copy the database file shown by `database_path()`.
"""

from __future__ import annotations

import os
from pathlib import Path

DB_FILE_NAME = "drivenstyle.db"


def data_dir() -> Path:
    """Return the data folder, creating it if it does not exist yet."""
    override = os.environ.get("DNS_REPORTS_DATA_DIR")
    if override:
        folder = Path(override)
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        folder = Path(os.environ["LOCALAPPDATA"]) / "Drive N Style Reports"
    else:
        folder = Path.home() / ".drivenstyle_reports"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def database_path() -> Path:
    """Full path of the SQLite database file."""
    return data_dir() / DB_FILE_NAME

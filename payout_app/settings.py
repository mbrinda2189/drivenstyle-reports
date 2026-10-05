"""
settings.py - The payout app's small settings file on this PC
=============================================================

WHAT THIS MODULE DOES
---------------------
Remembers, on each PC, which Google Sheet holds the masters (and later the
payout register). It is one small text file, `payout_settings.json`, kept
in the same data folder as the monthly tool's database
(`%LOCALAPPDATA%\\Drive N Style Reports`, see app/data/paths.py) - never in
the project folder, so it is never committed to Git.

    load()            all settings as a dict ({} if nothing saved yet)
    get(key)          one setting ("" if not set)
    save(**values)    add / change settings, keeping the others

SETTINGS USED SO FAR
--------------------
    masters_sheet_id    the Google Sheet's id (the long code in its link)
    masters_sheet_url   its link, for showing to the user
    register_sheet_id / register_sheet_url   the same for the payout register
    invoice_folder      where the invoice PDFs are saved on this PC
    start_date          invoices dated earlier are left alone (dd-mm-yyyy)

THE INSTALLED APP: FILES THAT TRAVEL WITH IT (v0.18.0)
------------------------------------------------------
The program built for the staff PCs (scripts/build_payout_app.py) carries a
small folder, "payout_bundle", with:
    payout_defaults.json   the links of the masters sheet and the register,
                           so the staff do not have to paste them. They are
                           only DEFAULTS: whatever is saved on the PC wins.
    client_secret_*.json   the app's Google key (see google_api.py)
`bundle_dir()` says where that folder is - inside the unpacked program when
running as the built .exe, otherwise None (development: nothing bundled).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.data.paths import data_dir

FILE_NAME = "payout_settings.json"
BUNDLE_FOLDER = "payout_bundle"
DEFAULTS_FILE = "payout_defaults.json"
# Only these may come from the bundled defaults - never a folder or a date,
# which belong to one PC.
DEFAULT_KEYS = ("masters_sheet_id", "masters_sheet_url",
                "register_sheet_id", "register_sheet_url")


def bundle_dir() -> Path | None:
    """The folder of files built into the installed app (None in development)."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    folder = Path(base) / BUNDLE_FOLDER
    return folder if folder.is_dir() else None


def defaults() -> dict:
    """The sheet links built into the installed app ({} if none)."""
    folder = bundle_dir()
    if folder is None:
        return {}
    try:
        data = json.loads((folder / DEFAULTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in data.items() if k in DEFAULT_KEYS and v} \
        if isinstance(data, dict) else {}


def settings_path() -> Path:
    return data_dir() / FILE_NAME


def load() -> dict:
    """
    All settings: what is saved on this PC, on top of the installed app's
    defaults. An unreadable file counts as nothing saved.
    """
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    saved = data if isinstance(data, dict) else {}
    return {**defaults(), **{k: v for k, v in saved.items() if v not in ("", None)},
            **{k: v for k, v in saved.items() if k not in DEFAULT_KEYS}}


def get(key: str) -> str:
    return str(load().get(key, "") or "")


def save(**values) -> dict:
    """Add or change settings (others are kept). Returns all settings."""
    data = {**load(), **values}
    settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def sheet_id_from(text: str) -> str:
    """
    The sheet id from a pasted link or id:
    "https://docs.google.com/spreadsheets/d/1AbC.../edit#gid=0" -> "1AbC...".
    """
    text = (text or "").strip()
    marker = "/spreadsheets/d/"
    if marker in text:
        text = text.split(marker, 1)[1]
    return text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]

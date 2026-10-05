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
"""

from __future__ import annotations

import json
from pathlib import Path

from app.data.paths import data_dir

FILE_NAME = "payout_settings.json"


def settings_path() -> Path:
    return data_dir() / FILE_NAME


def load() -> dict:
    """All saved settings; an unreadable file counts as no settings."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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

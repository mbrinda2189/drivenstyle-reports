"""
test_packaging.py - What the installed payout app carries with it (v0.18.0)
===========================================================================

The Windows program is built on Brinda's PC (scripts/build_payout_app.py)
and checks itself there. These tests cover the parts that can be checked
anywhere: the built-in sheet links are only defaults, the Google key is
found inside the installed app, and the self-check reports what is missing.
An "installed app" is imitated by pointing sys._MEIPASS at a folder.
"""

import json
import sys

import pytest

from payout_app import google_api, settings


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A folder standing in for the unpacked program, with its bundle."""
    bundle = tmp_path / "program" / settings.BUNDLE_FOLDER
    bundle.mkdir(parents=True)
    (bundle / settings.DEFAULTS_FILE).write_text(json.dumps({
        "masters_sheet_id": "M1", "masters_sheet_url": "https://x/M1",
        "register_sheet_id": "R1", "register_sheet_url": "https://x/R1",
        "invoice_folder": "C:/someone/else"}))
    (bundle / "client_secret_abc.json").write_text("{}")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "program"), raising=False)
    return bundle


def test_nothing_is_built_in_during_development():
    assert settings.bundle_dir() is None and settings.defaults() == {}
    assert settings.load() == {}


def test_built_in_links_are_defaults_that_the_pc_can_override(installed):
    assert settings.get("masters_sheet_id") == "M1"
    assert settings.get("register_sheet_url") == "https://x/R1"
    assert settings.get("invoice_folder") == ""          # a folder is never built in
    settings.save(invoice_folder="D:/Invoices", start_date="")
    assert settings.get("masters_sheet_id") == "M1"      # still the default
    settings.save(register_sheet_id="R2", register_sheet_url="https://x/R2")
    loaded = settings.load()
    assert (loaded["register_sheet_id"], loaded["masters_sheet_id"]) == ("R2", "M1")
    assert loaded["invoice_folder"] == "D:/Invoices" and loaded["start_date"] == ""
    settings.save(register_sheet_id="")                  # cleared: the default again
    assert settings.get("register_sheet_id") == "R1"


def test_google_key_is_found_inside_the_installed_app(installed, tmp_path, monkeypatch):
    assert google_api.find_client_secret().name == "client_secret_abc.json"
    own = tmp_path / "data" / "client_secret_own.json"   # the PC's own copy wins
    own.write_text("{}")
    assert google_api.find_client_secret().name == "client_secret_own.json"


def test_damaged_defaults_file_is_ignored(installed):
    (installed / settings.DEFAULTS_FILE).write_text("not json")
    assert settings.defaults() == {} and settings.get("masters_sheet_id") == ""


def test_self_check_names_what_is_missing():
    # In development nothing is built in, so the sheet links are reported
    # missing while the window, the pictures and the PDF reader are fine.
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from payout_app.__main__ import self_check
    lines = {what.split(":")[0]: ok for ok, what in self_check()}
    assert lines["The app window opens"] and lines["Theme pictures"]
    assert lines["PDF reader"]
    assert lines["Sheet links"] is False
    assert set(lines) >= {"Google key file", "Google libraries (Sheets, Drive, sign-in, upload)"}
    assert app is not None

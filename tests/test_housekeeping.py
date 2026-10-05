"""
test_housekeeping.py - Clearing the register and removing duplicate sheets
==========================================================================

Payout app, v0.17.1 - the owner's clean start before go-live. Run against
the stand-ins of tests/fakes.py. What is checked:
* clearing needs the word CLEAR and the register's owner, makes a backup
  copy FIRST, empties Payouts / Invoices / Log, keeps Matches and Setup,
  and leaves one log line saying who, when and where the backup is;
* after clearing, every invoice is new again (and the start date keeps
  old ones out);
* duplicates are listed with the ones in use marked; only the others can
  go to the trash, and the move is logged.
"""

from datetime import date, datetime

import pytest

from app.data.inputs_repo import InputsRepo
from payout_app import engine, masters_sheet as ms, register as rg, service, settings
from payout_app.google_api import GoogleError
from tests.fakes import FakeDrive, FakeGoogle
from tests.test_payout_engine import build_masters, september

NOW = lambda: datetime(2026, 10, 6, 9, 15)


def filled(repo, drive):
    build_masters(repo)
    google = FakeGoogle(ms.to_tabs(repo, InputsRepo(repo)))
    session = service.Session(google, "automation@example.com", drive)
    settings.save(masters_sheet_id="M", register_sheet_id="R")
    outcome = engine.calculate(ms.load_tabs(google.store["M"]).masters, september())
    todo = rg.plan(google.store["R"]["Payouts"], google.store["R"]["Invoices"], outcome,
                   "x", datetime(2026, 10, 5, 18, 0))
    for tab, rows in ((rg.PAYOUTS, todo.payout_appends), (rg.INVOICES, todo.invoice_appends),
                      (rg.LOG, todo.log)):
        google.append_rows("R", tab, rows)
    service.save_match(session, "Car", "NIOS", "Tata Punch EV", now=NOW)
    service.create_proofs_folder(session, now=NOW)
    return session, google


def test_clear_register_backs_up_first_and_keeps_matches(repo):
    drive = FakeDrive()
    session, google = filled(repo, drive)
    store = google.store["R"]
    assert len(store[rg.PAYOUTS]) == 6 and len(store[rg.INVOICES]) == 4
    with pytest.raises(GoogleError, match="type CLEAR"):
        service.clear_register(session, "clear", now=NOW)
    assert len(store[rg.PAYOUTS]) == 6 and drive.copies == []

    backup, removed = service.clear_register(session, "CLEAR", now=NOW)
    assert drive.copies == [("R", "Drive N Style Payout Register - backup 06-10-2026 09.15")]
    assert removed == {"Payouts": 5, "Invoices": 3, "Log": 5}
    assert store[rg.PAYOUTS] == [rg.PAYOUT_HEADERS]
    assert store[rg.INVOICES] == [rg.INVOICE_HEADERS]
    assert store[rg.MATCHES][1][:3] == ["Car", "NIOS", "Tata Punch EV"]
    assert store[rg.SETUP][1] == ["Proofs folder", "F1"]
    (entry,) = store[rg.LOG][1:]
    assert entry[1:4] == ["automation@example.com", "Register cleared",
                          "5 payout line(s), 3 invoice(s), 5 log entries"]
    assert entry[5] == f"Backup: {backup}" and "COPY1" in backup


def test_only_the_owner_can_clear(repo):
    session, google = filled(repo, FakeDrive(owner=False))
    with pytest.raises(GoogleError, match="Only the owner"):
        service.clear_register(session, "CLEAR", now=NOW)
    assert len(google.store["R"][rg.PAYOUTS]) == 6
    assert session.drive.copies == []


def test_after_clearing_invoices_are_new_and_the_start_date_keeps_old_ones_out(repo):
    session, google = filled(repo, FakeDrive())
    service.clear_register(session, "CLEAR", now=NOW)
    outcome = engine.calculate(ms.load_tabs(google.store["M"]).masters, september())
    store = google.store["R"]
    fresh = rg.plan(store[rg.PAYOUTS], store[rg.INVOICES], outcome, "x", NOW())
    assert fresh.tally["posted"] == 3 and fresh.tally["already posted"] == 0
    kept_out = rg.plan(store[rg.PAYOUTS], store[rg.INVOICES], outcome, "x", NOW(),
                       start=date(2026, 10, 1))
    assert kept_out.tally["before start date"] == 3 and not kept_out.has_writes


SHEET, FOLDER = "application/vnd.google-apps.spreadsheet", "application/vnd.google-apps.folder"


def drive_with_extras():
    return FakeDrive(files=[
        dict(id="OLD1", name="Drive N Style Masters", mimeType=SHEET,
             createdTime="2026-10-05T04:10:00Z", webViewLink="https://x/OLD1"),
        dict(id="M", name="Drive N Style Masters", mimeType=SHEET,
             createdTime="2026-10-05T05:00:00Z", webViewLink="https://x/M"),
        dict(id="R", name="Drive N Style Payout Register", mimeType=SHEET,
             createdTime="2026-10-05T06:00:00Z", webViewLink="https://x/R"),
        dict(id="OLD2", name="Drive N Style Payout Register", mimeType=SHEET,
             createdTime="2026-10-05T06:30:00Z", webViewLink="https://x/OLD2"),
        dict(id="F1", name="Drive N Style Payout Proofs", mimeType=FOLDER,
             createdTime="2026-10-05T07:00:00Z", webViewLink="https://x/F1"),
        dict(id="Z", name="Something else", mimeType=SHEET, createdTime="", webViewLink=""),
    ])


def test_duplicates_are_listed_with_those_in_use_marked(repo):
    session, google = filled(repo, drive_with_extras())
    found = service.find_duplicates(session)
    assert [(f["id"], f["kind"], f["in_use"]) for f in found] == [
        ("OLD1", "Sheet", False), ("M", "Sheet", True), ("R", "Sheet", True),
        ("OLD2", "Sheet", False), ("F1", "Folder", True)]
    assert len(found[0]["created"]) == 16 and found[0]["created"][2] == "-"


def test_only_duplicates_not_in_use_go_to_the_trash(repo):
    session, google = filled(repo, drive_with_extras())
    found = {f["id"]: f for f in service.find_duplicates(session)}
    with pytest.raises(GoogleError, match="Tick the files"):
        service.trash_duplicates(session, [])
    with pytest.raises(GoogleError, match="in use"):
        service.trash_duplicates(session, [found["OLD1"], found["R"]], now=NOW)
    assert session.drive.trashed == []
    assert service.trash_duplicates(session, [found["OLD1"], found["OLD2"]], now=NOW) == 2
    assert session.drive.trashed == ["OLD1", "OLD2"]
    assert [f["id"] for f in service.find_duplicates(session)] == ["M", "R", "F1"]
    log = google.store["R"][rg.LOG][-2:]
    assert [e[2:4] for e in log] == [
        ["Duplicate moved to trash", "Sheet: Drive N Style Masters"],
        ["Duplicate moved to trash", "Sheet: Drive N Style Payout Register"]]
    with pytest.raises(GoogleError, match="no longer in the list"):
        service.trash_duplicates(session, [found["OLD1"]], now=NOW)

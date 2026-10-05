"""
test_payout_ui.py - The payout app's screens (Scan, Review, Set-up)
==================================================================

Payout app, v0.16.0. The screens are run without a display (Qt's
"offscreen" platform) against a stand-in for Google that keeps the two
sheets as row lists, and with invoices built in code instead of PDFs. So
the whole path is exercised - button, background thread, service, register
rows, screen - with no internet and no client data.

Skipped when PySide6 is not installed (the calculation tests still run).
Waiting is done with app.processEvents() in a loop, never QTest.qWait,
which starves the background thread (CLAUDE.md).
"""

import os
import time
from datetime import date

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.data.inputs_repo import InputsRepo  # noqa: E402
from app.theme import build_stylesheet  # noqa: E402
from payout_app import engine, masters_sheet as ms, register as rg, service, settings  # noqa: E402
from payout_app.ui.main_window import PAGE_REVIEW, PAGE_SETUP, MainWindow  # noqa: E402
from tests.test_invoices import inv_0753, inv_226  # noqa: E402
from tests.test_payout_engine import build_masters, with_vehicle  # noqa: E402


class FakeGoogle:
    """The masters sheet "M" and the register "R" as row lists."""

    def __init__(self, masters_tabs):
        self.store = {"M": masters_tabs, "R": rg.new_register_tabs()}
        self.titles = {"M": "Drive N Style Masters", "R": "Drive N Style Payout Register"}

    def read_tabs(self, sheet_id):
        return {t: [list(r) for r in rows] for t, rows in self.store[sheet_id].items()}

    def tab_names(self, sheet_id):
        return list(self.store[sheet_id])

    def title(self, sheet_id):
        return self.titles[sheet_id]

    def append_rows(self, sheet_id, tab, rows):
        self.store[sheet_id][tab] += [list(r) for r in rows]

    def update_rows(self, sheet_id, updates):
        for tab, n, cells in updates:
            row = self.store[sheet_id][tab][n - 1]
            row += [""] * (len(cells) - len(row))
            row[:len(cells)] = cells


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_stylesheet())
    return app


@pytest.fixture
def world(qapp, repo, tmp_path, monkeypatch):
    """A window on a fake Google, with two September invoices 'in the folder'."""
    build_masters(repo)
    google = FakeGoogle(ms.to_tabs(repo, InputsRepo(repo)))
    folder = tmp_path / "invoices"
    folder.mkdir()
    settings.save(masters_sheet_id="M", register_sheet_id="R",
                  invoice_folder=str(folder), start_date="")
    invoices = [with_vehicle(inv_0753(), "I20", "Edhayan - Ooty"),
                with_vehicle(inv_226(), "NIOS")]                  # car not known
    monkeypatch.setattr(engine, "read_files",
                        lambda paths, progress=None, cache=None:
                        [(i.file_name, i, "") for i in invoices])
    monkeypatch.setattr(service, "monthly_tool_matches", lambda path=None: [])
    window = MainWindow(service.Session(google, "staff@example.com"))
    window.show()
    yield window, google, invoices
    window.close()


def wait(qapp, window, seconds=10.0):
    """Let the background task finish (see module notes)."""
    end = time.time() + seconds
    qapp.processEvents()
    while window.busy and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    for _ in range(5):
        qapp.processEvents()
    assert not window.busy, "the background task did not finish"


def test_scan_posts_and_shows_the_result(qapp, world):
    window, google, _ = world
    page = window.scan_page
    page.scan()
    wait(qapp, window)
    assert page.tiles["posted"].value_label.text() == "1"
    assert page.tiles["in review"].value_label.text() == "1"
    assert page.table.rowCount() == 2
    assert page.table.item(0, 0).text() == "DNS26-GST-0753-LAB"
    assert page.table.item(0, 3).text() == "150.00"
    assert "Lines posted: 2" in page.lines_title.text()
    assert "1 invoice(s) are in review" in page.messages.text()
    assert "2 PDF file(s) = 1 posted + 1 in review" in page.messages.text()
    assert len(google.store["R"]["Payouts"]) == 3          # headings + 2 lines
    assert google.store["R"]["Invoices"][1][rg.I["Scanned by"]] == "staff@example.com"
    # Review shows the one thing to decide, and the sidebar counts it
    review = window.review_page
    assert review.table.rowCount() == 1
    assert review.table.item(0, 0).text() == "Car"
    assert review.table.item(0, 1).text() == "NIOS"
    assert window.sidebar.buttons[PAGE_REVIEW].badge.text() == "1"


def test_trial_run_writes_nothing(qapp, world):
    window, google, _ = world
    window.scan_page.trial.setChecked(True)
    window.scan_page.scan()
    wait(qapp, window)
    assert window.scan_page.table.rowCount() == 2
    assert "trial run" in window.scan_page.lines_title.text()
    assert google.store["R"]["Payouts"] == [rg.PAYOUT_HEADERS]
    assert google.store["R"]["Invoices"] == [rg.INVOICE_HEADERS]


def test_saving_a_match_posts_the_invoice(qapp, world):
    window, google, _ = world
    window.scan_page.scan()
    wait(qapp, window)
    review = window.review_page
    assert review.panel.isVisibleTo(review)
    names = [review.match_combo.itemText(i) for i in range(review.match_combo.count())]
    assert names[0] == "Choose…" and "Others (not in the master)" in names
    review.match_combo.setCurrentIndex(review.match_combo.findData("Tata Punch EV"))
    review._save_match()
    wait(qapp, window)            # saving the match ...
    wait(qapp, window)            # ... then the scan it asked for
    assert google.store["R"]["Matches"][1][:3] == ["Car", "NIOS", "Tata Punch EV"]
    assert review.table.rowCount() == 0 and "Nothing needs review" in review.summary.text()
    assert window.sidebar.buttons[PAGE_REVIEW].badge.text() == ""
    ids = [r[0] for r in google.store["R"]["Payouts"][1:]]
    assert "DNS-226-2627-LAB" in ids and "DNS-226-2627-INC" in ids
    assert any(e[2] == "Match saved" for e in google.store["R"]["Log"][1:])


def test_cancelling_an_invoice(qapp, world, monkeypatch):
    window, google, _ = world
    window.scan_page.scan()
    wait(qapp, window)
    review = window.review_page
    review._cancel_invoice()                         # no reason given: refused
    assert not window.busy
    review.reason.setText("Raised by mistake")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    review._cancel_invoice()
    wait(qapp, window)
    wait(qapp, window)
    row = next(r for r in google.store["R"]["Invoices"] if r[0] == "DNS-226-2627")
    assert row[rg.I["State"]] == "Cancelled" and row[rg.I["Reason"]] == "Raised by mistake"
    assert review.table.rowCount() == 0
    assert window.scan_page.tiles["in review"].value_label.text() == "0"


def test_a_mistake_in_the_masters_sheet_stops_the_scan(qapp, world):
    window, google, _ = world
    google.store["M"]["Cars"].append(["Tata", "", "SUV", "Yes"])     # model missing
    window.scan_page.scan()
    wait(qapp, window)
    page = window.scan_page
    assert page.message_title.text() == "Stopped"
    assert "Model is required" in page.messages.text()
    assert page.table.rowCount() == 0
    assert google.store["R"]["Payouts"] == [rg.PAYOUT_HEADERS]
    assert "stopped" in window.review_page.summary.text()


def test_setup_checks_both_sheets(qapp, world):
    window, google, _ = world
    setup = window.setup_page
    setup.masters_link.setText("https://docs.google.com/spreadsheets/d/M/edit")
    setup.register_link.setText("R")
    setup._save_and_check()
    wait(qapp, window)
    text = setup.check_result.text()
    assert "Masters sheet “Drive N Style Masters” is fine" in text
    assert "Payout register “Drive N Style Payout Register” is fine" in text
    setup.register_link.setText("M")                 # the wrong sheet
    setup._save_and_check()
    wait(qapp, window)
    assert "is not a payout register" in setup.check_result.text()
    setup.start.setText("1/11/2026")
    setup._start_changed()
    assert settings.get("start_date") == "01-11-2026"
    setup.start.setText("soon")
    setup._start_changed()
    assert "Not a date" in setup.start_note.text()
    assert settings.get("start_date") == "01-11-2026"


def test_first_start_opens_on_setup(qapp, repo):
    window = MainWindow(service.Session(FakeGoogle({}), "x"))
    assert window.sidebar.buttons[PAGE_SETUP].isChecked()
    window.close()


# --- the actions behind the screens ------------------------------------------
def test_cancel_leaves_paid_lines_alone(repo):
    build_masters(repo)
    google = FakeGoogle(ms.to_tabs(repo, InputsRepo(repo)))
    session = service.Session(google, "staff@example.com")
    settings.save(masters_sheet_id="M", register_sheet_id="R")
    outcome = engine.calculate(ms.load_tabs(google.store["M"]).masters,
                               [("a.pdf", with_vehicle(inv_0753(), "I20", "Edhayan - Ooty"), "")])
    from datetime import datetime
    todo = rg.plan(google.store["R"]["Payouts"], google.store["R"]["Invoices"], outcome,
                   "staff", datetime(2026, 10, 5, 9, 0))
    google.append_rows("R", "Payouts", todo.payout_appends)
    google.append_rows("R", "Invoices", todo.invoice_appends)
    google.store["R"]["Payouts"][1][rg.P["Status"]] = "Paid"          # labour paid
    paid = service.cancel_invoice(session, "DNS26-GST-0753", "Customer returned")
    assert paid == ["DNS26-GST-0753-LAB"]
    labour, incentive = google.store["R"]["Payouts"][1:3]
    assert labour[rg.P["Status"]] == "Paid"
    assert incentive[rg.P["Status"]] == "Cancelled"
    assert incentive[rg.P["Remarks"]] == "Invoice cancelled: Customer returned"
    assert rg.verify(google.store["R"]["Payouts"], "x", datetime(2026, 10, 5)).payout_updates == []
    with pytest.raises(service.GoogleError, match="reason"):
        service.cancel_invoice(session, "DNS26-GST-0753", "  ")


def test_a_saved_match_is_replaced_not_repeated(repo):
    google = FakeGoogle({})
    session = service.Session(google, "staff@example.com")
    settings.save(register_sheet_id="R")
    service.save_match(session, "Car", "NIOS", "Others")
    service.save_match(session, "Car", " nios ", "Tata Punch EV")
    assert [r[:3] for r in google.store["R"]["Matches"][1:]] == [["Car", "nios", "Tata Punch EV"]]
    assert google.store["R"]["Log"][-1][4:6] == ["Others", "Tata Punch EV"]


def test_matches_of_the_monthly_tool_are_read(repo, tmp_path):
    from app.data.database import connect
    from app.data.invoices_repo import InvoicesRepo
    from app.data.masters_repo import MastersRepo
    path = tmp_path / "monthly.db"
    monthly = MastersRepo(connect(path))
    build_masters(monthly)
    inv = InvoicesRepo(monthly)
    car = next(c for c in monthly.list_rows("cars") if c["model"] == "i20")
    inv.set_car("", "I-20 Sportz", car["id"], all_invoices=True)
    inv.set_salesperson("", "Harish - Ho", 0, all_invoices=True)
    monthly.conn.close()
    assert service.monthly_tool_matches(path) == [
        dict(kind="Car", printed="i20sportz", target="Hyundai i20"),
        dict(kind="Salesperson", printed="harish - ho", target="Others")]
    assert service.monthly_tool_matches(tmp_path / "none.db") == []

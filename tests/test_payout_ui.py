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
from payout_app.ui.payouts_page import PaymentDialog, SlipDialog  # noqa: E402
from tests.fakes import FakeDrive, FakeGoogle  # noqa: E402
from tests.test_invoices import inv_0753, inv_226  # noqa: E402
from tests.test_payout_engine import build_masters, with_vehicle  # noqa: E402


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
    window = MainWindow(service.Session(google, "staff@example.com", FakeDrive()))
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


# --- Payouts and History (v0.17.0) -------------------------------------------
def scanned(qapp, world):
    """Scan (posts the two lines of DNS26-GST-0753) and open Payouts."""
    window, google, _ = world
    window.scan_page.scan()
    wait(qapp, window)
    window.payouts_page.reload()
    wait(qapp, window)
    return window, google, window.payouts_page


def test_payouts_lists_pending_lines(qapp, world):
    window, google, page = scanned(qapp, world)
    assert page.table.rowCount() == 2
    assert page.table.item(0, 1).text() == "DNS26-GST-0753"
    assert page.table.item(1, 3).text() == "Edhayan"
    assert page.tile_pending.value_label.text() == "349.97"
    assert page.selected.text().startswith("2 line(s) shown")
    page.table.setCurrentCell(1, 2)
    assert "invoice of 05-09-2026" in page.detail.text()
    assert "Working: Underbody: 200 x 1" in page.detail.text()
    page.kind.setCurrentIndex(page.kind.findData("Labour"))
    assert page.table.rowCount() == 1
    page.kind.setCurrentIndex(0)
    page.search.setText("nobody")
    assert page.table.rowCount() == 0


def test_recording_a_payment_from_the_screen(qapp, world, tmp_path):
    window, google, page = scanned(qapp, world)
    page._record()                                    # nothing ticked: only a message
    assert not window.busy
    page.tick(["DNS26-GST-0753-LAB", "DNS26-GST-0753-INC"])
    assert page.selected.text().startswith("2 line(s) ticked")
    page.record(page.ticked(), date.today(), "GPay", "UTR77", "", "evening run")
    wait(qapp, window)            # the payment ...
    wait(qapp, window)            # ... then the list is read again
    assert page.table.rowCount() == 0                 # nothing pending any more
    assert page.tile_pending.value_label.text() == "0.00"
    assert page.tile_today.value_label.text() == "349.97"
    page.status.setCurrentIndex(page.status.findData("Paid"))
    assert page.table.rowCount() == 2
    assert page.table.item(0, 7).text() == "GPay · UTR77"
    paid = google.store["R"]["Payouts"][1]
    assert paid[rg.P["Status"]] == "Paid" and paid[rg.P["Entered by"]] == "staff@example.com"
    # a paid line cannot be paid again from the screen ...
    page.tick(["DNS26-GST-0753-LAB"])
    page._record()
    assert not window.busy
    # ... but it can be reopened with a reason, and then held and released
    page.reopen(page.ticked(), "Wrong reference")
    wait(qapp, window)
    wait(qapp, window)
    assert google.store["R"]["Payouts"][1][rg.P["Status"]] == "Pending"
    page.status.setCurrentIndex(page.status.findData("Pending"))
    page.tick(["DNS26-GST-0753-LAB"])
    page.hold(page.ticked(), True, "Wait for the owner")
    wait(qapp, window)
    wait(qapp, window)
    assert page.tile_hold.value_label.text() == "150.00"
    # History shows all of it, newest first, and can be searched
    history = window.history_page
    history.reload()
    wait(qapp, window)
    what = [history.table.item(r, 2).text() for r in range(history.table.rowCount())]
    assert what[0] == "Put on hold" and "Payment reopened" in what and "Posted" in what
    history.search.setText("reopened")
    assert history.table.rowCount() == 1 and "1 of" in history.count.text()


def test_payment_dialog_insists_on_reference_or_proof(qapp, world):
    window, google, page = scanned(qapp, world)
    dialog = PaymentDialog(page.shown, proofs_ready=False, parent=page)
    assert not dialog.proof.isEnabled()
    dialog._accept()
    assert "reference number or a proof" in dialog.problem.text()
    assert dialog.result() != PaymentDialog.Accepted
    dialog.reference.setText(" UTR5 ")
    dialog._accept()
    assert dialog.result() == PaymentDialog.Accepted
    values = dialog.values()
    assert values["paid_date"] == date.today() and values["mode"] == "Cash"
    assert values["reference"] == "UTR5" and values["proof_path"] == ""


def test_payout_slip_is_shown_and_saved_as_pdf(qapp, world, tmp_path):
    window, google, page = scanned(qapp, world)
    dialog = SlipDialog(page.view.lines, page)
    text = dialog.page.toPlainText()
    assert "To pay - pending" in text and "Edhayan" in text and "Grand total" in text
    dialog.which.setCurrentIndex(dialog.which.findData("paid"))
    assert "Nothing to show" in dialog.page.toPlainText()
    dialog.which.setCurrentIndex(0)
    target = tmp_path / "slip.pdf"
    dialog.save_pdf(str(target))
    assert target.read_bytes().startswith(b"%PDF") and target.stat().st_size > 1000


def test_owner_creates_the_proofs_folder_from_setup(qapp, world, monkeypatch, tmp_path):
    window, google, page = scanned(qapp, world)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.setup_page._create_proofs_folder()
    wait(qapp, window)
    assert google.store["R"]["Setup"][1] == ["Proofs folder", "F1"]
    assert "Drive N Style Payout Proofs" in window.setup_page.proofs.text()
    shot = tmp_path / "pay.png"
    shot.write_bytes(b"x")
    page.reload()
    wait(qapp, window)
    page.tick(["DNS26-GST-0753-INC"])
    page.record(page.ticked(), date.today(), "GPay", "", str(shot))
    wait(qapp, window)
    wait(qapp, window)
    assert window.session.drive.uploads[0][2] == "F1"
    assert google.store["R"]["Payouts"][2][rg.P["Proof"]].startswith("https://drive.google.com")
    page.status.setCurrentIndex(page.status.findData("Paid"))
    assert page.table.item(0, 7).text() == "GPay · proof"


def test_owner_clears_the_register_from_setup(qapp, world):
    window, google, page = scanned(qapp, world)
    assert len(google.store["R"]["Payouts"]) == 3
    setup = window.setup_page
    setup.clear_register("clear")                    # wrong word: refused, shown
    import PySide6.QtWidgets as widgets
    original = widgets.QMessageBox.warning
    widgets.QMessageBox.warning = lambda *a, **k: None
    try:
        wait(qapp, window)
    finally:
        widgets.QMessageBox.warning = original
    assert len(google.store["R"]["Payouts"]) == 3
    setup.clear_register("CLEAR")
    wait(qapp, window)
    assert google.store["R"]["Payouts"] == [rg.PAYOUT_HEADERS]
    assert google.store["R"]["Invoices"] == [rg.INVOICE_HEADERS]
    assert "Register cleared: 2 payout line(s), 2 invoice(s)" in setup.housekeeping.text()
    assert "backup" in setup.housekeeping.text()
    assert window.session.drive.copies[0][0] == "R"
    page.reload()
    wait(qapp, window)
    assert page.table.rowCount() == 0


def test_duplicates_dialog_only_lets_extras_be_ticked(qapp, world):
    from PySide6.QtCore import Qt
    from payout_app.ui.setup_page import DuplicatesDialog
    window, google, _ = world
    files = [dict(id="M", name="Drive N Style Masters", kind="Sheet",
                  created="05-10-2026 10:30", link="", in_use=True),
             dict(id="OLD", name="Drive N Style Masters", kind="Sheet",
                  created="05-10-2026 09:40", link="", in_use=False)]
    dialog = DuplicatesDialog(files, window.setup_page)
    assert dialog.table.item(0, 4).text() == "in use"
    assert not dialog.table.item(0, 0).flags() & Qt.ItemIsUserCheckable
    assert dialog.chosen() == []
    dialog.table.item(1, 0).setCheckState(Qt.Checked)
    assert [f["id"] for f in dialog.chosen()] == ["OLD"]
    window.session.drive.files = [
        dict(id="OLD", name="Drive N Style Masters", mimeType="sheet", createdTime="",
             webViewLink="")]
    window.setup_page.trash(dialog.chosen())
    wait(qapp, window)
    assert window.session.drive.trashed == ["OLD"]
    assert "1 duplicate(s) moved" in window.setup_page.housekeeping.text()


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

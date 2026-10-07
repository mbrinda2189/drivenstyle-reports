"""
test_payments.py - Recording payments, proofs, hold, reopen and the slip
========================================================================

Payout app, v0.17.0. The real service code runs against the stand-ins of
tests/fakes.py. What is checked:
* a payment needs a reference or a proof, a mode and a date not in the
  future; only lines waiting for payment can be paid; if one chosen line
  is not, nothing at all is recorded;
* one proof covers several lines, gets a telling name and goes to the
  shared proofs folder;
* only the payment columns are written - the calculated cells still match
  their sealed copy afterwards;
* reopening and holding need a reason and are logged;
* the payout slip groups by payee and equals the register.
"""

from datetime import date, datetime

import pytest

from app.data.inputs_repo import InputsRepo
from payout_app import engine, masters_sheet as ms, register as rg, service, settings, slip
from payout_app.google_api import GoogleError
from tests.fakes import FakeDrive, FakeGoogle
from tests.test_payout_engine import build_masters, september

NOW = lambda: datetime(2026, 10, 6, 11, 0)
TODAY = date(2026, 10, 6)


@pytest.fixture
def world(repo):
    """A register holding the five lines of the three September invoices."""
    build_masters(repo)
    google, drive = FakeGoogle(ms.to_tabs(repo, InputsRepo(repo))), FakeDrive()
    session = service.Session(google, "staff@example.com", drive)
    settings.save(masters_sheet_id="M", register_sheet_id="R")
    outcome = engine.calculate(ms.load_tabs(google.store["M"]).masters, september())
    todo = rg.plan(google.store["R"]["Payouts"], google.store["R"]["Invoices"], outcome,
                   "staff@example.com", datetime(2026, 10, 5, 18, 0))
    google.append_rows("R", rg.PAYOUTS, todo.payout_appends)
    google.append_rows("R", rg.INVOICES, todo.invoice_appends)
    return session, google, drive


def line(google, line_id):
    return next(l for l in rg.payout_lines(google.store["R"][rg.PAYOUTS])
                if l["line_id"] == line_id)


def test_register_view(world):
    session, google, _ = world
    view = service.read_register(session)
    assert [l["line_id"] for l in view.lines] == [
        "DNS26-GST-0753-LABM", "DNS26-GST-0753-INC", "DNS-226-2627-LABM",
        "DNS-226-2627-LABS", "DNS-226-2627-INC", "DNS-237-2627-LABM"]
    first = view.lines[0]
    assert (first["row"], first["status"], first["amount"]) == (2, "Pending", 150.0)
    assert first["invoice_date"] == date(2026, 9, 5) and first["paid_date"] is None
    assert view.proofs_folder == "" and view.log == []


def test_payment_with_reference_covers_several_lines(world):
    session, google, _ = world
    ids = ["DNS26-GST-0753-LABM", "DNS-226-2627-LABS"]
    link = service.record_payment(session, ids, TODAY, "Cash", "V-102", now=NOW)
    assert link == ""
    paid = line(google, ids[1])
    assert (paid["status"], paid["paid_date"], paid["mode"], paid["reference"]) == \
        ("Paid", TODAY, "Cash", "V-102")
    assert paid["entered_by"] == "staff@example.com" and paid["entered_at"] == "06-10-2026 11:00"
    assert line(google, "DNS-237-2627-LABM")["status"] == "Pending"
    # the calculated cells are untouched: they still match their sealed copy
    check = rg.verify(google.store["R"][rg.PAYOUTS], "x", NOW())
    assert check.payout_updates == [] and check.problems == [] and check.warnings == []
    log = google.store["R"][rg.LOG][1:]
    assert [(e[2], e[3], e[5]) for e in log] == [
        ("Payment recorded", ids[0], "Paid | 06-10-2026 | Cash | V-102"),
        ("Payment recorded", ids[1], "Paid | 06-10-2026 | Cash | V-102")]


def test_rules_for_recording(world, tmp_path):
    session, google, _ = world
    one = ["DNS26-GST-0753-INC"]
    cases = [
        (dict(line_ids=[], paid_date=TODAY, mode="Cash", reference="x"), "Tick the lines"),
        (dict(line_ids=one, paid_date=TODAY, mode="", reference="x"), "Choose how"),
        (dict(line_ids=one, paid_date=TODAY, mode="GPay"), "reference number or a proof"),
        (dict(line_ids=one, paid_date=date(2026, 10, 7), mode="GPay", reference="x"),
         "cannot be in the future"),
        (dict(line_ids=["NOPE-LAB"], paid_date=TODAY, mode="GPay", reference="x"),
         "no longer in the register"),
        (dict(line_ids=one, paid_date=TODAY, mode="GPay", proof_path=tmp_path / "none.jpg"),
         "was not found"),
    ]
    for arguments, message in cases:
        with pytest.raises(GoogleError, match=message):
            service.record_payment(session, now=NOW, **arguments)
    text = tmp_path / "notes.txt"
    text.write_text("x")
    with pytest.raises(GoogleError, match="picture or a PDF"):
        service.record_payment(session, one, TODAY, "GPay", proof_path=text, now=NOW)
    assert all(l["status"] == "Pending" for l in rg.payout_lines(google.store["R"][rg.PAYOUTS]))
    assert google.store["R"][rg.LOG] == [rg.LOG_HEADERS]


def test_if_one_line_is_already_paid_nothing_is_recorded(world):
    session, google, _ = world
    service.record_payment(session, ["DNS26-GST-0753-LABM"], TODAY, "Cash", "V-1", now=NOW)
    with pytest.raises(GoogleError, match=r"DNS26-GST-0753-LABM \(Paid\)"):
        service.record_payment(session, ["DNS-237-2627-LABM", "DNS26-GST-0753-LABM"],
                               TODAY, "Cash", "V-2", now=NOW)
    assert line(google, "DNS-237-2627-LABM")["status"] == "Pending"


def test_proof_is_uploaded_to_the_shared_folder(world, tmp_path):
    session, google, drive = world
    shot = tmp_path / "IMG_2041.JPG"
    shot.write_bytes(b"picture")
    with pytest.raises(GoogleError, match="proofs folder is not set up"):
        service.record_payment(session, ["DNS26-GST-0753-INC"], TODAY, "GPay",
                               proof_path=shot, now=NOW)
    name, url = service.create_proofs_folder(session, now=NOW)
    assert name == "Drive N Style Payout Proofs" and url.endswith("/F1")
    assert google.store["R"][rg.SETUP][1] == ["Proofs folder", "F1"]
    assert service.create_proofs_folder(session)[1].endswith("/F1")     # kept, not remade
    assert len(drive.folders) == 1
    link = service.record_payment(session, ["DNS26-GST-0753-INC"], TODAY, "GPay",
                                  "UTR 55/12", shot, "evening", now=NOW)
    assert drive.uploads == [("IMG_2041.JPG", "2026-10-06_GPay_UTR-55-12_Edhayan.jpg", "F1")]
    paid = line(google, "DNS26-GST-0753-INC")
    assert paid["proof"] == link and paid["remarks"] == "evening"
    assert service.read_register(session).proofs_folder == "F1"


def test_proof_names():
    name = service.proof_name
    assert name(TODAY, "Cash", "", ["", ""], ".PDF") == "2026-10-06_Cash_Labour.pdf"
    assert name(TODAY, "GPay", "T1", ["Asha", "Kumaran", "Asha"], ".png") == \
        "2026-10-06_GPay_T1_2-payees.png"


def test_register_without_setup_tab_gets_one(world):
    session, google, _ = world
    del google.store["R"][rg.SETUP]                      # a register made before v0.17.0
    service.create_proofs_folder(session, now=NOW)
    assert google.store["R"][rg.SETUP] == [["Key", "Value"], ["Proofs folder", "F1"]]


def test_reopen_needs_a_reason_and_keeps_the_trail(world):
    session, google, _ = world
    ids = ["DNS26-GST-0753-INC"]
    service.record_payment(session, ids, TODAY, "GPay", "UTR9", now=NOW)
    with pytest.raises(GoogleError, match="reason"):
        service.reopen_payment(session, ids, " ", now=NOW)
    with pytest.raises(GoogleError, match="Only paid lines"):
        service.reopen_payment(session, ["DNS-237-2627-LABM"], "x", now=NOW)
    service.reopen_payment(session, ids, "Paid to the wrong person", now=NOW)
    again = line(google, ids[0])
    assert (again["status"], again["paid_date"], again["reference"], again["mode"]) == \
        ("Pending", None, "", "")
    assert again["remarks"] == "Reopened: Paid to the wrong person"
    last = google.store["R"][rg.LOG][-1]
    assert last[2:] == ["Payment reopened", ids[0], "Paid | 06-10-2026 | GPay | UTR9",
                        "Pending - Paid to the wrong person"]
    service.record_payment(session, ids, TODAY, "GPay", "UTR10", now=NOW)   # afresh
    assert line(google, ids[0])["reference"] == "UTR10"


def test_hold_and_release(world):
    session, google, _ = world
    ids = ["DNS-226-2627-INC"]
    with pytest.raises(GoogleError, match="reason"):
        service.set_hold(session, ids, True, now=NOW)
    service.set_hold(session, ids, True, "Customer has not paid yet", now=NOW)
    held = line(google, ids[0])
    assert held["status"] == "Hold" and held["remarks"] == "On hold: Customer has not paid yet"
    with pytest.raises(GoogleError, match="Only pending lines"):
        service.set_hold(session, ids, True, "again", now=NOW)
    service.set_hold(session, ids, False, now=NOW)
    assert line(google, ids[0])["status"] == "Pending"
    service.set_hold(session, ids, True, "wait", now=NOW)
    service.record_payment(session, ids, TODAY, "GPay", "U1", now=NOW)     # hold can be paid
    assert line(google, ids[0])["status"] == "Paid"


def test_payout_slip(world):
    session, google, _ = world
    lines = service.read_register(session).lines
    to_pay = slip.build(lines, now=NOW())
    assert to_pay.title == "To pay - pending as on 06-10-2026"
    # v0.21.0: one block per kind of labour, each with its own total
    assert [(b.title, len(b.lines)) for b in to_pay.blocks] == [
        ("Labour - Floor mat", 3), ("Labour - Sunfilm", 1), ("Edhayan", 1),
        ("Nandha Kumar", 1)]
    assert to_pay.blocks[0].total == 150 + 150 + 175 and to_pay.blocks[1].total == 800
    assert to_pay.total == pytest.approx(sum(l["amount"] for l in lines))
    service.record_payment(session, ["DNS26-GST-0753-LABM", "DNS26-GST-0753-INC"],
                           TODAY, "GPay", "U1", now=NOW)
    lines = service.read_register(session).lines
    paid = slip.build(lines, TODAY, NOW())
    assert paid.title == "Paid on 06-10-2026" and paid.count == 2
    assert slip.build(lines, date(2026, 10, 5), NOW()).blocks == []
    assert slip.build(lines, now=NOW()).count == 4
    html = slip.to_html(paid)
    assert "Edhayan" in html and "Grand total" in html and "DNS26-GST-0753" in html
    assert "Labour - Floor mat" in html
    # a plain "Labour" line posted before v0.21.0 keeps a block of its own, first
    old = dict(lines[0], type="Labour", line_id="OLD-1-LAB", status="Pending")
    assert [b.title for b in slip.build(lines + [old], now=NOW()).blocks][:3] == [
        "Labour", "Labour - Floor mat", "Labour - Sunfilm"]
    assert "Nothing to show" in slip.to_html(slip.build(lines, date(2026, 10, 5), NOW()))

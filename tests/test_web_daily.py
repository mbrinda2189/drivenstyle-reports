"""
test_web_daily.py - The daily payouts through the web server (v0.27.0)
======================================================================

The amounts and the posting rules are tested in test_payout_engine.py and
test_payments.py. Here the same sample invoices go through the WEB
addresses, with the register in the database instead of a Google Sheet,
to prove:

    * staff can do the whole daily job; nothing answers without a sign-in
    * an invoice is posted once, whoever scans and however often
    * invoices before the start date are left alone; only an admin may
      change that date
    * an invoice in review is posted as soon as its name is matched, and
      the match is the monthly tool's own (shared)
    * a daily scan never touches the months read into the monthly tool
    * the payment rules: reference or proof, not in the future, only
      Pending / Hold; reopen and hold need a reason; nothing half-recorded
    * a cancelled invoice: unpaid lines cancelled, paid lines left alone
    * a re-issued invoice is noticed
    * every change is in the log with who made it; only an admin can clear
      the register, with a backup

Client PDFs are never in Git, so `daily_api.read_files` is replaced by a
stand-in that hands out invoices built in code for the uploaded names.
"""

from datetime import date, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("itsdangerous")

from app.data.database import connect                         # noqa: E402
from app.data.masters_repo import MastersRepo                 # noqa: E402
from payout_app import engine                                 # noqa: E402
from tests.test_invoices import inv_0753, inv_226, inv_237    # noqa: E402
from tests.test_payout_engine import build_masters, with_vehicle   # noqa: E402
from tests.test_web_auth import ADMIN, H, make, sign_in       # noqa: E402
from web.backend import daily_api                             # noqa: E402

STAFF = "asha@gmail.com"
PDF = b"%PDF-1.4 stand-in"
TODAY = date.today().isoformat()


class Drawer:
    """The stand-in for reading PDFs: file name -> the invoice it "contains"."""

    def __init__(self):
        self.invoices = {}

    def put(self, client, inv, expect=200):
        self.invoices[inv.file_name] = inv
        reply = client.post("/api/daily/files", params={"filename": inv.file_name},
                            content=PDF, headers=H)
        assert reply.status_code == expect, reply.text
        return inv

    def read(self, paths, progress=None, cache=None):
        return [(p.name, self.invoices.get(p.name), "" if p.name in self.invoices
                 else "Could not be read.") for p in paths]


@pytest.fixture
def world(tmp_path, monkeypatch):
    app, settings = make(tmp_path)
    conn = connect(settings.db_path)
    build_masters(MastersRepo(conn, "setup"))          # the engine tests' masters
    conn.close()
    admin = sign_in(app, ADMIN)
    admin.post("/api/users", json={"email": STAFF}, headers=H)
    # The sample invoices are September's: the register must start before them.
    assert admin.put("/api/daily/start-date", json={"date": "2026-09-01"},
                     headers=H).json() == {"start_date": "2026-09-01"}
    drawer = Drawer()
    monkeypatch.setattr(daily_api, "read_files", drawer.read)
    return settings, admin, sign_in(app, STAFF), drawer


def september(drawer, client):
    drawer.put(client, with_vehicle(inv_0753(), "I20", "Edhayan - Ooty"))
    drawer.put(client, inv_226())
    drawer.put(client, with_vehicle(inv_237(), "EXTER", "Kumaran - HO"))


def scan(client):
    reply = client.post("/api/daily/scan", headers=H)
    assert reply.status_code == 200, reply.text
    return reply.json()


def lines(client):
    return {l["line_id"]: l for l in client.get("/api/daily/lines").json()["lines"]}


def test_needs_a_sign_in_and_the_two_admin_things(world, tmp_path):
    _, _, staff, _ = world
    from fastapi.testclient import TestClient
    nobody = TestClient(staff.app)
    assert nobody.get("/api/daily/overview").status_code == 401
    assert nobody.post("/api/daily/scan", headers=H).status_code == 401
    assert nobody.get("/api/daily/proofs/x.jpg").status_code == 401
    assert staff.put("/api/daily/start-date", json={"date": "2026-01-01"}, headers=H).status_code == 403
    assert staff.post("/api/daily/clear", json={"confirm": "CLEAR"}, headers=H).status_code == 403


def test_an_invoice_is_posted_once(world):
    settings, admin, staff, drawer = world
    assert staff.post("/api/daily/scan", headers=H).status_code == 400        # nothing uploaded
    september(drawer, staff)
    assert [f["name"] for f in staff.get("/api/daily/overview").json()["inbox"]] == sorted(drawer.invoices)
    report = scan(staff)
    assert report["tally"]["posted"] == 3 and report["tally"]["files"] == 3
    assert report["review"] == [] and report["not_used"] == []
    posted = {l["line_id"]: l for l in report["posted"]}
    assert posted["DNS26-GST-0753-LABM"]["amount"] == 150
    assert posted["DNS26-GST-0753-INC"]["payee"] == "Edhayan"
    assert report["posted_total"] == round(sum(l["amount"] for l in posted.values()), 2)
    # The PDFs left the inbox and are kept; the register has the same lines.
    daily = settings.data_dir / "daily"
    assert list((daily / "inbox").iterdir()) == []
    assert sorted(p.name for p in (daily / "pdfs").iterdir()) == sorted(drawer.invoices)
    assert set(lines(staff)) == set(posted)
    view = staff.get("/api/daily/overview").json()
    assert view["totals"]["pending"] == {"lines": len(posted), "amount": report["posted_total"]}
    # The same PDFs again, by the admin this time: nothing is posted twice.
    september(drawer, admin)
    again = scan(admin)
    assert again["tally"]["already posted"] == 3 and again["posted"] == []
    assert set(lines(staff)) == set(posted)
    # The months of the monthly tool are untouched by daily scans.
    assert admin.get("/api/monthly/2026-09/overview").json()["scan"] is None
    assert admin.get("/api/monthly/history").json()["months"] == []


def test_invoices_before_the_start_date_are_left_alone(world):
    _, admin, staff, drawer = world
    assert admin.put("/api/daily/start-date", json={"date": "2026-10-01"}, headers=H).status_code == 200
    assert admin.put("/api/daily/start-date", json={"date": "1 October"}, headers=H).status_code == 400
    september(drawer, staff)
    report = scan(staff)
    assert report["tally"]["before start date"] == 3 and report["posted"] == []
    assert lines(staff) == {}
    # An invoice left alone is not shown as waiting, even if it cannot be calculated.
    drawer.put(staff, with_vehicle(inv_0753(), "NIOS", "Edhayan - Ooty"))
    left = scan(staff)
    assert left["tally"]["before start date"] == 1 and left["review"] == [] and left["issues"] == []
    assert staff.get("/api/daily/review").json() == {"invoices": [], "issues": []}
    log = staff.get("/api/daily/log").json()["entries"]
    assert [(e["user"], e["field"], e["old_value"], e["new_value"]) for e in log][:2] == [
        (ADMIN, "Start date", "01-09-2026", "01-10-2026"),
        (ADMIN, "Start date", "01-10-2026", "01-09-2026")]


def test_review_is_fixed_by_a_match_shared_with_the_monthly_tool(world):
    _, admin, staff, drawer = world
    drawer.put(staff, with_vehicle(inv_0753(), "NIOS", "Edhayan - Ooty"))     # car not in the master
    report = scan(staff)
    assert report["tally"]["in review"] == 1 and report["posted"] == []
    assert report["issues"][0]["kind"] == "Car" and report["issues"][0]["printed"] == "NIOS"
    waiting = staff.get("/api/daily/review").json()
    assert [i["invoice_no"] for i in waiting["invoices"]] == ["DNS26-GST-0753"]
    assert "NIOS" in waiting["invoices"][0]["reason"] and waiting["issues"][0]["kind"] == "Car"
    assert staff.get("/api/daily/overview").json()["in_review"] == 1
    cars = staff.get("/api/daily/choices").json()["Car"]
    assert cars[-1] == {"id": 0, "text": "Others (not in master)"}
    i20 = next(c["id"] for c in cars if c["text"] == "Hyundai i20")
    bad = staff.post("/api/daily/match", json={"kind": "Car", "printed": "NIOS", "target_id": 999},
                     headers=H)
    assert bad.status_code == 400 and "Choose a car" in bad.json()["detail"]
    fixed = staff.post("/api/daily/match", headers=H, json={
        "kind": "Car", "printed": "NIOS", "invoices": ["DNS26-GST-0753"], "target_id": i20}).json()
    assert fixed["done"] == "Hyundai i20 set for all invoices showing “NIOS”."
    assert fixed["report"]["tally"]["posted"] == 1                # posted at once
    assert staff.get("/api/daily/review").json() == {"invoices": [], "issues": []}
    assert "DNS26-GST-0753-LABM" in lines(staff)
    # The match is the monthly tool's own saved match.
    shared = admin.get("/api/monthly/2026-09/matches").json()
    assert [(m["kind"], m["printed"], m["target"]) for m in shared] == [("car", "nios", "Hyundai i20")]


def test_payment_rules(world):
    settings, _, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    mat, inc = "DNS26-GST-0753-LABM", "DNS26-GST-0753-INC"
    pay = lambda **body: staff.post("/api/daily/pay", headers=H, json={   # noqa: E731
        "line_ids": [mat], "paid_date": TODAY, "mode": "GPay", **body})
    assert "reference number or a proof" in pay().json()["detail"]
    assert "cannot be in the future" in pay(
        reference="UTR1", paid_date=(date.today() + timedelta(days=1)).isoformat()).json()["detail"]
    assert "how it was paid" in pay(reference="UTR1", mode=" ").json()["detail"]
    assert "Tick the lines" in pay(reference="UTR1", line_ids=[]).json()["detail"]
    assert lines(staff)[mat]["status"] == "Pending"                 # nothing recorded so far

    done = pay(reference="UTR 123", remarks="paid to  fitter").json()
    assert done == {"paid": 1, "amount": 150.0, "proof": ""}
    line = lines(staff)[mat]
    assert (line["status"], line["paid_date"], line["mode"], line["reference"]) == (
        "Paid", TODAY, "GPay", "UTR 123")
    assert line["remarks"] == "paid to fitter" and line["entered_by"] == STAFF
    assert line["amount"] == 150 and line["working"]               # calculated cells untouched
    # Paying it again, together with another line: NOTHING is recorded.
    both = pay(reference="UTR9", line_ids=[inc, mat])
    assert both.status_code == 400 and f"{mat} (Paid)" in both.json()["detail"]
    assert lines(staff)[inc]["status"] == "Pending"

    # A proof instead of a reference; one proof for one payee.
    assert staff.post("/api/daily/proofs", params={"filename": "note.txt"}, content=b"x",
                      headers=H).status_code == 400
    token = staff.post("/api/daily/proofs", params={"filename": "IMG 01.JPG"}, content=b"\xff\xd8jpg",
                       headers=H).json()["token"]
    assert pay(line_ids=[inc], proof_token="../../x.jpg").status_code == 400
    proof = pay(line_ids=[inc], proof_token=token).json()["proof"]
    assert proof == f"{TODAY}_GPay_Edhayan.jpg" and lines(staff)[inc]["proof"] == proof
    assert staff.get(f"/api/daily/proofs/{proof}").content == b"\xff\xd8jpg"
    assert list((settings.data_dir / "daily" / "proofs" / "waiting").iterdir()) == []
    assert pay(line_ids=[inc], proof_token=token).status_code == 400          # used up

    # Reopen and hold need a reason, and the right state.
    assert "give the reason" in staff.post("/api/daily/reopen", json={"line_ids": [mat]},
                                           headers=H).json()["detail"]
    assert staff.post("/api/daily/reopen", json={"line_ids": [mat], "reason": "wrong UTR"},
                      headers=H).json() == {"reopened": 1}
    line = lines(staff)[mat]
    assert (line["status"], line["reference"], line["remarks"]) == ("Pending", "", "Reopened: wrong UTR")
    assert "Only paid lines" in staff.post("/api/daily/reopen", headers=H, json={
        "line_ids": [mat], "reason": "again"}).json()["detail"]
    assert "give the reason" in staff.post("/api/daily/hold", json={"line_ids": [mat]},
                                           headers=H).json()["detail"]
    assert staff.post("/api/daily/hold", json={"line_ids": [mat], "reason": "query"},
                      headers=H).json() == {"changed": 1}
    assert lines(staff)[mat]["status"] == "Hold"
    assert staff.post("/api/daily/hold", json={"line_ids": [mat], "hold": False},
                      headers=H).json() == {"changed": 1}
    assert pay(reference="UTR 124").status_code == 200

    what = [(e["user"], e["field"], e["record"]) for e in staff.get("/api/daily/log").json()["entries"]]
    assert [w[1] for w in what if w[2] == mat] == [
        "Payment recorded", "Hold released", "Put on hold", "Payment reopened", "Payment recorded"]
    assert {w[0] for w in what if w[2] == mat} == {STAFF}


def test_cancelled_and_reissued_invoices(world):
    _, _, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    mat, inc = "DNS26-GST-0753-LABM", "DNS26-GST-0753-INC"
    staff.post("/api/daily/pay", headers=H, json={"line_ids": [mat], "paid_date": TODAY,
                                                  "mode": "Cash", "reference": "V-12"})
    assert staff.post("/api/daily/cancel", json={"invoice_no": "DNS26-GST-0753"},
                      headers=H).status_code == 400                               # reason needed
    assert staff.post("/api/daily/cancel", json={"invoice_no": "NOPE", "reason": "x"},
                      headers=H).status_code == 400
    left = staff.post("/api/daily/cancel", headers=H, json={
        "invoice_no": "DNS26-GST-0753", "reason": "billed twice"}).json()
    assert left == {"paid_lines_left": [mat]}
    now = lines(staff)
    assert now[mat]["status"] == "Paid" and now[inc]["status"] == "Cancelled"
    assert now[inc]["remarks"] == "Invoice cancelled: billed twice"
    # A cancelled invoice is never posted again.
    drawer.put(staff, with_vehicle(inv_0753(), "I20", "Edhayan - Ooty"))
    assert scan(staff)["tally"]["cancelled"] == 1

    # DNS-226 saved again from Zoho with another salesperson: re-issued.
    changed = inv_226()
    changed.salesperson = "Kumaran - HO"
    drawer.put(staff, changed)
    report = scan(staff)
    assert report["tally"]["re-issued"] == 1
    states = {i["invoice_no"]: i["state"] for i in staff.get("/api/daily/lines").json()["invoices"]}
    assert states["DNS-226-2627"] == "Re-issued" and states["DNS26-GST-0753"] == "Cancelled"


def test_only_an_admin_clears_the_register_with_a_backup(world):
    settings, admin, staff, drawer = world
    september(drawer, staff)
    posted = len(scan(staff)["posted"])
    assert admin.post("/api/daily/clear", json={"confirm": "clear"}, headers=H).status_code == 400
    done = admin.post("/api/daily/clear", json={"confirm": "CLEAR"}, headers=H).json()
    assert (done["lines"], done["invoices"]) == (posted, 3)
    assert (settings.data_dir / done["backup"]).is_file() and "before-clear" in done["backup"]
    assert lines(staff) == {}
    first = staff.get("/api/daily/log").json()["entries"][0]
    assert (first["user"], first["field"]) == (ADMIN, "Register cleared")
    # The log itself survives, and is the read-only audit log.
    kept = admin.get("/api/audit", params={"master": "payouts"}).json()["entries"]
    assert sum(e["field"] == "Posted" for e in kept) == 3          # one per invoice posted
    # Every PDF counts as new again.
    september(drawer, staff)
    assert scan(staff)["tally"]["posted"] == 3


def test_a_file_that_is_not_an_invoice(world):
    _, _, staff, drawer = world
    assert staff.post("/api/daily/files", params={"filename": "list.xlsx"}, content=PDF,
                      headers=H).status_code == 400
    assert staff.post("/api/daily/files", params={"filename": "a.pdf"}, content=b"hello",
                      headers=H).status_code == 400
    staff.post("/api/daily/files", params={"filename": "..\\..\\Quotation.pdf"}, content=PDF, headers=H)
    assert [f["name"] for f in staff.get("/api/daily/overview").json()["inbox"]] == ["Quotation.pdf"]
    report = scan(staff)                                       # the stand-in cannot read it
    assert report["tally"]["not used"] == 1 and report["not_used"][0]["file_name"] == "Quotation.pdf"
    staff.post("/api/daily/files", params={"filename": "b.pdf"}, content=PDF, headers=H)
    assert staff.delete("/api/daily/files/b.pdf", headers=H).json() == {"ok": True}
    assert staff.get("/api/daily/overview").json()["inbox"] == []
    assert engine.LINE_TYPES == tuple(staff.get("/api/daily/overview").json()["types"])

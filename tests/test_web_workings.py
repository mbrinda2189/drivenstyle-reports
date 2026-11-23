"""
test_web_workings.py - "Show working" on the daily Payouts (v0.37.0)
====================================================================

Brinda (23-11-2026): the client's staff check every invoice's labour and
incentive by hand, so the tool shows HOW it reached each amount - on the
screen, as a one-invoice PDF / Excel, and as an Excel for a date range -
and staff may mark a working as checked (optional). Proved here:

    * every posted invoice gets its working, and the working's totals ARE
      the posted line amounts (labour by kind, spot incentive, internal)
    * the incentive steps state the whole-invoice rule with its numbers
    * the working is the one the amounts came from: Recalculate after a
      master change stores a new working and keeps the old one as history;
      a check made before then shows as "checked an earlier working"
    * checking is optional (paying needs no check), logged, can be undone
    * an invoice posted before v0.37.0 can have its working rebuilt from
      its PDF - saved only if it gives exactly the posted amounts
    * the downloads: one invoice as Excel (and PDF when the machine can
      make one), a date range as Excel with check formulas
"""

import io
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("itsdangerous")

from openpyxl import load_workbook                            # noqa: E402

from app.data.database import connect                         # noqa: E402
from app.reports.pdf_export import pdf_possible               # noqa: E402
from tests.test_web_auth import H                             # noqa: E402
from tests.test_web_daily import TODAY, lines, scan, september, world   # noqa: E402,F401
from tests.test_web_recalculate import recalc, relink          # noqa: E402

INVOICES = ("DNS-226-2627", "DNS-237-2627", "DNS26-GST-0753")


def show(client, number, expect=200):
    reply = client.get(f"/api/daily/working/{number}")
    assert reply.status_code == expect, reply.text
    return reply.json()


def test_every_posted_invoice_has_a_working_that_gives_its_amounts(world):
    _, _, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    posted = lines(staff)
    for number in INVOICES:
        view = show(staff, number)
        w = view["working"]
        mine = {lid: l for lid, l in posted.items() if l["invoice_no"] == number}
        # the working's own lines are exactly the posted ones
        assert {l["line_id"]: l["amount"] for l in w["lines"]} == \
            {lid: l["amount"] for lid, l in mine.items()}
        # labour: each kind's total = its line; each item = rate x qty
        for g in w["labour"]["groups"]:
            suffix = {"Floor mat": "LABM", "Sunfilm": "LABS", "Other": "LABO"}[g["kind"]]
            assert mine[f"{number}-{suffix}"]["amount"] == g["total"]
            assert g["total"] == round(sum(i["amount"] for i in g["items"]), 2)
            for i in g["items"]:
                assert i["amount"] == round(i["rate"] * i["qty"], 2)
        # spot incentive: full x min(1, paid / fixed) = the line
        inc = w["incentive"]
        if inc["payable"]:
            assert mine[f"{number}-INC"]["amount"] == inc["payable"]
            share = 1 if inc["fixed"] <= 0 else min(1, inc["paid"] / inc["fixed"])
            assert inc["payable"] == round(inc["full"] * share, 2)
            assert inc["paid"] == round(sum(i["paid"] for i in w["items"]), 2)
            assert any("Incentive payable" in s for s in inc["steps"])
        # what was read: every item with its printed name and master product
        assert w["items"] and all(i["printed"] and i["product"] for i in w["items"])
        assert view["history"][0]["why"] == "Posted"
        assert view["check"] is None and view["rebuildable"] is False
    listing = staff.get("/api/daily/lines").json()
    assert sorted(listing["with_working"]) == sorted(INVOICES)
    assert listing["checks"] == {}
    show(staff, "NOPE", expect=404)


def test_checking_is_optional_logged_and_follows_recalculate(world):
    settings, _, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    number = "DNS-237-2627"
    # Paying needs no check.
    paid = staff.post("/api/daily/pay", headers=H, json={
        "line_ids": ["DNS-226-2627-LABS"], "paid_date": TODAY, "mode": "Cash",
        "reference": "V-1"})
    assert paid.status_code == 200, paid.text
    done = staff.post(f"/api/daily/working/{number}/check", headers=H,
                      json={"checked": True, "note": "tallied with PDF"}).json()
    assert done["check"]["checked_by"] == "asha@gmail.com"
    assert done["check"]["note"] == "tallied with PDF" and done["check"]["current"] is True
    assert staff.get("/api/daily/lines").json()["checks"][number]["current"] is True

    # A master changes and the invoice is recalculated: a NEW working, the
    # old one stays as history, and the check is now of the earlier working.
    relink(settings, '14" WHEEL CUPS', "Underbody")
    recalc(staff, [number])
    view = show(staff, number)
    assert [h["why"] for h in view["history"]] == ["Recalculated", "Posted"]
    assert view["working"]["incentive"]["payable"] > 0
    assert view["check"]["current"] is False
    # Check again, then take the check off.
    assert staff.post(f"/api/daily/working/{number}/check", headers=H,
                      json={"checked": True}).json()["check"]["current"] is True
    assert staff.post(f"/api/daily/working/{number}/check", headers=H,
                      json={"checked": False}).json()["check"] is None
    log = [e["field"] for e in staff.get("/api/daily/log").json()["entries"]]
    assert log.count("Working checked") == 2 and "Check removed" in log
    # Recalculate that changes nothing does not add a copy of the same working.
    recalc(staff, [number])
    assert len(show(staff, number)["history"]) == 2


def _forget_workings(settings, numbers):
    """As if the invoices had been posted before v0.37.0."""
    conn = connect(settings.db_path)
    with conn:
        for n in numbers:
            conn.execute("DELETE FROM payout_workings WHERE invoice_no = ?", (n,))
    conn.close()


def test_rebuilding_the_working_of_an_older_invoice(world):
    settings, _, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    _forget_workings(settings, ["DNS26-GST-0753", "DNS-237-2627"])
    view = show(staff, "DNS26-GST-0753")
    assert view["working"] is None and view["rebuildable"] is True
    # Nothing to download until it is made.
    assert staff.get("/api/daily/working/DNS26-GST-0753/file?format=xlsx").status_code == 400
    made = staff.post("/api/daily/working/DNS26-GST-0753/rebuild", headers=H)
    assert made.status_code == 200, made.text
    assert made.json()["history"][0]["why"].startswith("Rebuilt")
    assert staff.post("/api/daily/working/DNS26-GST-0753/rebuild",
                      headers=H).status_code == 400              # already there
    # The masters changed since DNS-237 was posted: refused, nothing saved.
    relink(settings, '14" WHEEL CUPS', "Underbody")
    refused = staff.post("/api/daily/working/DNS-237-2627/rebuild", headers=H)
    assert refused.status_code == 400 and "Recalculate" in refused.json()["detail"]
    assert show(staff, "DNS-237-2627")["working"] is None
    # Recalculate brings it up to date and saves its working with it.
    recalc(staff, ["DNS-237-2627"])
    assert show(staff, "DNS-237-2627")["history"][0]["why"] == "Recalculated"


def test_downloads(world):
    _, _, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    one = staff.get("/api/daily/working/DNS26-GST-0753/file?format=xlsx")
    assert one.status_code == 200
    assert "Working_DNS26-GST-0753.xlsx" in one.headers["content-disposition"]
    text = " ".join(str(c.value) for row in load_workbook(io.BytesIO(one.content)).active.iter_rows()
                    for c in row if c.value is not None)
    for words in ("Invoice DNS26-GST-0753", "Labour - Floor mat", "Spot incentive payable",
                  "Checked by"):
        assert words in text
    assert staff.get("/api/daily/working/DNS26-GST-0753/file?format=doc").status_code == 400
    if pdf_possible():
        pdf = staff.get("/api/daily/working/DNS26-GST-0753/file?format=pdf")
        assert pdf.status_code == 200, pdf.text
        assert pdf.content.startswith(b"%PDF")

    # A date range: every posted invoice dated in it.
    posted = lines(staff)
    dates = sorted({l["invoice_date"] for l in posted.values()})
    reply = staff.get("/api/daily/workings/export",
                      params={"date_from": dates[0], "date_to": dates[-1]})
    assert reply.status_code == 200, reply.text
    wb = load_workbook(io.BytesIO(reply.content))
    assert wb.sheetnames == ["Invoices", "Items", "Read me"]
    ws = wb["Invoices"]
    head = [c.value for c in ws[1]]
    rows = [dict(zip(head, [c.value for c in r])) for r in ws.iter_rows(min_row=2)
            if r[0].value and r[0].value != "Total"]
    assert sorted(r["Invoice no"] for r in rows) == sorted(INVOICES)
    for r in rows:
        assert str(r["Incentive (check)"]).startswith("=ROUND(")        # her own formula
        mine = [l for l in posted.values() if l["invoice_no"] == r["Invoice no"]]
        assert r["Incentive posted"] == round(sum(l["amount"] for l in mine
                                                  if l["type"] == "Spot incentive"), 2)
        assert r["Labour posted"] == round(sum(r[k] for k in ("Labour - Floor mat",
                                           "Labour - Sunfilm", "Labour - Other")), 2)
    assert wb["Items"].max_row - 1 == sum(len(show(staff, n)["working"]["items"])
                                          for n in INVOICES)
    # range rules
    assert staff.get("/api/daily/workings/export",
                     params={"date_from": "2026-09-10", "date_to": "2026-09-01"}).status_code == 400
    assert staff.get("/api/daily/workings/export",
                     params={"date_from": "2020-01-01"}).status_code == 400   # none dated then


def test_clearing_the_register_clears_workings_and_checks(world):
    settings, admin, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    staff.post("/api/daily/working/DNS-226-2627/check", headers=H, json={"checked": True})
    admin.post("/api/daily/clear", json={"confirm": "CLEAR"}, headers=H)
    conn = connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM payout_workings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM payout_checks").fetchone()[0] == 0
    conn.close()

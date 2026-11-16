"""
test_web_recalculate.py - Recalculate on the Payouts screen (v0.35.0)
====================================================================

A posted invoice is never calculated again by a scan (its PDF has not
changed), so a product linked to its incentive group later, or a changed
rule, needs Recalculate. Checked here, through the web addresses:

    * an item linked late: Recalculate adds the spot incentive line
    * an unpaid line whose amount changes is corrected in place
    * a PAID line is never changed - it is named in the warnings
    * "every invoice with unpaid lines" covers exactly those invoices
    * only posted invoices can be recalculated; every change is logged
"""

from datetime import date

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("itsdangerous")

from app.data.database import connect                         # noqa: E402
from app.data.masters_repo import MastersRepo, RowChange      # noqa: E402
from tests.test_web_auth import H                             # noqa: E402
from tests.test_web_daily import TODAY, lines, scan, september, world   # noqa: E402,F401


def relink(settings, product: str, group: str) -> None:
    """Set a product's incentive group, as on Masters -> Products."""
    conn = connect(settings.db_path)
    repo = MastersRepo(conn, "admin")
    row = next(p for p in repo.list_rows("products") if p["name"] == product)
    values = {k: v for k, v in row.items() if k not in ("id",)}
    values["incentive_group"] = group
    repo.save("products", [RowChange(row["id"], values, date(2026, 4, 1))])
    conn.close()


def recalc(client, invoices=(), all_unpaid=False, expect=200):
    reply = client.post("/api/daily/recalculate", headers=H,
                        json={"invoice_nos": list(invoices), "all_unpaid": all_unpaid})
    assert reply.status_code == expect, reply.text
    return reply.json()


def test_recalculate_adds_corrects_and_never_touches_paid_lines(world):
    settings, admin, staff, drawer = world
    september(drawer, staff)
    scan(staff)
    assert "DNS-237-2627-INC" not in lines(staff)          # wheel cups: no incentive yet
    # One incentive is paid before the masters change.
    paid = staff.post("/api/daily/pay", headers=H, json={
        "line_ids": ["DNS26-GST-0753-INC"], "paid_date": TODAY, "mode": "Cash",
        "reference": "V-1"})
    assert paid.status_code == 200, paid.text
    before = lines(staff)

    # The masters change: wheel cups and the side/rear sunfilm now earn incentive,
    # and so does the silencer on the PAID invoice.
    relink(settings, '14" WHEEL CUPS', "Underbody")
    relink(settings, "Sunfilm - Nano Ceramic - Side and Rear (SK)", "Sunfilm")
    relink(settings, "Silencer Coating - All Cars", "Underbody")

    # A scan alone changes nothing: the PDFs are the same.
    september(drawer, staff)
    assert scan(staff)["tally"]["already posted"] == 3
    assert lines(staff) == before                            # same lines, same amounts

    # Every invoice with unpaid lines: all three still have unpaid labour.
    assert sorted(staff.get("/api/daily/recalculate").json()["unpaid_invoices"]) == [
        "DNS-226-2627", "DNS-237-2627", "DNS26-GST-0753"]
    report = recalc(staff, all_unpaid=True)
    assert report["recalculated"] == 3
    after = lines(staff)
    # newly due: the spot incentive of DNS-237
    assert after["DNS-237-2627-INC"]["status"] == "Pending"
    assert after["DNS-237-2627-INC"]["amount"] > 0
    assert [l["line_id"] for l in report["posted"]] == ["DNS-237-2627-INC"]
    # corrected in place: DNS-226's incentive (side/rear sunfilm now counts)
    assert after["DNS-226-2627-INC"]["amount"] > before["DNS-226-2627-INC"]["amount"]
    assert after["DNS-226-2627-INC"]["status"] == "Pending"
    # the PAID line is exactly as it was, and is named
    assert after["DNS26-GST-0753-INC"] == before["DNS26-GST-0753-INC"]
    assert after["DNS26-GST-0753-INC"]["status"] == "Paid"
    assert any(w.startswith("DNS26-GST-0753-INC is already paid") for w in report["warnings"])
    assert {c["invoice_no"] for c in report["changes"]} == {"DNS-226-2627", "DNS-237-2627"}
    # logged with who did it
    log = staff.get("/api/daily/log?text=Recalculated").json()["entries"]
    assert any("DNS-237-2627-INC" in str(e) for e in log)

    # A second time: nothing more to do.
    again = recalc(staff, ["DNS-226-2627", "DNS-237-2627"])
    assert again["changes"] == [] and again["posted"] == []


def test_only_posted_invoices_can_be_recalculated(world):
    _, _, staff, drawer = world
    assert "Choose the invoices" in recalc(staff, [], expect=400)["detail"]
    september(drawer, staff)
    scan(staff)
    assert "Only posted invoices" in recalc(staff, ["DNS-999-2627"], expect=400)["detail"]

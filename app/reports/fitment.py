"""
fitment.py - Floor mat and sunfilm figures against the cars delivered (v0.33.0)
==============================================================================

WHAT THIS MODULE DOES
---------------------
The client asked (via Brinda, 10-11-2026) for these figures every month:

    Total number of cars delivered
    Full floor mat:  OE full mat      - qty - % of cars delivered
                     non-OE full mat  - qty - % of cars delivered
    Sunfilm:         side and rear    - qty - % of cars delivered
                     front            - qty - % of cars delivered

`fitments(link)` works them out from the delivery list joined to the
month's invoices (rto_reports.Linked) and returns one row per line:

    Particulars                       Cars   % of cars delivered   Qty
    Full floor mat - OE (dealer)        32        14.6%              32
    Full floor mat - DNS                20         9.1%              21
    Sunfilm side & rear - DNS           22        10.0%              22
    Sunfilm front - DNS                 16         7.3%              16
                                     (October 2026)

"Cars" counts each delivered car once, however many it took; "Qty" adds the
quantities on those cars. The % is of the cars delivered this month.
(Brinda chose the defaults, 10-11-2026: only this month's delivered cars,
cars not quantity for the %.)

WHERE EACH FIGURE COMES FROM
----------------------------
    OE full mat     the DEALER's accessory lines for the car (Car Sales
                    Report, "Part Wise" and counter-sale sheets -
                    RtoCar.oe_parts): a part whose name has "FULL FLOOR MAT"
                    ("FULL FLOOR MAT", "FULL FLOOR MAT - NIOS & AURA"). 3D
                    mats, cabin mats, dual-layer mats and boot mats are not
                    full floor mats and are not counted. An older RTO list
                    without those sheets is read from its "OE Accessories
                    List" text instead.
    DNS full mat    Drive N Style's invoice lines for the car (linked by the
                    VIN) whose product name has "full floor mat" (the "PVC
                    Full Floor Mat" items).
    Sunfilm         invoice lines whose product name has "sunfilm" / "sun
                    film" and
                      "side" or "rear"         -> side and rear
                      "front" or "windshield"  -> front
                    A roll (no side / front in the name) is neither.
    Lines whose name STARTS with "Labour" are labour charges, not a product
    fitted, and are never counted ("Labour Charges for Sunfilm - Front").

The words live only in this module (RULES) so they are changed in one place.
Sales are not changed by any of this: it only counts.

No database and no Qt code here.
"""

from __future__ import annotations

from app.data.rto_list import RtoCar

# key, label, where (OE = the dealer's parts, DNS = Drive N Style's invoices)
ROWS = (
    ("oe_mat", "Full floor mat – OE (dealer)"),
    ("dns_mat", "Full floor mat – DNS"),
    ("film_side", "Sunfilm side & rear – DNS"),
    ("film_front", "Sunfilm front – DNS"),
)
KEYS = tuple(k for k, _ in ROWS)


def oe_full_mat(part: str) -> bool:
    """A dealer part that is a full floor mat."""
    return "FULL FLOOR MAT" in " ".join(str(part or "").upper().split())


def dns_kind(product: str) -> str | None:
    """Which of the DNS figures an invoice line belongs to, or None."""
    name = " ".join(str(product or "").lower().split())
    if not name or name.startswith("labour") or name.startswith("labor"):
        return None
    if "full floor mat" in name:
        return "dns_mat"
    if "sunfilm" in name or "sun film" in name:
        if "side" in name or "rear" in name:
            return "film_side"
        if "front" in name or "windshield" in name or "wind shield" in name:
            return "film_front"
    return None


def car_fitments(car: RtoCar, invoices: list) -> dict[str, float]:
    """key -> quantity fitted on this car (only the keys it took)."""
    out: dict[str, float] = {}
    oe = sum(q for part, q in car.oe_parts.items() if oe_full_mat(part))
    if not oe and not car.oe_parts and oe_full_mat(car.oe_list):
        oe = 1.0                     # an RTO list's text, no quantities in it
    if oe:
        out["oe_mat"] = oe
    for inv in invoices:
        for line in inv.lines:
            kind = dns_kind(line.product)
            if kind:
                out[kind] = round(out.get(kind, 0.0) + line.qty, 2)
    return out


def fitments(link) -> list[dict]:
    """The four lines for the month (see module notes). `link` is
    rto_reports.Linked - not imported here, as rto_reports imports this."""
    cars = len(link.cars)
    rows = {k: dict(key=k, name=label, cars=0, qty=0.0, delivered=cars) for k, label in ROWS}
    for car in link.cars:
        for key, qty in car_fitments(car, link.invoices(car)).items():
            rows[key]["cars"] += 1
            rows[key]["qty"] = round(rows[key]["qty"] + qty, 2)
    for r in rows.values():
        r["pct"] = r["cars"] / cars if cars else ""
    return [rows[k] for k in KEYS]


def counts(link) -> dict[str, int]:
    """key -> cars, kept per month for the trend (inputs_repo.save_rto_month)."""
    return {r["key"]: r["cars"] for r in fitments(link)}

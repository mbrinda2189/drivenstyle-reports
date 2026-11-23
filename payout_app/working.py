"""
working.py - "Show working": how each payout amount of an invoice was reached
=============================================================================

WHY THIS EXISTS (v0.37.0)
-------------------------
The client's staff check the daily payouts by hand. Each payout line
already carries a one-line "Working" text (engine.py), but that is too
short to check an invoice against its PDF. Brinda (23-11-2026) asked for a
full breakdown, per invoice, for BOTH labour and incentive, shown on the
screen, downloadable as a one-page PDF / Excel for one invoice, and as an
Excel sheet for a day or a date range.

WHAT THIS MODULE DOES
---------------------
`invoice_working(inv, lines)` turns ONE calculated invoice into a plain
dictionary (only text, numbers, lists - so it can be stored in the
database as JSON and sent to the browser as it is):

    1. what was read      invoice no, date, customer, car, sales executive
                          as printed and as matched, invoice total
    2. items              every item line: name as printed, the master
                          product it was read as, qty, typed price, its
                          share of the discount, what the customer paid,
                          the fixed price and where it came from, labour
                          rate, incentive, and the master rate rows used
                          (their "effective from" dates)
    3. labour             per kind of work (Floor mat / Sunfilm / Other):
                          rate x qty per item, the total = the payout line
    4. spot incentive     every incentive x qty, the package (if any), the
                          full incentive, paid vs fixed prices, the ratio,
                          the formula with the invoice's own numbers, the
                          amount payable = the payout line
    5. internal team      internal incentive x qty per item
    6. lines              the payout lines this invoice gave (ID, type,
                          payee, amount) - the figures the steps must reach

IT CALCULATES NOTHING NEW. Every figure is read from the monthly tool's own
objects (app/reports/data.py: Invoice, Line, PackageSale) that engine.py
used for the amounts. The totals here are those objects' own properties
(inv.labour, inv.full_incentive, inv.incentive_ratio ...), so the working
can never disagree with the amount that was posted.

WHEN IT IS MADE AND KEPT
------------------------
engine.calculate attaches it to every invoice it can calculate
(InvoiceResult.working). web/backend/payout_store.py stores it when the
invoice is Posted, Re-issued or Recalculated - so the working shown later
is the one the posted amounts came from, even if a master changes after.

`FORMAT` is stored with each working; a later version that changes the
shape of the dictionary raises it, and the screens can still show older
ones.
"""

from __future__ import annotations

from datetime import date

from app.data.masters_repo import name_key
from app.reports.data import BILL_VALUE, SELLING_PRICE, TYPED, labour_group

FORMAT = 1

# How the fixed price was found, in the words the screen shows.
FIXED_SOURCE_TEXT = {
    BILL_VALUE: "Bill value (Incentive master)",
    SELLING_PRICE: "Selling price (Product master)",
    TYPED: "Price typed on the invoice (no fixed price in the masters)",
}


def _day(value) -> str:
    """A date as "YYYY-MM-DD" text ("" for none) - JSON has no dates."""
    return value.isoformat() if isinstance(value, date) else (str(value) if value else "")


def _r(value: float) -> float:
    """Money to the paisa, the same as everywhere in the tool."""
    return round(float(value or 0.0), 2)


def _matched_how(printed: str, product: str) -> str:
    """
    "Same name" when the printed name is the master product's name (spaces
    and capitals ignored, the monthly tool's own rule); otherwise the name
    was read through a saved match made on Review / Scan review.
    """
    if not printed or name_key(printed) == name_key(product):
        return "Same name"
    return "Saved match"


def _item(l) -> dict:
    """One invoice line (data.Line) with everything the working shows of it."""
    has_labour = l.labour > 0
    return {
        "printed": l.printed or l.product,
        "product": l.product,
        "matched": _matched_how(l.printed, l.product),
        "category": l.category,
        "qty": l.qty,
        # what was typed, GST-inclusive, before discount
        "typed_unit": _r(l.typed_unit),
        "typed": _r(l.typed),
        # what the customer paid for the line: after its share of the
        # discount, WITH GST (data.Line.billed = sales + gst)
        "discount": _r(l.discount),
        "paid": _r(l.billed),
        # the fixed price rule (v0.35.0)
        "fixed_price": _r(l.fixed_price),
        "fixed_source": l.fixed_source,
        "fixed_source_text": FIXED_SOURCE_TEXT.get(l.fixed_source, ""),
        "fixed_value": _r(l.fixed_value),
        "in_package": bool(l.is_package),
        # labour
        "labour_kind": labour_group(l.product) if has_labour else "",
        "labour_rate": _r(l.labour_rate),
        "labour": _r(l.labour),
        "rate_from": _day(l.rate_from),
        # spot incentive (0 inside a package or for "Gets incentive = No")
        "incentive_group": l.incentive_group,
        "incentive_rate": _r(l.incentive_amount),
        "incentive": _r(l.incentive_amount * l.qty) if l.incentive_group else 0.0,
        "incentive_from": _day(l.incentive_from) if l.incentive_group else "",
        # internal team
        "internal_rate": _r(l.internal_incentive),
        "internal": _r(l.internal_incentive * l.qty),
    }


def _num(value: float) -> str:
    """1 -> "1", 1.5 -> "1.5", 1500 -> "1,500" (rates and quantities in sentences)."""
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _money(value: float) -> str:
    """Indian grouping, two decimals: 123456.5 -> "1,23,456.50"."""
    whole, paise = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if value < 0 else "") + whole + "." + paise


def invoice_working(inv, lines) -> dict:
    """
    The full working of one calculated invoice (see the module notes).
    `inv`   data.Invoice, as engine.calculate got it from build_month
    `lines` the engine.PayoutLine objects made for it
    """
    items = [_item(l) for l in inv.lines]

    # ---- labour, by kind of work - the same grouping as engine.calculate ----
    labour = []
    for kind in ("Floor mat", "Sunfilm", "Other"):
        work = [i for i in items if i["labour"] > 0 and i["labour_kind"] == kind]
        if work:
            labour.append({
                "kind": kind,
                "items": [{"product": i["product"], "rate": i["labour_rate"], "qty": i["qty"],
                           "amount": i["labour"], "rate_from": i["rate_from"]} for i in work],
                "total": _r(sum(i["labour"] for i in work))})

    # ---- spot incentive (data.Invoice, v0.35.0 rule) ---------------------------
    k = inv.package
    package = None
    if k:
        package = {"name": k.package, "incentive": _r(k.incentive),
                   "coupon_value": _r(k.coupon_value), "rate_from": _day(k.rate_from),
                   "items": [l.product for l in k.lines],
                   "items_fixed_value": _r(sum(l.fixed_value for l in k.lines))}
    paid, fixed, ratio = _r(inv.paid_total), _r(inv.fixed_total), inv.incentive_ratio
    full, payable = _r(inv.full_incentive), _r(inv.incentive_payable)
    steps = []
    if not inv.incentive_allowed:
        steps.append(f"{inv.executive} is marked “Gets incentive = No” in the Sales "
                     "executive master, so this invoice carries no spot incentive.")
    else:
        parts = [f"{i['incentive_group']} {_num(i['incentive_rate'])} x {_num(i['qty'])} = "
                 f"{_money(i['incentive'])}" for i in items if i["incentive"]]
        if package and package["incentive"]:
            parts.append(f"{package['name']} (package) = {_money(package['incentive'])}")
        if parts:
            steps.append("Full incentive: " + "; ".join(parts) + f". Total {_money(full)}.")
        else:
            steps.append("No item on this invoice carries a spot incentive.")
        steps.append(f"Customer paid {_money(paid)} for the items; their fixed prices add up "
                     f"to {_money(fixed)}.")
        if fixed <= 0:
            steps.append("There are no fixed prices, so the full incentive is earned.")
        elif ratio >= 1:
            steps.append("Paid is not less than the fixed prices, so the FULL incentive is "
                         "earned (the share is capped at 100%).")
        else:
            steps.append(f"Paid is less than the fixed prices: share earned = "
                         f"{_money(paid)} / {_money(fixed)} = {ratio * 100:.2f}%.")
        if full:
            if ratio >= 1:
                steps.append(f"Incentive payable = {_money(full)} x 100% = {_money(payable)}.")
            else:
                steps.append(f"Incentive payable = {_money(full)} x {_money(paid)} / "
                             f"{_money(fixed)} = {_money(payable)}.")
        steps.append("Not rounded here: rounding up to the next ₹10 is done once on each "
                     "executive's month total in the monthly report.")
    payee = inv.executive
    if inv.printed_executive:
        payee = f"{inv.executive} ({inv.printed_executive})"

    internal = [{"product": i["product"], "rate": i["internal_rate"], "qty": i["qty"],
                 "amount": i["internal"]} for i in items if i["internal"]]

    return {
        "format": FORMAT,
        "invoice_no": inv.invoice_no,
        "invoice_date": _day(inv.invoice_date),
        "customer": inv.customer,
        "car": inv.printed_car or inv.car,
        "executive": inv.executive,
        "printed_executive": inv.printed_executive,
        "branch": inv.branch,
        "total": _r(inv.total),
        "discount": _r(inv.discount),
        "gst": _r(inv.gst),
        "rounding": _r(inv.rounding),
        "markers": inv.markers,
        "marker_value": _r(inv.marker_value),
        "items": items,
        "labour": {"groups": labour, "total": _r(inv.labour)},
        "incentive": {
            "payee": payee, "allowed": inv.incentive_allowed,
            "items": [{"product": i["product"], "group": i["incentive_group"],
                       "rate": i["incentive_rate"], "qty": i["qty"], "amount": i["incentive"],
                       "rate_from": i["incentive_from"]} for i in items if i["incentive"]],
            "package": package, "full": full, "paid": paid, "fixed": fixed,
            "ratio": round(ratio, 6), "payable": payable, "steps": steps},
        "internal": {"items": internal, "total": _r(inv.internal_incentive)},
        "lines": [{"line_id": l.line_id, "type": l.type, "payee": l.payee,
                   "amount": _r(l.amount)} for l in lines],
    }


def lines_total(work: dict) -> float:
    """What all the payout lines of a working add up to."""
    return _r(sum(l["amount"] for l in work.get("lines", [])))

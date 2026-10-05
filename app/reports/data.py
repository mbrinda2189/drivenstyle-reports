"""
data.py - Every figure the reports need, for one month
======================================================

WHAT THIS MODULE DOES
---------------------
`build_month(masters, invoices, inputs, year, month)` returns a
`MonthData` with the month's invoices and their lines, ready for the
report sheets. It changes nothing in the database.

WHICH INVOICES ARE INCLUDED
---------------------------
Every invoice read for the month, EXCEPT those with an open issue on Scan
review (item not in the Product master, salesperson or car not matched,
labour note, totals difference). Those are listed on the "Not included"
sheet with their amounts and reasons, so
    included + not included = every invoice read.
(Confirmed with the client: a partly-known invoice would make the reports
disagree with each other.)

HOW EACH LINE IS VALUED
-----------------------
    sales        the line's value after its share of the invoice discount,
                 WITHOUT GST (worked out at scan time, invoices_repo.py).
                 Invoices with no GST shown count in full as sales.
    product cost Product master cost price x quantity, at the rate that
                 applied on the invoice date (masters are GST-exclusive)
    labour cost  Product master labour charge x quantity, for products
                 marked "Labour involved" (what Drive N Style pays for the
                 labour)
    gross profit sales - product cost - labour cost
The Rs. 1 "Labour Charges for ..." / "Labour - ..." lines are IGNORED
(v0.6.3, confirmed by the client): they only show that labour was done.
Labour is worked out from the product (Labour involved + labour charge in
the Product master), never from these lines. Their small value (about
Rs. 0.85 each after discount and GST) is left out of sales, so report sales
are slightly below the invoice totals; the count and value are kept on the
invoice (`markers`, `marker_value`) and shown on the cover sheet.

INCENTIVES (report 7 - rule confirmed by the client on 30-09-2026)
-----------------------------------------------------------------
For a product linked to an incentive group, the group's incentive amount
and bill value that applied on the invoice date are attached to the line,
with `billed` = the line's value after discount INCLUDING GST (what the
customer paid for it). The workbook applies the client's rule
    payable = incentive x qty x min(1, billed / (bill value x qty))
i.e. the incentive falls in proportion to any discount below the bill
value, and is never more than the full incentive.

PACKAGES (report 5)
-------------------
From v0.8.0 a package is recognised from the invoice: every item of the
package (Packages master) must be on it - see app/reports/packages.py.
The lines that make up the package are marked `is_package`, lose their own
item incentive, and the invoice gets ONE package incentive instead
(Incentive master row with the package's name: incentive amount and bill
value = the coupon's final value). The confirmed discount rule applies to
it the same way: incentive x min(1, amount billed for the package items /
coupon final value). Lines outside the package keep their own incentive.
(Until v0.7.1 a line was a package when its product's incentive group name
contained "Package"; no product is billed like that.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from app.data.inputs_repo import AUTO_HEADS, InputsRepo
from app.data.invoices_repo import (
    OTHERS, OTHERS_ID, InvoicesRepo, month_key, month_label, split_salesperson)
from app.data.masters_repo import MastersRepo
from app.reports import packages as pk

COUNTER_SALE = "Counter sale (no vehicle)"


def segment_group(segment: str) -> str:
    """
    Segment as shown in "Vehicle-wise - By segment" (v0.20.0, Brinda,
    05-10-2026): counter sales (no vehicle) and cars with no segment in the
    Car master are counted in the one line "Others", together with the
    invoices whose car was marked "Others" on Scan review.
    """
    return OTHERS if not segment or segment == COUNTER_SALE else segment


# Labour calculation is shown as separate tables (v0.20.0): one for floor
# mats, one for sunfilm. The table is picked from the item name; an item
# with labour that is neither goes to "Other" so the total still agrees.
LABOUR_GROUPS = ("Floor mat", "Sunfilm", "Other")


def labour_group(product: str) -> str:
    name = (product or "").lower()
    if "sunfilm" in name or "sun film" in name:
        return "Sunfilm"
    if "floor mat" in name or "floormat" in name:
        return "Floor mat"
    return "Other"

# AUTOMATIC INDIRECT COSTS (v0.8.1)
# ---------------------------------
# Brinda, 03-10-2026: every month two indirect expenses are not entered by
# hand but worked out from the month's COGS, where
#     COGS = product cost + labour   (the "Total direct costs" of the P&L)
#   * Breakage / returns / transport = 4% of COGS
#   * Compliance GST                 = 3% of COGS
# They apply to every month (earlier months too, when generated again).
# (label, share of COGS, word that marks the same head typed on Monthly
# inputs - a typed head with that word is left out so it is not counted
# twice.) These are the defaults; from v0.8.2 the percentages in force are
# the ones set on Monthly inputs (inputs_repo.auto_rates), put on
# MonthData.auto_rates by build_month.
#
# v0.20.0 (Brinda, 05-10-2026): the two percentages are taken on the PRODUCT
# COST ONLY, not on product cost + labour - see MonthData.auto_base. This
# again applies to every month when it is generated again.
AUTO_INDIRECT = tuple((head, pct / 100, word) for _, head, pct, word in AUTO_HEADS)


def round_up_10(amount: float) -> float:
    """
    v0.12.1 (Brinda, 04-10-2026): an executive's incentive for the month is
    rounded UP to the next 10 rupees - 1,492 becomes 1,500 and 2,677.80
    becomes 2,680. An exact multiple of 10 stays as it is. The rounding is
    done ONCE on the executive's total, not on each invoice line.
    """
    return float(math.ceil(round(amount, 2) / 10 - 1e-9) * 10)


@dataclass
class Line:
    """One invoice line, valued."""
    invoice_no: str
    invoice_date: date
    executive: str
    branch: str
    car: str
    segment: str
    product: str                  # master name (or printed text for labour lines)
    category: str                 # Product / Service
    qty: float
    sales: float                  # after discount, before GST
    discount: float
    gst: float
    cost: float
    labour: float
    labour_rate: float = 0.0      # per unit, from the master
    incentive_group: str = ""
    incentive_amount: float = 0.0   # per unit
    bill_value: float = 0.0         # per unit
    is_package: bool = False        # part of a package sale (v0.8.0)
    list_price: float = 0.0         # per unit, Product master (Zoho's rate)
    internal_incentive: float = 0.0  # per unit, to the internal team (v0.12.0)

    @property
    def billed(self) -> float:
        """What the customer paid for this line (after discount, with GST)."""
        return round(self.sales + self.gst, 2)

    @property
    def gross_profit(self) -> float:
        return round(self.sales - self.cost - self.labour, 2)


@dataclass
class PackageSale:
    """A package recognised on one invoice (v0.8.0)."""
    package: str
    incentive: float              # Incentive master, on the invoice date
    coupon_value: float           # its Bill value = the coupon's final value
    lines: list[Line] = field(default_factory=list)

    def _sum(self, attr: str) -> float:
        return round(sum(getattr(l, attr) for l in self.lines), 2)

    @property
    def list_value(self) -> float:
        return round(sum(l.list_price * l.qty for l in self.lines), 2)

    @property
    def sales(self) -> float:
        return self._sum("sales")

    @property
    def billed(self) -> float:
        return self._sum("billed")

    @property
    def cost(self) -> float:
        return self._sum("cost")

    @property
    def labour(self) -> float:
        return self._sum("labour")


@dataclass
class Invoice:
    invoice_no: str
    invoice_date: date
    customer: str
    customer_type: str
    executive: str
    branch: str
    car: str
    segment: str
    discount: float
    gst: float
    rounding: float
    total: float
    payment_mode: str             # printed on the invoice, if any
    payment_made: float
    lines: list[Line] = field(default_factory=list)
    markers: int = 0              # Rs. 1 labour marker lines ignored
    marker_value: float = 0.0     # their value (after discount, before GST)
    # v0.7.1: set when the salesperson / car was fixed as "Others" on Scan
    # review - the text printed on the invoice, shown in the Invoice register.
    printed_executive: str = ""
    printed_car: str = ""
    incentive_allowed: bool = True   # False: executive marked "Gets incentive = No"
    vin: str = ""                 # Zoho's VIN / registration field (v0.9.0:
                                  # links the invoice to the delivery list)
    package: PackageSale | None = None      # v0.8.0
    near_package: str = ""                  # "almost a package": its name ...
    near_missing: str = ""                  # ... and the one item missing

    @property
    def sales(self) -> float:
        return round(sum(l.sales for l in self.lines), 2)

    @property
    def incentive_payable(self) -> float:
        """
        Spot incentive for this invoice by the confirmed rule (the same
        figure the Spot incentive sheet works out with Excel formulas):
        incentive x qty x min(1, billed / (bill value x qty)) per line with
        an incentive group, plus the package incentive if a package was sold.
        """
        total = 0.0
        for l in self.lines:
            base = l.bill_value * l.qty
            if l.incentive_group and base:
                total += l.incentive_amount * l.qty * min(1.0, l.billed / base)
        k = self.package
        if k and k.coupon_value:
            total += k.incentive * min(1.0, k.billed / k.coupon_value)
        return round(total, 2)

    @property
    def internal_incentive(self) -> float:
        """
        Internal team incentive on this invoice (v0.12.0): the product's
        "Internal incentive" x quantity - in full whatever the discount, in
        addition to the salesperson's incentive, also for items inside a
        package, and whoever the salesperson is.
        """
        return round(sum(l.internal_incentive * l.qty for l in self.lines), 2)

    @property
    def cost(self) -> float:
        return round(sum(l.cost for l in self.lines), 2)

    @property
    def labour(self) -> float:
        return round(sum(l.labour for l in self.lines), 2)

    @property
    def gross_profit(self) -> float:
        return round(self.sales - self.cost - self.labour, 2)

    @property
    def items(self) -> float:
        return sum(l.qty for l in self.lines)


@dataclass
class LeftOut:
    invoice_no: str
    invoice_date: date
    customer: str
    total: float
    reasons: list[str]


@dataclass
class MonthData:
    year: int
    month: int
    invoices: list[Invoice]
    left_out: list[LeftOut]
    skipped_files: list[dict]              # file_name, reason
    indirect_costs: list[tuple[str, float]]
    threshold: float                       # high-profit margin %
    has_inputs: bool                       # indirect costs were entered
    auto_rates: tuple = AUTO_INDIRECT      # (head, share of COGS, word)

    @property
    def label(self) -> str:
        return month_label(self.year, self.month)

    @property
    def lines(self) -> list[Line]:
        return [l for inv in self.invoices for l in inv.lines]

    @property
    def sales(self) -> float:
        return round(sum(i.sales for i in self.invoices), 2)

    @property
    def cogs(self) -> float:
        """Product cost + labour of the included invoices."""
        return round(sum(i.cost + i.labour for i in self.invoices), 2)

    @property
    def auto_base(self) -> float:
        """
        The amount the automatic indirect costs are a percentage of: the
        month's PRODUCT COST only (v0.20.0; it was product cost + labour
        before - Brinda, 05-10-2026).
        """
        return round(sum(i.cost for i in self.invoices), 2)

    @property
    def auto_indirect(self) -> list[tuple[str, float, float]]:
        """(head, share of product cost, amount) - see AUTO_INDIRECT."""
        return [(head, pct, round(self.auto_base * pct, 2))
                for head, pct, _ in self.auto_rates]

    @property
    def direct_incentives(self) -> list[tuple[str, float]]:
        """
        v0.20.0: the "Incentives" head typed on Monthly inputs is shown under
        DIRECT costs in the Profit & loss and Indirect vs direct statements
        (Brinda, 05-10-2026), so gross profit there is after incentives. Any
        typed head with the word "incentive" counts. Net profit is the same
        as before - the amount only moves from one block to the other.
        NOTE: the other reports (branches, products, vehicles, summary) keep
        gross profit = sales - product cost - labour, because the incentive
        is one figure for the month and cannot be split by product or branch.
        """
        return [(h, a) for h, a in self.entered_indirect if "incentive" in h.lower()]

    @property
    def other_indirect(self) -> list[tuple[str, float]]:
        """Typed indirect heads without the incentive head(s) above."""
        return [(h, a) for h, a in self.entered_indirect if "incentive" not in h.lower()]

    @property
    def entered_indirect(self) -> list[tuple[str, float]]:
        """Heads typed on Monthly inputs, without those now automatic."""
        words = [w for _, _, w in self.auto_rates]
        return [(h, a) for h, a in self.indirect_costs
                if not any(w in h.lower() for w in words)]

    @property
    def incentive_by_executive(self) -> dict[str, float]:
        """Executive (with branch) -> spot incentive payable for the month,
        rounded up to the next Rs. 10 (see round_up_10)."""
        totals: dict[str, float] = {}
        for i in self.invoices:
            if i.incentive_payable:
                name = f"{i.executive} – {i.branch}" if i.branch else i.executive
                totals[name] = totals.get(name, 0.0) + i.incentive_payable
        return {name: round_up_10(v) for name, v in totals.items()}

    @property
    def incentive_payable(self) -> float:
        """The month's spot incentive to executives (each rounded up to Rs. 10)."""
        return round(sum(self.incentive_by_executive.values()), 2)

    @property
    def internal_incentive(self) -> float:
        """The month's internal team incentive (see Invoice.internal_incentive)."""
        return round(sum(i.internal_incentive for i in self.invoices), 2)

    @property
    def no_incentive(self) -> list[str]:
        """Executives with sales this month who are marked "Gets incentive =
        No" in the Sales executive master (v0.11.0)."""
        return sorted({f"{i.executive} – {i.branch}" if i.branch else i.executive
                       for i in self.invoices if not i.incentive_allowed})

    @property
    def marker_lines(self) -> int:
        """Rs. 1 labour marker lines ignored on the included invoices."""
        return sum(i.markers for i in self.invoices)

    @property
    def marker_value(self) -> float:
        return round(sum(i.marker_value for i in self.invoices), 2)

    @property
    def gross_profit(self) -> float:
        return round(sum(i.gross_profit for i in self.invoices), 2)


def scanned_months(invoices: InvoicesRepo) -> list[tuple[int, int]]:
    """Every month that has a scan, oldest first."""
    return [tuple(map(int, r["month"].split("-"))) for r in invoices.conn.execute(
        "SELECT month FROM scan_runs ORDER BY month")]


def build_month(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
                year: int, month: int) -> MonthData:
    """All figures for one month (see module notes)."""
    open_reasons: dict[str, list[str]] = {}
    for issue in invoices.issues(year, month):
        if issue.status == "open":
            for no in issue.invoices:
                open_reasons.setdefault(no, []).append(issue.message)

    products = {p["id"]: p for p in masters.list_rows("products")}
    execs = {e["id"]: e for e in masters.list_rows("executives")}
    cars = {c["id"]: c for c in masters.list_rows("cars")}
    incentive_ids = {i["name"]: i["id"] for i in masters.list_rows("incentives")}
    package_defs = pk.build_defs(masters.list_rows("package_items"))
    incentive_by_key = {pk.name_key(n): i for n, i in incentive_ids.items()}
    rate_cache: dict[tuple, dict | None] = {}

    def rate(master: str, row_id: int, day: date) -> dict:
        key = (master, row_id, day)
        if key not in rate_cache:
            rate_cache[key] = masters.rate_on(master, row_id, day)
        return rate_cache[key] or {}

    included, left_out = [], []
    for raw in invoices.invoices(year, month):
        day = date.fromisoformat(raw["invoice_date"])
        if raw["invoice_no"] in open_reasons:
            left_out.append(LeftOut(raw["invoice_no"], day, raw["customer"],
                                    raw["total"], open_reasons[raw["invoice_no"]]))
            continue
        ex = execs.get(raw["executive_id"], {})
        others_exec = raw["executive_id"] == OTHERS_ID
        others_car = raw["car_id"] == OTHERS_ID
        if others_exec:
            # "Others" (v0.7.1): not in the Sales executive master. The
            # branch is the one on the invoice; incentive is still worked
            # out and shown under Others.
            ex = dict(name=OTHERS, branch=(raw.get("branch") or "").strip()
                      or split_salesperson(raw.get("salesperson") or "")[1])
        # No car on an included invoice = a counter sale (every item marked
        # "Vehicle needed = No"; otherwise Scan review would have held it).
        car = cars.get(raw["car_id"]) or dict(make="", model=COUNTER_SALE,
                                               segment=COUNTER_SALE)
        if others_car:
            car = dict(make="", model=OTHERS, segment=OTHERS)
        inv = Invoice(
            raw["invoice_no"], day, raw["customer"], raw["customer_type"],
            ex.get("name", ""), ex.get("branch", ""),
            " ".join(p for p in (car.get("make", ""), car.get("model", "")) if p),
            car.get("segment", ""), raw["discount"], raw["tax_total"],
            raw["rounding"], raw["total"], raw["payment_mode"], raw["payment_made"])
        if others_exec:
            inv.printed_executive = (raw.get("salesperson") or "").strip()
        if others_car:
            inv.printed_car = (raw.get("vehicle") or "").strip()
        inv.vin = (raw.get("vin") or "").strip()
        for ln in raw["lines"]:
            common = dict(invoice_no=inv.invoice_no, invoice_date=day,
                          executive=inv.executive, branch=inv.branch, car=inv.car,
                          segment=inv.segment, qty=ln["qty"] or 1,
                          sales=ln["net_value"], discount=ln["discount_share"],
                          gst=ln["gst"])
            if ln["is_labour_marker"]:            # ignored - see module notes
                inv.markers += 1
                inv.marker_value = round(inv.marker_value + (ln["net_value"] or 0), 2)
                continue
            p = products[ln["product_id"]]
            r = rate("products", p["id"], day)
            qty = common["qty"]
            labour_rate = r.get("labour_charge", 0.0) if p["has_labour"] else 0.0
            line = Line(product=p["name"], category=p["category"],
                        cost=round(r.get("cost_price", 0.0) * qty, 2),
                        labour=round(labour_rate * qty, 2), labour_rate=labour_rate,
                        list_price=r.get("selling_price", 0.0),
                        internal_incentive=p.get("internal_incentive") or 0.0, **common)
            group = p["incentive_group"]
            if group and group in incentive_ids:
                ir = rate("incentives", incentive_ids[group], day)
                line.incentive_group = group
                line.incentive_amount = ir.get("incentive_amount", 0.0)
                line.bill_value = ir.get("bill_value", 0.0)
            inv.lines.append(line)

        # --- package (v0.8.0): every item of a package is on the invoice -----
        def package_rate(name: str) -> dict:
            iid = incentive_by_key.get(pk.name_key(name))
            return rate("incentives", iid, day) if iid else {}
        sold, near = pk.detect(package_defs, inv.lines,
                               lambda n: package_rate(n).get("bill_value", 0.0))
        if sold:
            pr = package_rate(sold.package.name)
            inv.package = PackageSale(sold.package.name,
                                      pr.get("incentive_amount", 0.0),
                                      pr.get("bill_value", 0.0), sold.lines)
            for line in sold.lines:
                # the package incentive replaces the items' own incentives
                line.is_package = True
                line.incentive_group, line.incentive_amount = "", 0.0
                line.bill_value = 0.0
        elif near:
            inv.near_package = near.package.name
            inv.near_missing = near.missing[0]

        # --- executives who do not earn spot incentive (v0.11.0) --------------
        # "Gets incentive = No" in the Sales executive master: the sale counts
        # everywhere as usual, but carries no item or package incentive.
        # ("Others" is not in the master and stays eligible.)
        if not others_exec and not ex.get("gets_incentive", True):
            inv.incentive_allowed = False
            for line in inv.lines:
                line.incentive_group, line.incentive_amount = "", 0.0
                line.bill_value = 0.0
            if inv.package:
                inv.package.incentive = 0.0
        included.append(inv)

    skipped = [f for f in invoices.scan_files(year, month) if f["status"] != "read"]
    rates = inputs.auto_rates()
    return MonthData(year, month, included, left_out, skipped,
                     inputs.costs(year, month), inputs.threshold(year, month),
                     inputs.has_inputs(year, month),
                     tuple((head, rates[key] / 100, word)
                           for key, head, _, word in AUTO_HEADS))


def trend_months(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
                 year: int, month: int, limit: int = 12) -> list[MonthData]:
    """The chosen month and up to limit-1 earlier scanned months, oldest first."""
    wanted = [m for m in scanned_months(invoices) if month_key(*m) <= month_key(year, month)]
    return [build_month(masters, invoices, inputs, y, m) for y, m in wanted[-limit:]]
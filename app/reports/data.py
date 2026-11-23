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

INCENTIVES (report 7) - WHOLE INVOICE AGAINST FIXED PRICES (v0.35.0)
-------------------------------------------------------------------
Rule confirmed by the client on 16-11-2026 (Brinda: "measure against the
fixed price", the whole invoice, not item by item):

    fixed price of a line   per unit, GST-inclusive:
                              the group's BILL VALUE (Incentive master) for
                              a product with an incentive group, else
                              the SELLING PRICE (Product master), else
                              the price typed on the invoice
                            (`Line.fixed_price`, `Line.fixed_source`)
    fixed total             the invoice's fixed prices x qty; the lines of a
                            package count at the package's own bill value
                            (the coupon's final value) instead
    paid                    what the customer paid for the lines: each line's
                            value after discount INCLUDING GST (`billed`)
    ratio                   min(1, paid / fixed total)
    incentive payable       ratio x (every item incentive x qty + the
                            package incentive)

WHY: salespeople were typing an item ABOVE its fixed price and then giving
a "discount" (estimate 515: prices raised by Rs. 4,900, discount Rs. 4,400,
customer still paid Rs. 500 more than the fixed prices). Comparing what was
actually collected with the fixed prices of the whole invoice means the
typed prices - and how a discount is spread over the lines - can no longer
change the incentive. A customer who paid the fixed prices or more earns
the full incentive; one who paid less cuts every incentive on the invoice
by the same proportion.

Until v0.34.0 each line was checked on its own:
    payable = incentive x qty x min(1, billed / (bill value x qty))
with the invoice discount spread over the lines in proportion to the TYPED
prices - which a salesperson could steer by typing the incentive item high
and another item low (same total). Paid register lines keep the amount they
were paid at; unpaid ones can be brought to the new rule with Recalculate
on the Payouts screen (payout_app/register.py).

PRICES TYPED ABOVE THE FIXED PRICE (v0.35.0)
--------------------------------------------
`MonthData.raised_prices()` lists every item typed on an invoice above its
fixed price by more than Rs. 1 (unit price as typed, GST-inclusive, minus the
fixed price, x qty) - for the "Prices above fixed price" sheet and the
internal team PDF. Items with no fixed price (neither an incentive group
with a bill value nor a selling price) are not listed.

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


# Where a line's fixed price comes from (v0.35.0)
BILL_VALUE, SELLING_PRICE, TYPED = "bill value", "selling price", "typed price"
RAISED_MIN = 1.0      # differences of Rs. 1 or less are rounding, not raised prices
PLACEHOLDER_PRICE = 1.0   # a selling price of Rs. 1 or less is a placeholder in the
                          # Product master ("Consumables - Exp", "Misc Items",
                          # "frieght" ...), not a real price: such items count at
                          # their typed price and are never "raised"


def fixed_price_for(bill_value: float, selling_price: float, typed_unit: float
                    ) -> tuple[float, str]:
    """
    The fixed price of one unit and where it comes from (v0.35.0):
    the incentive group's bill value when there is one, else the Product
    master's selling price (when above Rs. 1 - see PLACEHOLDER_PRICE), else
    the price typed on the invoice. All three
    are GST-inclusive (Brinda, 16-11-2026: selling prices in the Product
    master include GST).
    """
    if bill_value and bill_value > 0:
        return round(bill_value, 2), BILL_VALUE
    if selling_price and selling_price > PLACEHOLDER_PRICE:
        return round(selling_price, 2), SELLING_PRICE
    return round(max(typed_unit, 0.0), 2), TYPED


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
    # v0.35.0 - the fixed-price rule (see INCENTIVES in the module notes)
    typed: float = 0.0              # the line amount as typed on the invoice
                                    # (qty x rate, GST-inclusive, before discount)
    fixed_price: float = 0.0        # per unit, GST-inclusive
    fixed_source: str = ""          # "bill value" / "selling price" / "typed price"
    # v0.37.0 - kept only so the daily payouts can SHOW how a figure was
    # reached ("Show working", payout_app/working.py). No report uses them.
    printed: str = ""               # the item name exactly as printed on the invoice
    rate_from: date | None = None   # Product master rate row used (effective from)
    incentive_from: date | None = None  # Incentive master rate row used

    @property
    def typed_unit(self) -> float:
        """The unit price as typed on the invoice (GST-inclusive)."""
        return round(self.typed / self.qty, 2) if self.qty else round(self.typed, 2)

    @property
    def fixed_value(self) -> float:
        """Fixed price x quantity."""
        return round(self.fixed_price * self.qty, 2)

    @property
    def raised_by(self) -> float:
        """How much more than the fixed price was typed for this line
        (0 when typed at or below it, or when there is no fixed price)."""
        if self.fixed_source in ("", TYPED):
            return 0.0
        return round(max(0.0, self.typed - self.fixed_value), 2)

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
    rate_from: date | None = None  # v0.37.0: Incentive master row used (for "Show working")

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
    def sales_discount(self) -> float:
        """
        The discount on this invoice's lines, EXCLUDING GST (v0.32.0) - the
        same basis as sales, so sales + discount = the lines at Zoho's
        price before discount. Each line's share is stored when the invoice
        is read (invoices_repo: before tax - Item Total). It differs from
        `discount` above, which is Zoho's "Entity Discount Amount" as given
        on the invoice: tax inclusive where the invoice carries GST. On the
        October 2026 export these line shares add up to Zoho's "Discount"
        account in its Profit & Loss to the paisa. The Rs. 1 labour lines
        are not in `lines`, so their (tiny) discount is not counted - just
        as their value is not in sales.
        """
        return round(sum(l.discount for l in self.lines), 2)

    # ---- spot incentive: whole invoice against fixed prices (v0.35.0) ------
    @property
    def paid_total(self) -> float:
        """What the customer paid for the invoice's lines: every line after
        its share of the discount, INCLUDING GST (the Rs. 1 labour marker
        lines are not counted, as they are not in `lines`)."""
        return round(sum(l.billed for l in self.lines), 2)

    @property
    def fixed_total(self) -> float:
        """The invoice's fixed prices: every line's fixed price x qty, with
        the lines of a package counted at the package's bill value (the
        coupon's final value) instead of their own."""
        k = self.package
        total = sum(l.fixed_value for l in self.lines if not (k and l.is_package))
        if k:
            total += k.coupon_value if k.coupon_value else sum(l.fixed_value for l in k.lines)
        return round(total, 2)

    @property
    def incentive_ratio(self) -> float:
        """min(1, paid / fixed total) - the share of the full incentive that
        is earned. 1 when the invoice has no fixed prices at all."""
        fixed = self.fixed_total
        return 1.0 if fixed <= 0 else min(1.0, self.paid_total / fixed)

    @property
    def full_incentive(self) -> float:
        """Every item incentive x qty + the package incentive, before the
        ratio (0 for an executive marked "Gets incentive = No")."""
        total = sum(l.incentive_amount * l.qty for l in self.lines if l.incentive_group)
        if self.package:
            total += self.package.incentive
        return round(total, 2)

    @property
    def incentive_payable(self) -> float:
        """
        Spot incentive for this invoice (v0.35.0, see INCENTIVES in the
        module notes): full incentive x min(1, paid / fixed total). The
        Spot incentive sheet works out the same figure with Excel formulas.
        """
        return round(self.full_incentive * self.incentive_ratio, 2)

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
    # v0.32.0: labour as booked in Zoho for the month (from the uploaded
    # Zoho expense file), by kind - "Sunfilm" / "Floor mat" / "Other". Only
    # SHOWN beside the tool's own labour in the Profit & loss; never used
    # in any figure. Empty when no expense file was uploaded for the month.
    books_labour: dict = field(default_factory=dict)
    # v0.33.0: Zoho's cost of goods sold reports uploaded on Generate
    # (app/data/zoho_costs.ZohoCosts), or None. Only SHOWN beside the
    # master cost (sheet 18 COGS check, a block under the P&L); never used
    # in any figure. Set by reports/generate.py, not by build_month.
    zoho_costs: object = None

    @property
    def label(self) -> str:
        return month_label(self.year, self.month)

    @property
    def lines(self) -> list[Line]:
        return [l for inv in self.invoices for l in inv.lines]

    def raised_prices(self) -> list[dict]:
        """
        Every item typed above its fixed price by more than Rs. 1 (v0.35.0,
        see PRICES TYPED ABOVE THE FIXED PRICE in the module notes), one dict
        per line, sorted by executive, then the amount raised (largest first):
            executive, invoice_no, date, customer, product, qty,
            typed_unit, fixed_unit, fixed_source, raised (Rs.), raised_pct,
            has_incentive (the line carries an item incentive),
            inv_discount (the invoice's discount as printed),
            inv_paid, inv_fixed, inv_over (paid - fixed: + = the customer
            still paid at least the fixed prices)
        """
        out = []
        for inv in self.invoices:
            label = f"{inv.executive} – {inv.branch}" if inv.branch else inv.executive
            if inv.printed_executive:
                label = f"{label} ({inv.printed_executive})"
            for l in inv.lines:
                raised = l.raised_by
                if raised <= RAISED_MIN:
                    continue
                out.append(dict(
                    executive=label, invoice_no=inv.invoice_no, date=inv.invoice_date,
                    customer=inv.customer, product=l.product, qty=l.qty,
                    typed_unit=l.typed_unit, fixed_unit=l.fixed_price,
                    fixed_source=l.fixed_source, raised=raised,
                    raised_pct=round(raised / l.fixed_value, 4) if l.fixed_value else 0.0,
                    has_incentive=bool(l.incentive_group) or l.is_package,
                    inv_discount=inv.discount, inv_paid=inv.paid_total,
                    inv_fixed=inv.fixed_total,
                    inv_over=round(inv.paid_total - inv.fixed_total, 2)))
        out.sort(key=lambda r: (r["executive"], -r["raised"], r["date"], r["invoice_no"]))
        return out

    def raised_by_executive(self) -> list[dict]:
        """`raised_prices` summed per executive: invoices, items, total raised,
        and the discount printed on those invoices (each invoice once).
        Largest total raised first."""
        groups: dict[str, dict] = {}
        seen: set[tuple[str, str]] = set()
        for r in self.raised_prices():
            g = groups.setdefault(r["executive"], dict(
                executive=r["executive"], invoices=0, items=0, raised=0.0, discount=0.0))
            g["items"] += 1
            g["raised"] += r["raised"]
            if (r["executive"], r["invoice_no"]) not in seen:
                seen.add((r["executive"], r["invoice_no"]))
                g["invoices"] += 1
                g["discount"] += r["inv_discount"] or 0.0
        rows = [dict(g, raised=round(g["raised"], 2), discount=round(g["discount"], 2))
                for g in groups.values()]
        return sorted(rows, key=lambda g: (-g["raised"], g["executive"]))

    @property
    def sales(self) -> float:
        return round(sum(i.sales for i in self.invoices), 2)

    @property
    def discount(self) -> float:
        """Discount given on the included invoices, excluding GST (v0.32.0;
        see Invoice.sales_discount). Sales + discount = sales before discount."""
        return round(sum(i.sales_discount for i in self.invoices), 2)

    @property
    def labour_by_kind(self) -> dict[str, float]:
        """The tool's labour by kind (Floor mat / Sunfilm / Other), the same
        split as the Labour sheet."""
        out = {g: 0.0 for g in LABOUR_GROUPS}
        for l in self.lines:
            if l.labour:
                out[labour_group(l.product)] += l.labour
        return {g: round(v, 2) for g, v in out.items()}

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
                        internal_incentive=p.get("internal_incentive") or 0.0,
                        typed=round(ln.get("amount") or 0.0, 2),
                        printed=ln.get("description") or "",
                        rate_from=r.get("effective_from"), **common)
            group = p["incentive_group"]
            if group and group in incentive_ids:
                ir = rate("incentives", incentive_ids[group], day)
                line.incentive_group = group
                line.incentive_amount = ir.get("incentive_amount", 0.0)
                line.bill_value = ir.get("bill_value", 0.0)
                line.incentive_from = ir.get("effective_from")
            # v0.35.0: the line's fixed price, worked out HERE - before a
            # package or "Gets incentive = No" clears the incentive fields -
            # so it stays the same whoever sold the item.
            line.fixed_price, line.fixed_source = fixed_price_for(
                line.bill_value, line.list_price, line.typed_unit)
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
                                      pr.get("bill_value", 0.0), sold.lines,
                                      rate_from=pr.get("effective_from"))
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
                           for key, head, _, word in AUTO_HEADS),
                     inputs.books_labour(year, month))


def trend_months(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
                 year: int, month: int, limit: int = 12) -> list[MonthData]:
    """The chosen month and up to limit-1 earlier scanned months, oldest first."""
    wanted = [m for m in scanned_months(invoices) if month_key(*m) <= month_key(year, month)]
    return [build_month(masters, invoices, inputs, y, m) for y, m in wanted[-limit:]]
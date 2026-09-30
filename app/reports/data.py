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
A line is a package sale when its product's incentive group name contains
"Package" (Basic Package, Essential Package, Premium Package, ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import InvoicesRepo, month_key, month_label
from app.data.masters_repo import MastersRepo

COUNTER_SALE = "Counter sale (no vehicle)"


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
    is_package: bool = False

    @property
    def billed(self) -> float:
        """What the customer paid for this line (after discount, with GST)."""
        return round(self.sales + self.gst, 2)

    @property
    def gross_profit(self) -> float:
        return round(self.sales - self.cost - self.labour, 2)


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

    @property
    def sales(self) -> float:
        return round(sum(l.sales for l in self.lines), 2)

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
        # No car on an included invoice = a counter sale (every item marked
        # "Vehicle needed = No"; otherwise Scan review would have held it).
        car = cars.get(raw["car_id"]) or dict(make="", model=COUNTER_SALE,
                                               segment=COUNTER_SALE)
        inv = Invoice(
            raw["invoice_no"], day, raw["customer"], raw["customer_type"],
            ex.get("name", ""), ex.get("branch", ""),
            " ".join(p for p in (car.get("make", ""), car.get("model", "")) if p),
            car.get("segment", ""), raw["discount"], raw["tax_total"],
            raw["rounding"], raw["total"], raw["payment_mode"], raw["payment_made"])
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
                        **common)
            group = p["incentive_group"]
            if group and group in incentive_ids:
                ir = rate("incentives", incentive_ids[group], day)
                line.incentive_group = group
                line.incentive_amount = ir.get("incentive_amount", 0.0)
                line.bill_value = ir.get("bill_value", 0.0)
                line.is_package = "package" in group.lower()
            inv.lines.append(line)
        included.append(inv)

    skipped = [f for f in invoices.scan_files(year, month) if f["status"] != "read"]
    return MonthData(year, month, included, left_out, skipped,
                     inputs.costs(year, month), inputs.threshold(year, month),
                     inputs.has_inputs(year, month))


def trend_months(masters: MastersRepo, invoices: InvoicesRepo, inputs: InputsRepo,
                 year: int, month: int, limit: int = 12) -> list[MonthData]:
    """The chosen month and up to limit-1 earlier scanned months, oldest first."""
    wanted = [m for m in scanned_months(invoices) if month_key(*m) <= month_key(year, month)]
    return [build_month(masters, invoices, inputs, y, m) for y, m in wanted[-limit:]]
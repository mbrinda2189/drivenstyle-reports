"""
findings.py - Key findings: WHY the month's figures moved (v0.36.0)
===================================================================

WHAT THE CLIENT ASKED FOR
-------------------------
The reports showed WHAT the figures were. The client wanted them to say WHY
they moved - why profit fell, why the cost of goods sold rose, and so on.
Plan confirmed by Brinda on 16-11-2026 (project doc claude/key-findings-plan.md):

  * every month is compared TWO ways, side by side:
        - the previous month that has been read into the tool, and
        - the AVERAGE of the (up to) three months read before it
          (the current month is never part of its own average);
  * a change is a "finding" when it is worth Rs. 1,000 or more against
    EITHER comparison - the amount is a setting (Monthly reports > Key
    findings), stored once for all months (inputs_repo.findings_threshold);
  * the FULL list is shown (no top-10 cut);
  * findings go on the first page of BOTH PDFs - management and internal
    team - and into Excel ("Key findings" sheet, plus "Drivers" with every
    comparison including the small ones);
  * the tool drafts a plain-English sentence for each finding; an ADMIN can
    change the sentence, leave a finding out, or add remarks before the PDF
    is made (stored per month - inputs_repo.findings_edits). The figures
    themselves can never be edited.

RULES, NOT GUESSWORK
--------------------
Everything here is arithmetic on the figures the other reports already use
(reports/data.py). The same data always gives the same findings, and every
number can be traced to a table. No AI writes the sentences: they are
templates filled with the numbers.

THE FIGURES OF A MONTH (`base_figures`)
---------------------------------------
One flat dictionary per month, e.g. "sales", "cost", "branch:HO",
"pgp:<product>" (gross profit of a product), "head:Rent" (an expense head).
The average of the earlier months is the average of these dictionaries,
key by key - a key a month does not have counts as 0 in that month (an
executive who sold nothing). Percentages of the average (margin %, discount
%, penetration %) are worked out from the averaged amounts, never as an
average of percentages - the same rule as the Trend's "Total" column.
Delivery-list figures (cars delivered, penetration ...) and Zoho-booked
labour exist only for months generated with those files; their average is
over the months that have them, and they are left blank when none has.

HOW BIG IS A CHANGE (the "effect", in rupees)
---------------------------------------------
    rupee rows          the change itself (now - earlier)
    count rows          the change x a rupee value per unit, named in each
                        rule (e.g. invoices x the earlier average bill)
    percentage rows     the change in points x the amount it is a % of
                        (e.g. margin points x this month's sales)
A finding is LISTED when the effect against either comparison is at least
the threshold. "Drivers" in Excel shows every row with its effect.

THE PROFIT BRIDGE (how the net profit change is made up)
--------------------------------------------------------
With s = sales, c = product cost, l = labour, a = automatic indirect costs
(the % of product cost heads), e = the other expenses, and "ref" = the
month compared with (previous month, or the average):

    1 Sales                   (s_now - s_ref) x gross margin_ref
    2 Product cost % of sales  - s_now x (c/s now - c/s ref)
    3 Labour % of sales        - s_now x (l/s now - l/s ref)
    4 Automatic indirect costs - (a_now - a_ref)
    5 Other expenses           - (e_now - e_ref)
    -----------------------------------------------
    = change in net profit (exactly; checked by tests/test_findings.py)

WHY DID PRODUCT COST CHANGE (COGS split)
----------------------------------------
    volume      (s_now / s_ref - 1) x c_ref    - what the cost would have
                                                 done if every item had
                                                 grown with sales
    cost rate   for every item sold in BOTH months:
                qty_now x (cost per unit now - cost per unit ref)
                - the same item cost more (a master cost change)
    mix         the rest: a different mix of items (e.g. more PPF)
    volume + cost rate + mix = the change in product cost (exactly).
The "Product cost % of sales" finding also says when the share rose while
the discount % rose too: the same cost was sold for less.
The automatic indirect costs (breakage 4%, compliance GST 3% of product
cost) simply follow product cost; their finding says so, so they are not
read as a separate problem.

WHEN A % CHANGE IS NOT SHOWN (v0.36.1, Brinda 16-11-2026: "same rule
everywhere" - screen, sentences, Excel and PDF)
--------------------------------------------------------------------------
A % change means nothing when the earlier figure is negative (a loss) or
tiny: profit going from Rs. 20,258 to a loss of Rs. 55,861 printed as
"-375.7%". So the % is left blank when the earlier figure is 0 or less, or -
for rupee rows - smaller than the findings threshold (`pct_change`). Profit
rows that change sign are said in words instead: "turned from a profit of
Rs. 20,258 to a loss of Rs. 55,861".

WHAT IS NOT COMPARED (yet)
--------------------------
Payment modes and the Zoho COGS check need files uploaded for the current
month only, so earlier months have nothing to compare with. Purchases are
not in the tool yet (the purchase analysis is still to be built).

No Qt and no database code here (except `findings_for`, which only reads
through the repositories, like generate.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openpyxl.styles import Alignment, Border, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from app.data.inputs_repo import DEFAULT_FINDINGS_THRESHOLD
from app.data.invoices_repo import MONTH_NAMES, month_key
from app.reports.data import LABOUR_GROUPS, MonthData, labour_group
from app.utils import format_inr

MANAGEMENT, INTERNAL = "management", "internal"     # the two PDFs (pdf_book.py)
PARTS = (MANAGEMENT, INTERNAL)
PART_TITLES = {MANAGEMENT: "Management report", INTERNAL: "Internal team report"}
DEFAULT_THRESHOLD = DEFAULT_FINDINGS_THRESHOLD   # Rs. 1,000 - Brinda, 16-11-2026 ("for now ... 1000, editable")
AVERAGE_OF = 3                  # months in the average
SHEET = "Key findings"
DRIVERS_SHEET = "Drivers"
PDF_SECTION = "Key findings"
REMARKS = "Remarks"             # section of the remarks an admin adds
CHUNK = 6                       # findings per table: a longer section continues
                                # under "<section> (continued)", so the PDF can
                                # fill a page instead of moving a whole long
                                # section to the next page (pdf_book._blocks
                                # keeps a heading with its table)
LINE_CHARS = 150                # a sentence row longer than this is split in two
                                # (the PDF cannot wrap a sentence across columns)

# Sections, in the order they are shown.
SECTIONS = {
    MANAGEMENT: ("Profit bridge", "Sales", "Product cost (COGS)", "Expenses",
                 "New-car business", "Products and services"),
    INTERNAL: ("Labour", "Incentives", "Prices above fixed price", "Tool vs Zoho"),
}
# Rows said as "turned from a profit of ... to a loss of ..." when the sign
# changes (v0.36.1).
PROFIT_KEYS = ("net", "gp")
# Figures that exist only for months generated with an optional file: their
# average is over the months that have them (see the module notes).
OPTIONAL = ("cars", "took", "oe_mat", "dns_mat", "film_side", "film_front",
            "books:", "books_total")


# ---------------------------------------------------------------------------
# One finding
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    """
    One comparison line.
        key        stable name (e.g. "sales", "exec:KUMARAN – HO"): an admin's
                   edit is kept against it, so it survives a regenerate
        kind       money / count / pct (a share, 0.42 = 42%) / effect (a
                   part of the profit bridge or COGS split: only the change
                   columns are filled) / remark (an admin's own line)
        now, prev, avg   this month, previous month, average (None = none)
        effect_prev, effect_avg   rupee size of the change (see notes)
        draft      the tool's sentence; `text` = what is shown (an admin's
                   edit, or the draft)
        headline   the section's main line, shown first
    """
    key: str
    part: str
    section: str
    label: str
    kind: str
    now: float | None = None
    prev: float | None = None
    avg: float | None = None
    effect_prev: float | None = None
    effect_avg: float | None = None
    draft: str = ""
    headline: bool = False
    group: int = 1          # order inside a section: 0 headline, 1 main lines,
                            # 2, 3 ... detail lists (branches, then executives)
    seq: int = 0            # the order the rule wrote it (headlines keep it)
    material: bool = False
    small: float = 0.0      # the threshold: below it an earlier figure gets no % change
    text: str = ""
    edited: bool = False
    hidden: bool = False

    @property
    def change_prev(self) -> float | None:
        if self.kind == "effect":
            return self.effect_prev
        return _diff(self.now, self.prev)

    @property
    def change_avg(self) -> float | None:
        if self.kind == "effect":
            return self.effect_avg
        return _diff(self.now, self.avg)

    @property
    def pct_prev(self) -> float | None:
        """% change on the previous month, or None (see pct_change)."""
        return pct_change(self.kind, self.now, self.prev, self.small)

    @property
    def pct_avg(self) -> float | None:
        return pct_change(self.kind, self.now, self.avg, self.small)

    @property
    def size(self) -> float:
        """The larger rupee effect of the two comparisons (for ordering)."""
        return max(abs(self.effect_prev or 0), abs(self.effect_avg or 0))

    def as_dict(self) -> dict:
        """For the web screen."""
        return dict(key=self.key, part=self.part, section=self.section, label=self.label,
                    kind=self.kind, now=self.now, prev=self.prev, avg=self.avg,
                    change_prev=self.change_prev, change_avg=self.change_avg,
                    pct_prev=self.pct_prev, pct_avg=self.pct_avg,
                    effect_prev=self.effect_prev, effect_avg=self.effect_avg,
                    draft=self.draft, text=self.text or self.draft, edited=self.edited,
                    hidden=self.hidden, material=self.material, headline=self.headline)


def _diff(a, b):
    return None if a is None or b is None else round(a - b, 4)


def _ratio(a, b):
    return a / b if a is not None and b else 0.0


# ---------------------------------------------------------------------------
# The figures of one month
# ---------------------------------------------------------------------------
def _exec(name: str, branch: str) -> str:
    return f"{name} – {branch}" if branch else name


def base_figures(m: MonthData, rto: dict | None = None) -> dict[str, float]:
    """Every amount the findings compare, for one month (see module notes)."""
    f: dict[str, float] = {}

    def add(key: str, value: float) -> None:
        f[key] = f.get(key, 0.0) + (value or 0.0)

    f["invoices"] = float(len(m.invoices))
    f["sales"] = m.sales
    f["discount"] = m.discount
    f["cost"] = m.auto_base                      # product cost
    f["labour"] = round(sum(i.labour for i in m.invoices), 2)
    f["gp"] = m.gross_profit
    f["auto"] = round(sum(a for _, _, a in m.auto_indirect), 2)
    f["entered"] = round(sum(a for _, a in m.entered_indirect), 2)
    f["net"] = round(f["gp"] - f["auto"] - f["entered"], 2)
    f["packages"] = float(sum(1 for i in m.invoices if i.package))
    f["incentive"] = m.incentive_payable
    f["internal"] = m.internal_incentive
    for inv in m.invoices:
        add("branch:" + (inv.branch or "(no branch)"), inv.sales)
        add("exec:" + _exec(inv.executive, inv.branch), inv.sales)
    for l in m.lines:
        add("cat:" + l.category, l.sales)
        add("psales:" + l.product, l.sales)
        add("pcost:" + l.product, l.cost)
        add("pqty:" + l.product, l.qty)
        add("pgp:" + l.product, l.gross_profit)
        if l.labour:
            add("lab:" + labour_group(l.product), l.labour)
            add("labqty:" + labour_group(l.product), l.qty)
    for head, amount in m.entered_indirect:
        add("head:" + head, amount)
    for name, amount in m.incentive_by_executive.items():
        add("inc:" + name, amount)
    raised = m.raised_prices()
    f["raised"] = round(sum(r["raised"] for r in raised), 2)
    f["raised_items"] = float(len(raised))
    for g in m.raised_by_executive():
        add("raisedex:" + g["executive"], g["raised"])
    if m.books_labour:                            # Zoho expense file uploaded
        for kind, amount in m.books_labour.items():
            add("books:" + kind, amount)
        f["books_total"] = round(sum(m.books_labour.values()), 2)
    for key, column in (("cars", "cars"), ("took", "took_dns"), ("oe_mat", "oe_mat"),
                        ("dns_mat", "dns_mat"), ("film_side", "film_side"),
                        ("film_front", "film_front")):
        if rto and rto.get(column) is not None:
            f[key] = float(rto[column])
    return {k: round(v, 2) for k, v in f.items()}


def _optional(key: str) -> bool:
    return any(key == o or (o.endswith(":") and key.startswith(o)) for o in OPTIONAL)


def average(months: list[dict]) -> dict[str, float]:
    """Key-by-key average of several months' figures (see module notes)."""
    keys = {k for f in months for k in f}
    out = {}
    for k in keys:
        if _optional(k):
            have = [f[k] for f in months if k in f]
        else:
            have = [f.get(k, 0.0) for f in months]
        if have:
            out[k] = round(sum(have) / len(have), 4)
    return out


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------
def _short(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1][:3]} {year}"


def rupees(v: float) -> str:
    return "₹" + format_inr(abs(v), 0)


def _num(v: float) -> str:
    return f"{v:,.0f}" if abs(v - round(v)) < 0.05 else f"{v:,.1f}"


def _show(kind: str, v: float | None) -> str:
    if v is None:
        return "–"
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "count":
        return _num(v)
    return rupees(v) if v >= 0 else "−" + rupees(v)


def pct_change(kind: str, now, ref, small: float = 0.0):
    """
    The % change from `ref` to `now`, or None when it would mislead
    (v0.36.1, see WHEN A % CHANGE IS NOT SHOWN): no figure; a share or a
    bridge row (they have no % change); the earlier figure 0 or less; or,
    for rupee rows, the earlier figure below `small` (the threshold).
    """
    if kind in ("pct", "effect", "remark") or now is None or ref is None:
        return None
    if ref <= 0 or (kind == "money" and ref < small):
        return None
    return (now - ref) / ref


def _move(kind: str, now: float, ref: float, small: float = 0.0,
          profit: bool = False) -> str:
    """'up ₹20,500 (+94.0%)' / 'down 1.2 pts' / 'no change' /
    'turned from a profit of ₹20,258 to a loss of ₹55,861' (`profit` rows)."""
    d = now - ref
    if kind == "pct":
        if abs(d) < 0.0005:
            return "no change"
        return f"{'up' if d > 0 else 'down'} {abs(d) * 100:.1f} pts"
    if abs(d) < (0.05 if kind == "count" else 0.5):
        return "no change"
    if profit and ref > 0 > now:
        return f"turned from a profit of {rupees(ref)} to a loss of {rupees(now)}"
    if profit and ref < 0 <= now:
        return f"turned from a loss of {rupees(ref)} to a profit of {rupees(now)}"
    amount = _num(abs(d)) if kind == "count" else rupees(d)
    share = pct_change(kind, now, ref, small)
    pct = f" ({share * 100:+.1f}%)".replace("-", "−") if share is not None else ""
    return f"{'up' if d > 0 else 'down'} {amount}{pct}"


class _Words:
    """The two comparison names used in sentences."""

    def __init__(self, prev_label: str, avg_label: str | None, small: float = 0.0):
        self.prev, self.avg, self.small = prev_label, avg_label, small

    def compare(self, kind: str, now, prev, avg, profit: bool = False) -> str:
        """'up ₹62,400 (+4.2%) on Oct 2026; down ₹1,200 (−0.1%) on the
        Aug–Oct 2026 average' (new / gone items said in words)."""
        bits = []
        if prev is not None:
            if kind != "pct" and not prev and now:
                bits.append(f"new against {self.prev} (nil)")
            elif kind != "pct" and prev and not now:
                bits.append(f"nil this month ({_show(kind, prev)} in {self.prev})")
            else:
                bits.append(f"{_move(kind, now, prev, self.small, profit)} on {self.prev}")
        if avg is not None and self.avg:
            bits.append(f"{_move(kind, now, avg, self.small, profit)} on the {self.avg} average")
        return "; ".join(bits)

    def effect(self, e_prev, e_avg) -> str:
        """'+₹38,000 on Oct 2026; −₹2,100 on the ... average'."""
        sign = lambda v: ("+" if v >= 0 else "−") + rupees(v)
        bits = []
        if e_prev is not None:
            bits.append(f"{sign(e_prev)} on {self.prev}")
        if e_avg is not None and self.avg:
            bits.append(f"{sign(e_avg)} on the {self.avg} average")
        return "; ".join(bits)


# ---------------------------------------------------------------------------
# Building the findings
# ---------------------------------------------------------------------------
class _Builder:
    def __init__(self, now: dict, prev: dict, avg: dict | None, words: _Words):
        self.n, self.p, self.a, self.w = now, prev, avg, words
        self.rows: list[Finding] = []

    # helpers ---------------------------------------------------------------
    def refs(self):
        """(name, reference figures) for each comparison that exists."""
        return [("prev", self.p)] + ([("avg", self.a)] if self.a is not None else [])

    def value(self, figures: dict | None, key, optional: bool = False):
        if figures is None or key is None:
            return None
        if callable(key):
            return key(figures)
        if optional or _optional(key):
            return figures.get(key)
        return figures.get(key, 0.0)

    def add(self, part, section, key, label, kind, get, unit=None, base=None,
            why=None, headline=False, effects=None, group=1) -> Finding:
        """
        One comparison row. `get` = a figure key or a function of a month's
        figures. Effect: money - the change; count - change x unit(ref);
        pct - change x base(now). `effects` (bridge / split rows) gives the
        effect for a reference directly: effects(ref) -> rupees.
        `why` = a function returning an extra clause for the sentence.
        """
        now = self.value(self.n, get)
        prev = self.value(self.p, get)
        avg = self.value(self.a, get)
        e = {}
        for name, ref in self.refs():
            r = prev if name == "prev" else avg
            if effects is not None:
                e[name] = round(effects(ref), 2)
            elif now is None or r is None:
                e[name] = None
            elif kind == "money":
                e[name] = round(now - r, 2)
            elif kind == "count":
                e[name] = round((now - r) * (unit(ref) if unit else 0.0), 2)
            elif kind == "pct":
                e[name] = round((now - r) * (base(self.n) if base else 0.0), 2)
        f = Finding(key, part, section, label, kind, now, prev, avg,
                    e.get("prev"), e.get("avg"), headline=headline,
                    group=0 if headline else group, seq=len(self.rows))
        if kind == "effect":
            f.now = f.prev = f.avg = None
            body = self.w.effect(f.effect_prev, f.effect_avg)
            f.draft = f"{label} – effect on net profit: {body}." if body else label + "."
        elif now is None:
            return f                                  # nothing this month (no list ...)
        else:
            body = self.w.compare(kind, now, prev, avg, profit=key in PROFIT_KEYS)
            f.draft = f"{label} {_show(kind, now)} – {body}." if body else f"{label} {_show(kind, now)}."
        if why:
            extra = why()
            if extra:
                f.draft = f.draft[:-1] + ". " + extra
        self.rows.append(f)
        return f

    def keys(self, prefix: str) -> list[str]:
        """Every name under a prefix in any of the months compared."""
        names = set()
        for figures in (self.n, self.p, self.a or {}):
            names |= {k[len(prefix):] for k in figures if k.startswith(prefix)}
        return sorted(names)

    # the management report ---------------------------------------------------
    def management(self, auto_rates_text: str) -> None:
        M = MANAGEMENT
        gm = lambda f: _ratio(f.get("gp", 0), f.get("sales", 0))
        cs = lambda f: _ratio(f.get("cost", 0), f.get("sales", 0))
        ls = lambda f: _ratio(f.get("labour", 0), f.get("sales", 0))
        n = self.n

        # 1. Profit bridge -----------------------------------------------------
        S = "Profit bridge"
        self.add(M, S, "net", "Net profit", "money", "net", headline=True)
        self.add(M, S, "gp", "Gross profit", "money", "gp", headline=True)

        def sales_part(ref):
            if not ref.get("sales"):
                return n["gp"] - ref.get("gp", 0)
            return (n["sales"] - ref["sales"]) * gm(ref)

        def share(ratio):
            def effect(ref):
                if not ref.get("sales"):
                    return 0.0
                return -n["sales"] * (ratio(n) - ratio(ref))
            return effect

        self.add(M, S, "bridge:sales", "More / less sales (at the earlier margin)", "effect",
                 None, effects=sales_part)
        self.add(M, S, "bridge:cost", "Product cost as a share of sales", "effect", None,
                 effects=share(cs))
        self.add(M, S, "bridge:labour", "Labour as a share of sales", "effect", None,
                 effects=share(ls))
        self.add(M, S, "bridge:auto", "Automatic indirect costs (follow product cost)",
                 "effect", None, effects=lambda ref: -(n["auto"] - ref.get("auto", 0)))
        self.add(M, S, "bridge:expenses", "Other expenses (Monthly inputs)", "effect", None,
                 effects=lambda ref: -(n["entered"] - ref.get("entered", 0)))

        # 2. Sales -------------------------------------------------------------
        S = "Sales"
        bill = lambda f: _ratio(f.get("sales", 0), f.get("invoices", 0))
        self.add(M, S, "sales", "Sales (excluding GST)", "money", "sales", headline=True)
        self.add(M, S, "invoices", "Invoices", "count", "invoices", unit=bill,
                 why=lambda: "Valued at the earlier average bill per invoice.")
        self.add(M, S, "avg_bill", "Average bill per invoice", "money", bill,
                 why=None)
        # the average bill's effect on sales is (bill now - bill ref) x invoices now
        last = self.rows[-1]
        for name, ref in self.refs():
            setattr(last, "effect_" + name,
                    round((bill(n) - bill(ref)) * n["invoices"], 2))
        gross = lambda f: f.get("sales", 0) + f.get("discount", 0)
        dpct = lambda f: _ratio(f.get("discount", 0), gross(f))
        self.add(M, S, "discount", "Discount given (excl. GST)", "money", "discount")
        self.add(M, S, "discount_pct", "Discount % of price before discount", "pct", dpct,
                 base=gross)
        for cat in self.keys("cat:"):
            self.add(M, S, "cat:" + cat, f"{cat} sales", "money", "cat:" + cat)
        for b in self.keys("branch:"):
            self.add(M, S, "branch:" + b, f"Branch {b} – sales", "money", "branch:" + b,
                     group=2)
        for e in self.keys("exec:"):
            self.add(M, S, "exec:" + e, f"{e} – sales", "money", "exec:" + e, group=3)

        # 3. Product cost (COGS) ------------------------------------------------
        S = "Product cost (COGS)"
        self.add(M, S, "cost", "Product cost", "money", "cost", headline=True)
        products = self.keys("pqty:")
        unit_cost = lambda f, p: _ratio(f.get("pcost:" + p, 0), f.get("pqty:" + p, 0))

        def rate_part(ref):
            return sum(n.get("pqty:" + p, 0) * (unit_cost(n, p) - unit_cost(ref, p))
                       for p in products if n.get("pqty:" + p) and ref.get("pqty:" + p))

        def volume_part(ref):
            if not ref.get("sales"):
                return n["cost"] - ref.get("cost", 0)
            return (n["sales"] / ref["sales"] - 1) * ref.get("cost", 0)

        def mix_part(ref):
            return (n["cost"] - ref.get("cost", 0)) - volume_part(ref) - rate_part(ref)

        cost_split = [
            ("cogs:volume", "Volume – cost moved with sales", volume_part),
            ("cogs:mix", "Mix – a different mix of items sold", mix_part),
            ("cogs:rate", "Cost rate – the same items cost more / less", rate_part),
        ]
        for key, label, fn in cost_split:
            f = self.add(M, S, key, label, "effect", None, effects=fn)
            # these explain product COST: a rise is shown as + (not as profit)
            body = self.w.effect(f.effect_prev, f.effect_avg)
            f.draft = f"{label} – effect on product cost: {body}." if body else label + "."

        def cost_share_why():
            bits = []
            for name, ref in self.refs():
                if cs(n) > cs(ref) + 0.0005 and dpct(n) > dpct(ref) + 0.0005:
                    where = self.w.prev if name == "prev" else f"the {self.w.avg} average"
                    bits.append(f"discount % also rose ({dpct(ref) * 100:.1f}% → "
                                f"{dpct(n) * 100:.1f}%) against {where}: the same cost was "
                                "sold for less")
            return ("Part of this: " + "; ".join(bits) + ".") if bits else ""

        self.add(M, S, "cost_pct", "Product cost % of sales", "pct", cs,
                 base=lambda f: f.get("sales", 0), why=cost_share_why)
        for p in products:
            if not n.get("pqty:" + p):
                continue
            qty_now = n["pqty:" + p]
            self.add(M, S, "unitcost:" + p, f"{p} – cost per unit", "money",
                     lambda f, p=p: unit_cost(f, p) if f.get("pqty:" + p) else None,
                     group=3)
            f = self.rows[-1]
            if f.key != "unitcost:" + p:
                continue
            # effect = qty this month x the change in cost per unit
            for name, ref in self.refs():
                if ref.get("pqty:" + p):
                    setattr(f, "effect_" + name,
                            round(qty_now * (unit_cost(n, p) - unit_cost(ref, p)), 2))
                else:
                    setattr(f, "effect_" + name, None)
            f.draft = f.draft[:-1] + f". On {_num(qty_now)} sold this month."
        self.add(M, S, "labour", "Labour", "money", "labour", group=2)
        self.add(M, S, "auto", "Automatic indirect costs", "money", "auto", group=2,
                 why=lambda: f"These are {auto_rates_text} of product cost, so they "
                             "follow product cost – not a separate cost driver.")

        # 4. Expenses ------------------------------------------------------------
        S = "Expenses"
        self.add(M, S, "entered", "Expenses entered (Monthly inputs)", "money", "entered",
                 headline=True)
        for h in self.keys("head:"):
            self.add(M, S, "head:" + h, h, "money", "head:" + h, group=2)

        # 5. New-car business (months generated with the delivery list) ----------
        S = "New-car business"
        per_car = lambda f: _ratio(f.get("sales", 0), f.get("invoices", 0))
        self.add(M, S, "cars", "Cars delivered", "count", "cars", unit=per_car,
                 headline=True)
        self.add(M, S, "took", "Cars fitted with DNS accessories", "count", "took",
                 unit=per_car, why=lambda: "Valued at the average bill per invoice.")
        cars_value = lambda f: (f.get("cars") or 0) * per_car(f)
        for key, label in (("took", "DNS penetration % of cars delivered"),
                           ("oe_mat", "Full floor mat – OE (dealer) %"),
                           ("dns_mat", "Full floor mat – DNS %"),
                           ("film_side", "Sunfilm side & rear – DNS %"),
                           ("film_front", "Sunfilm front – DNS %")):
            pct = (lambda f, k=key: _ratio(f.get(k), f.get("cars"))
                   if f.get(k) is not None and f.get("cars") else None)
            self.add(M, S, "pen:" + key, label, "pct", pct, base=cars_value)

        # 6. Products and services (gross profit) --------------------------------
        S = "Products and services"
        self.add(M, S, "packages", "Packages sold", "count", "packages", unit=per_car)
        for p in self.keys("pgp:"):
            self.add(M, S, "pgp:" + p, f"{p} – gross profit", "money", "pgp:" + p,
                     why=lambda p=p: self._qty_clause(p), group=2)

    def _qty_clause(self, p: str) -> str:
        q = lambda f: (f or {}).get("pqty:" + p, 0)
        if self.p is None:
            return ""
        text = f"Quantity {_num(q(self.n))} (was {_num(q(self.p))}"
        if self.a is not None:
            text += f"; average {_num(q(self.a))}"
        return text + ")."

    # the internal team report ------------------------------------------------
    def internal(self) -> None:
        I = INTERNAL
        n = self.n
        S = "Labour"
        self.add(I, S, "i:labour", "Labour", "money", "labour", headline=True)
        per_inv = lambda f: _ratio(f.get("labour", 0), f.get("invoices", 0))
        self.add(I, S, "i:labour_per_invoice", "Labour per invoice", "money", per_inv)
        last = self.rows[-1]
        for name, ref in self.refs():
            setattr(last, "effect_" + name,
                    round((per_inv(n) - per_inv(ref)) * n["invoices"], 2))
        for g in LABOUR_GROUPS:
            if any(f.get("lab:" + g) for f in (n, self.p, self.a or {})):
                self.add(I, S, "lab:" + g, f"Labour – {g}", "money", "lab:" + g,
                         why=lambda g=g: self._labqty(g))

        S = "Incentives"
        inv_count = lambda f: f.get("invoices", 0)
        self.add(I, S, "incentive", "Spot incentive payable", "money", "incentive",
                 headline=True)
        self.add(I, S, "internal", "Internal team incentive", "money", "internal")
        per = lambda f: _ratio(f.get("incentive", 0), inv_count(f))
        self.add(I, S, "incentive_per_invoice", "Spot incentive per invoice", "money", per)
        last = self.rows[-1]
        for name, ref in self.refs():
            setattr(last, "effect_" + name, round((per(n) - per(ref)) * n["invoices"], 2))
        for e in self.keys("inc:"):
            self.add(I, S, "inc:" + e, f"{e} – spot incentive", "money", "inc:" + e,
                     group=2)

        S = "Prices above fixed price"
        per_item = lambda f: _ratio(f.get("raised", 0), f.get("raised_items", 0))
        self.add(I, S, "raised", "Amount typed above fixed prices", "money", "raised",
                 headline=True)
        self.add(I, S, "raised_items", "Items typed above the fixed price", "count",
                 "raised_items", unit=per_item,
                 why=lambda: "Valued at the earlier average amount raised per item.")
        for e in self.keys("raisedex:"):
            self.add(I, S, "raisedex:" + e, f"{e} – typed above fixed price", "money",
                     "raisedex:" + e, group=2)

        S = "Tool vs Zoho"
        if "books_total" in n:
            diff = lambda f: (round(f.get("labour", 0) - f["books_total"], 2)
                              if f.get("books_total") is not None else None)
            self.add(I, S, "labour_vs_zoho", "Labour – tool minus Zoho", "money", diff,
                     headline=True)
            self.add(I, S, "books_total", "Labour booked in Zoho", "money", "books_total")

    def _labqty(self, g: str) -> str:
        q = lambda f: (f or {}).get("labqty:" + g, 0)
        text = f"Items with labour {_num(q(self.n))} (was {_num(q(self.p))}"
        if self.a is not None:
            text += f"; average {_num(q(self.a))}"
        return text + ")."


# ---------------------------------------------------------------------------
# The result for one month
# ---------------------------------------------------------------------------
@dataclass
class Findings:
    year: int
    month: int
    threshold: float
    prev_label: str = ""              # e.g. "Oct 2026" ("" = nothing to compare)
    avg_label: str = ""               # e.g. "Aug–Oct 2026" ("" = no average)
    avg_months: int = 0
    rows: list[Finding] = field(default_factory=list)       # every comparison
    remarks: dict[str, list[str]] = field(default_factory=dict)   # part -> admin remarks

    @property
    def comparable(self) -> bool:
        return bool(self.prev_label)

    def listed(self, part: str, include_hidden: bool = False) -> list[Finding]:
        """The findings shown for `part`: material ones (and remarks), in
        section order, headline first, then the largest change first;
        hidden ones left out unless asked for."""
        order = {s: i for i, s in enumerate(SECTIONS[part])}
        rows = [r for r in self.rows if r.part == part and r.material
                and (include_hidden or not r.hidden)]
        rows.sort(key=lambda r: (order.get(r.section, 99), r.group,
                                 r.seq if r.headline else -r.size, r.label))
        for i, text in enumerate(self.remarks.get(part, [])):
            rows.append(Finding(f"remark:{i}", part, REMARKS, "Remark", "remark",
                                draft=text, text=text, material=True))
        return rows


def compute(current: MonthData, earlier: list[MonthData], rto_by_month: dict | None = None,
            threshold: float = DEFAULT_THRESHOLD, auto_rates_text: str = "4% + 3%",
            edits: dict | None = None, remarks: dict | None = None) -> Findings:
    """
    The findings for `current`, against the latest month in `earlier` and
    the average of the last AVERAGE_OF months in `earlier` (oldest first).
    `edits` = {(part, key): {"text": ..., "hidden": bool}} from the admin.
    """
    rto_by_month = rto_by_month or {}
    out = Findings(current.year, current.month, threshold,
                   remarks={k: list(v) for k, v in (remarks or {}).items()})
    if not earlier:
        return out
    figures = lambda m: base_figures(m, rto_by_month.get(month_key(m.year, m.month)))
    now = figures(current)
    prev_m = earlier[-1]
    prev = figures(prev_m)
    window = earlier[-AVERAGE_OF:]
    out.prev_label = _short(prev_m.year, prev_m.month)
    avg = None
    if len(window) >= 2:              # an average of one month would only repeat it
        avg = average([figures(m) for m in window])
        first, last = window[0], window[-1]
        out.avg_months = len(window)
        out.avg_label = (f"{MONTH_NAMES[first.month - 1][:3]}–{_short(last.year, last.month)}"
                         if first.year == last.year else
                         f"{_short(first.year, first.month)}–{_short(last.year, last.month)}")
    b = _Builder(now, prev, avg, _Words(out.prev_label, out.avg_label or None, threshold))
    b.management(auto_rates_text)
    b.internal()
    edits = edits or {}
    for r in b.rows:
        r.material = r.size >= threshold - 1e-9
        r.small = threshold
        r.text = r.draft
        e = edits.get((r.part, r.key))
        if e:
            if (e.get("text") or "").strip():
                r.text, r.edited = e["text"].strip(), True
            r.hidden = bool(e.get("hidden"))
    out.rows = b.rows
    return out


def auto_text(m: MonthData) -> str:
    """'4% + 3%' from the month's automatic indirect cost rates."""
    return " + ".join(f"{pct * 100:g}%" for _, pct, _ in m.auto_rates) or "a share"


def findings_for(masters, invoices, inputs, year: int, month: int,
                 current: MonthData | None = None,
                 trend: list[MonthData] | None = None) -> Findings:
    """The findings of a month with the admin's edits, from the database.
    `current` / `trend` can be passed when already built (generate.py)."""
    from app.reports.data import build_month, trend_months
    if trend is None:
        trend = trend_months(masters, invoices, inputs, year, month, limit=AVERAGE_OF + 1)
    if current is None:
        current = (trend[-1] if trend and (trend[-1].year, trend[-1].month) == (year, month)
                   else build_month(masters, invoices, inputs, year, month))
    earlier = [m for m in trend if (m.year, m.month) < (year, month)]
    saved = inputs.findings_edits(year, month)
    return compute(current, earlier, inputs.rto_months(), inputs.findings_threshold(),
                   auto_text(current), saved["edits"], saved["remarks"])


# ---------------------------------------------------------------------------
# Writing: Excel sheets and the PDF section
# ---------------------------------------------------------------------------
def _split(text: str) -> list[str]:
    """A sentence in lines of at most LINE_CHARS characters (at spaces)."""
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > LINE_CHARS:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


def _cells(f: Finding) -> list:
    """Figures of one row: now, prev, change, change %, avg, change, change %."""
    cells = [f.now, f.prev, f.change_prev, f.pct_prev,      # % blank when it would
             f.avg, f.change_avg, f.pct_avg]                # mislead (v0.36.1)
    if f.kind == "pct":             # the change of a share is shown in points (POINTS)
        cells = [round(v * 100, 2) if v is not None and i in (2, 5) else v
                 for i, v in enumerate(cells)]
    if f.kind == "count":           # an average of counts: one decimal is enough
        cells = [round(v, 1) if v is not None and i in (0, 1, 2, 4, 5) else v
                 for i, v in enumerate(cells)]
    return cells


def _formats(f: Finding) -> list[str]:
    from app.reports.trend import POINTS
    from app.reports.workbook import MONEY, PCT
    value = {"pct": PCT, "count": "General", "money": MONEY}.get(f.kind, MONEY)
    change = POINTS if f.kind == "pct" else value
    return [value, value, change, PCT, value, change, PCT]


def write_findings(ws: Worksheet, result: Findings, part: str | None, label: str,
                   pdf: bool = False) -> None:
    """
    The "Key findings" section: one table per section of the report, each
    finding a row of figures with its sentence on the row below (in italics).
    `part` = MANAGEMENT / INTERNAL (one PDF), or None for Excel (both parts,
    each under its own heading). Eight columns at most (the PDF's limit).
    """
    from app.reports.trend import _header
    from app.reports.workbook import NAVY, _finish, _font, rule, section, title
    notes = []
    if result.comparable:
        notes.append(f"Compared with {result.prev_label}"
                     + (f" and with the average of {result.avg_label} "
                        f"({result.avg_months} months)" if result.avg_label else "")
                     + f". Listed: changes of ₹{format_inr(result.threshold, 0)} or more "
                       "against either; Drivers sheet = every comparison.")
    row = title(ws, "Key findings", f"{MONTH_NAMES[result.month - 1]} {result.year}", notes)
    if not result.comparable:
        ws.cell(row, 1, "No earlier month has been read into the tool, so there is nothing "
                        "to compare with yet.").font = _font(italic=True)
        _finish(ws)
        return
    # "Avg Jun–Aug": the year is left out so the heading fits its column
    avg_head = ("Avg " + result.avg_label.rsplit(" ", 1)[0]) if result.avg_label else "Average"
    labels = ["This month", result.prev_label, "Change", "Change %",
              avg_head, "Change", "Change %"]
    for p in ([part] if part else list(PARTS)):
        rows = result.listed(p)
        if part is None:
            ws.cell(row, 1, PART_TITLES[p]).font = _font(True, NAVY, 12)
            row += 2
        if not rows:
            ws.cell(row, 1, f"No change of ₹{format_inr(result.threshold, 0)} or more."
                    ).font = _font(italic=True)
            row += 3
            continue
        current, count = None, 0
        for f in rows:
            if f.section != current or (count >= CHUNK and f.kind != "remark"):
                if current is not None:
                    row += 1
                heading = f.section if f.section != current else f"{f.section} (continued)"
                current, count = f.section, 0
                row = section(ws, row, heading)
                if f.kind != "remark":
                    _header(ws, row, "Particulars", labels)
                    row += 1
            count += 1
            if f.kind == "remark":
                for line in _split("• " + f.text):
                    ws.cell(row, 1, line).font = _font()
                    row += 1
                continue
            ws.cell(row, 1, f.label).font = _font(f.headline)
            for c, (v, fmt) in enumerate(zip(_cells(f), _formats(f)), start=2):
                cell = ws.cell(row, c, "" if v is None else v)
                cell.font, cell.number_format = _font(f.headline), fmt
                cell.alignment = Alignment(horizontal="right")
            for c in range(1, 9):
                ws.cell(row, c).border = Border(top=rule) if f.headline else Border()
            row += 1
            for line in _split(f.text):
                ws.cell(row, 1, line).font = _font(italic=True, color="5B6B82")
                row += 1
        row += 2
    ws.column_dimensions["A"].width = 42
    _finish(ws)


def write_drivers(ws: Worksheet, result: Findings) -> None:
    """Excel only: every comparison, listed or not, with its rupee effect."""
    from app.reports.workbook import Col, _finish, table, title
    row = title(ws, "Drivers – every comparison", f"{MONTH_NAMES[result.month - 1]} "
                f"{result.year}", [
        "Every figure the key findings compare. 'Effect' = the rupee size of the change "
        "used against the threshold (see the Key findings notes). Listed = Yes when it is "
        f"₹{format_inr(result.threshold, 0)} or more against either comparison.",
        "Percentages: Now / Previous / Average are shares (42% = 0.42); their change is "
        "in percentage points."])
    if not result.comparable:
        ws.cell(row, 1, "Nothing to compare with yet.")
        _finish(ws)
        return
    order = {s: (pi, si) for pi, p in enumerate(PARTS) for si, s in enumerate(SECTIONS[p])}
    rows = []
    for f in sorted(result.rows, key=lambda r: (order.get(r.section, (9, 9)), -r.size)):
        rows.append(dict(part=PART_TITLES[f.part], section=f.section, label=f.label,
                         kind=f.kind, now=f.now, prev=f.prev, avg=f.avg,
                         e_prev=f.effect_prev, e_avg=f.effect_avg,
                         listed="Yes" if f.material else "No",
                         shown="Left out by admin" if f.hidden else
                         ("Edited" if f.edited else ""),
                         text=f.text))
    table(ws, row, [
        Col("Report", "part", width=20), Col("Section", "section", width=22),
        Col("Particulars", "label", width=44), Col("Kind", "kind", width=8),
        Col("This month", "now", "money"), Col(result.prev_label, "prev", "money"),
        Col(f"Avg {result.avg_label}" if result.avg_label else "Average", "avg", "money"),
        Col(f"Effect vs {result.prev_label}", "e_prev", "money"),
        Col("Effect vs average", "e_avg", "money"),
        Col("Listed", "listed", width=8), Col("Admin", "shown", width=16),
        Col("Sentence", "text", width=90)], rows, filters=True)
    _finish(ws, f"A{row + 1}")

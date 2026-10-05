"""
slip.py - The payout slip: who is to be paid how much, with the invoices
========================================================================

WHAT THIS MODULE DOES
---------------------
Before paying, the staff need one sheet that says what is due to each
person; after paying, the owner wants one that says what went out on a
day. `build(lines, ...)` makes both from the register's payout lines, as
data; `to_html(slip)` turns it into a page the app shows, prints or saves
as a PDF. No Qt and no Google here.

    to pay        every line that is Pending
    paid on day   every line Paid with that paid date

GROUPING
--------
One block per payee: Labour first (it has no payee - the technician is
not recorded), then the sales executives A-Z, then the Internal team.
Each block lists its invoices and ends with its total; the slip ends with
the grand total. Negative lines (adjustments after a re-issued invoice)
are shown and reduce the total, so the slip always equals the register.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape

from app.utils import format_inr
from payout_app.register import PAID, PENDING

LABOUR, INTERNAL = "Labour", "Internal team"


@dataclass
class Block:
    title: str                                   # "Labour", "Kumaran" ...
    lines: list[dict] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(l["amount"] for l in self.lines), 2)


@dataclass
class Slip:
    title: str
    made_at: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(b.total for b in self.blocks), 2)

    @property
    def count(self) -> int:
        return sum(len(b.lines) for b in self.blocks)


def _block_title(line: dict) -> str:
    if line["type"] == LABOUR:
        return LABOUR
    return line["payee"] or line["type"]


def build(lines: list[dict], paid_on: date | None = None,
          now: datetime | None = None) -> Slip:
    """`paid_on` None = the "to pay" slip (Pending lines); else lines paid that day."""
    now = now or datetime.now()
    if paid_on is None:
        chosen = [l for l in lines if l["status"] == PENDING]
        title = "To pay - pending as on " + now.strftime("%d-%m-%Y")
    else:
        chosen = [l for l in lines if l["status"] == PAID and l["paid_date"] == paid_on]
        title = "Paid on " + paid_on.strftime("%d-%m-%Y")
    groups: dict[str, Block] = {}
    for line in chosen:
        groups.setdefault(_block_title(line), Block(_block_title(line))).lines.append(line)
    order = lambda b: (0 if b.title == LABOUR else 2 if b.title == INTERNAL else 1,
                       b.title.lower())
    blocks = sorted(groups.values(), key=order)
    for block in blocks:
        block.lines.sort(key=lambda l: (l["invoice_date"] or date.min, l["line_id"]))
    return Slip(title, now.strftime("%d-%m-%Y %H:%M"), blocks)


def to_html(slip: Slip) -> str:
    """The slip as a simple page (tables only - prints the same everywhere)."""
    cell = "padding:4px 8px; border-bottom:1px solid #DCE4EF;"
    out = [f"<h2 style='color:#0B2545; margin-bottom:2px;'>Drive N Style - payout slip</h2>",
           f"<p style='margin-top:0;'><b>{escape(slip.title)}</b><br>"
           f"<span style='color:#5B6B82;'>{slip.count} line(s) &nbsp;·&nbsp; printed "
           f"{escape(slip.made_at)}</span></p>"]
    if not slip.blocks:
        out.append("<p>Nothing to show.</p>")
    for block in slip.blocks:
        out.append(f"<h3 style='color:#1F5FBF; margin-bottom:4px;'>{escape(block.title)}"
                   f" &nbsp; {format_inr(block.total)}</h3>")
        out.append("<table width='100%' cellspacing='0'>"
                   f"<tr style='background:#E8F0FC;'><th align='left' style='{cell}'>Invoice</th>"
                   f"<th align='left' style='{cell}'>Date</th>"
                   f"<th align='left' style='{cell}'>Customer</th>"
                   f"<th align='left' style='{cell}'>Type</th>"
                   f"<th align='right' style='{cell}'>Amount</th></tr>")
        for line in block.lines:
            day = line["invoice_date"].strftime("%d-%m-%Y") if line["invoice_date"] else ""
            out.append(
                f"<tr><td style='{cell}'>{escape(line['invoice_no'])}</td>"
                f"<td style='{cell}'>{day}</td>"
                f"<td style='{cell}'>{escape(line['customer'])}</td>"
                f"<td style='{cell}'>{escape(line['type'])}</td>"
                f"<td align='right' style='{cell}'>{format_inr(line['amount'])}</td></tr>")
        out.append(f"<tr><td colspan='4' align='right' style='{cell}'><b>Total</b></td>"
                   f"<td align='right' style='{cell}'><b>{format_inr(block.total)}</b></td>"
                   "</tr></table>")
    out.append(f"<h3 style='margin-top:14px;'>Grand total &nbsp; {format_inr(slip.total)}</h3>")
    return "\n".join(out)

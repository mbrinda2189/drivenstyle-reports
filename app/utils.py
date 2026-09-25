"""
utils.py - Small shared helpers
===============================

format_inr(value, decimals=2)
    Formats a number in the Indian digit-grouping style used in the client's
    books and reports, e.g. 1234567.5 -> "12,34,567.50".
    The last three digits form one group; every group before that has two
    digits (lakh / crore grouping). Negative numbers keep their minus sign.

parse_inr(text)
    The reverse: turns "12,34,567.50" (or "₹ 1,200") back into a float.
    Returns None if the text is not a valid number. Used when the user edits
    amounts in the masters tables.

first_of_next_month(today=None)
    The 1st of the month after `today`. Default effective date for a rate
    change, because rates usually change at the start of a month.
"""

from __future__ import annotations

from datetime import date


def format_inr(value: float, decimals: int = 2) -> str:
    """Return `value` formatted with Indian digit grouping (lakh/crore)."""
    negative = value < 0
    value = abs(value)

    # Split into whole-number and decimal parts using normal rounding.
    text = f"{value:.{decimals}f}"
    whole, _, fraction = text.partition(".")

    # Last three digits stay together; the rest is grouped in pairs.
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        whole = ",".join(pairs + [tail])

    result = whole + (f".{fraction}" if decimals else "")
    return f"-{result}" if negative else result


def parse_inr(text: str) -> float | None:
    """Convert an Indian-formatted amount string back to float (or None)."""
    cleaned = (
        text.replace("₹", "").replace(",", "").replace(" ", "").strip()
    )
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def first_of_next_month(today: date | None = None) -> date:
    """1st of the month after `today` (e.g. 15-12-2026 -> 01-01-2027)."""
    today = today or date.today()
    return date(today.year + today.month // 12, today.month % 12 + 1, 1)

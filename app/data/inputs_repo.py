"""
inputs_repo.py - Monthly inputs and the history of generated reports
====================================================================

WHAT THIS MODULE DOES
---------------------
Stores the figures that are NOT on the invoices but are needed for the
reports, entered once per month on the Monthly inputs screen:

    indirect costs        expense heads and amounts (Rent, Salaries, ...)
                          used by report 10 (indirect vs direct cost %) and
                          report 12 (profit & loss)
    high-profit threshold margin % at or above which a product appears in
                          report 9 (default 40%)

and the list of workbooks generated, shown on the History screen.

    costs(year, month)                 [(head, amount), ...] in screen order
    save_costs(year, month, rows)      replace the month's heads (logged)
    previous_costs(year, month)        the latest earlier month's heads,
                                       for "Copy from last month"
    threshold(year, month)             high-profit % (default 40)
    save_threshold(year, month, pct)   (logged)
    has_inputs(year, month)            were costs saved for the month?
    record_run(...) / runs()           generated workbooks, newest first

Every change is written to the audit log (master "Monthly inputs") with
old and new values, in the same transaction as the change.
"""

from __future__ import annotations

import json
from datetime import datetime

from app.data.invoices_repo import month_key, month_label
from app.data.masters_repo import MastersRepo
from app.utils import format_inr

DEFAULT_THRESHOLD = 40.0

# AUTOMATIC INDIRECT COSTS (v0.8.1, percentages editable from v0.8.2)
# -------------------------------------------------------------------
# Two indirect expenses are worked out from the month's COGS (product cost
# + labour) instead of being typed in. (setting key, head, default % of
# COGS, word that marks the same head if typed on Monthly inputs.)
# The percentages are ONE setting for all months (stored in
# monthly_settings under the month "all"), because the client's rule is
# "every month" and Brinda asked for it to apply to earlier months too. A
# change is logged in the audit log and applies to every report generated
# afterwards, whichever month it is for.
AUTO_HEADS = (
    ("auto_breakage_pct", "Breakage / returns / transport", 4.0, "breakage"),
    ("auto_compliance_pct", "Compliance GST", 3.0, "compliance"),
)
ALL_MONTHS = "all"
DEFAULT_HEADS = ("Rent", "Salaries", "Electricity", "Internet & phone",
                 "Marketing")


class InputsRepo:
    """Monthly inputs and report history, in the tool's database."""

    def __init__(self, masters: MastersRepo):
        self.masters = masters
        self.conn = masters.conn

    # ------------------------------------------------------------------
    # Indirect costs
    # ------------------------------------------------------------------
    def costs(self, year: int, month: int) -> list[tuple[str, float]]:
        return [(r["head"], float(r["amount"])) for r in self.conn.execute(
            "SELECT head, amount FROM monthly_costs WHERE month = ? "
            "ORDER BY position, head", (month_key(year, month),))]

    def has_inputs(self, year: int, month: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM monthly_costs WHERE month = ? LIMIT 1",
            (month_key(year, month),)).fetchone() is not None

    def previous_costs(self, year: int, month: int) -> tuple[str, list]:
        """(month label, heads) of the latest earlier month with costs, or
        ("", []) if there is none."""
        row = self.conn.execute(
            "SELECT month FROM monthly_costs WHERE month < ? "
            "ORDER BY month DESC LIMIT 1", (month_key(year, month),)).fetchone()
        if row is None:
            return "", []
        y, m = map(int, row["month"].split("-"))
        return month_label(y, m), self.costs(y, m)

    def save_costs(self, year: int, month: int,
                   rows: list[tuple[str, float]]) -> None:
        """
        Replace the month's cost heads. Heads must be unique (compared
        ignoring capitals and spaces) and amounts not negative; raises
        ValueError with a plain message otherwise. Changes are logged.
        """
        seen: set[str] = set()
        clean = []
        for head, amount in rows:
            head = " ".join(str(head).split())
            if not head:
                if amount:
                    raise ValueError("Every amount needs an expense head.")
                continue
            if head.lower() in seen:
                raise ValueError(f"“{head}” is entered twice.")
            if amount < 0:
                raise ValueError(f"{head}: the amount cannot be negative.")
            seen.add(head.lower())
            clean.append((head, round(float(amount), 2)))

        key = month_key(year, month)
        old = dict(self.costs(year, month))
        new = dict(clean)
        record = f"Indirect costs – {month_label(year, month)}"
        with self.conn:
            self.conn.execute("DELETE FROM monthly_costs WHERE month = ?", (key,))
            self.conn.executemany(
                "INSERT INTO monthly_costs(month, head, amount, position) "
                "VALUES (?, ?, ?, ?)",
                [(key, h, a, i) for i, (h, a) in enumerate(clean)])
            for head in list(old) + [h for h in new if h not in old]:
                before, after = old.get(head), new.get(head)
                if before == after:
                    continue
                self.masters._audit(
                    "inputs", None, record,
                    "Added" if before is None else "Deleted" if after is None
                    else "Edited", head,
                    "" if before is None else format_inr(before),
                    "" if after is None else format_inr(after), "Monthly inputs")

    # ------------------------------------------------------------------
    # High-profit threshold
    # ------------------------------------------------------------------
    def threshold(self, year: int, month: int) -> float:
        row = self.conn.execute(
            "SELECT value FROM monthly_settings WHERE month = ? AND "
            "key = 'high_profit_pct'", (month_key(year, month),)).fetchone()
        return float(row["value"]) if row else DEFAULT_THRESHOLD

    def save_threshold(self, year: int, month: int, pct: float) -> None:
        old = self.threshold(year, month)
        if abs(old - pct) < 1e-9 and self.conn.execute(
                "SELECT 1 FROM monthly_settings WHERE month = ? AND "
                "key = 'high_profit_pct'", (month_key(year, month),)).fetchone():
            return
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO monthly_settings(month, key, value) "
                "VALUES (?, 'high_profit_pct', ?)", (month_key(year, month), str(pct)))
            if abs(old - pct) > 1e-9:
                self.masters._audit(
                    "inputs", None, f"Report settings – {month_label(year, month)}",
                    "Edited", "High-profit threshold", f"{old:g}%", f"{pct:g}%",
                    "Monthly inputs")

    # ------------------------------------------------------------------
    # Automatic indirect costs (% of COGS) - one setting for all months
    # ------------------------------------------------------------------
    def auto_rates(self) -> dict[str, float]:
        """Setting key -> % of COGS (the defaults until changed)."""
        saved = {r["key"]: float(r["value"]) for r in self.conn.execute(
            "SELECT key, value FROM monthly_settings WHERE month = ?", (ALL_MONTHS,))}
        return {key: saved.get(key, default) for key, _, default, _ in AUTO_HEADS}

    def save_auto_rates(self, rates: dict[str, float]) -> None:
        """Save changed percentages (0-100); each change is logged."""
        old = self.auto_rates()
        with self.conn:
            for key, head, _, _ in AUTO_HEADS:
                if key not in rates:
                    continue
                pct = round(float(rates[key]), 2)
                if not 0 <= pct <= 100:
                    raise ValueError(f"{head}: the percentage must be between 0 and 100.")
                if abs(old[key] - pct) < 1e-9:
                    continue
                self.conn.execute(
                    "INSERT OR REPLACE INTO monthly_settings(month, key, value) "
                    "VALUES (?, ?, ?)", (ALL_MONTHS, key, str(pct)))
                self.masters._audit(
                    "inputs", None, "Report settings – all months", "Edited",
                    f"{head} (% of COGS)", f"{old[key]:g}%", f"{pct:g}%",
                    "Monthly inputs")

    # ------------------------------------------------------------------
    # Generated reports
    # ------------------------------------------------------------------
    def record_run(self, year: int, month: int, file_path: str, invoices: int,
                   left_out: int, sales: float, gross_profit: float,
                   payments_path: str, reports: list[str],
                   rto_path: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO report_runs(month, file_path, generated_at, user, "
                "invoices, left_out, sales, gross_profit, payments_path, "
                "reports_json, rto_path) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (month_key(year, month), file_path,
                 datetime.now().isoformat(timespec="seconds"), self.masters.user,
                 invoices, left_out, sales, gross_profit, payments_path,
                 json.dumps(reports), rto_path))

    def runs(self, latest_per_month: bool = True) -> list[dict]:
        """Generated workbooks, newest month first (by default only the
        latest run of each month)."""
        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM report_runs ORDER BY month DESC, generated_at DESC, id DESC")]
        if not latest_per_month:
            return rows
        seen, out = set(), []
        for r in rows:
            if r["month"] not in seen:
                seen.add(r["month"])
                out.append(r)
        return out
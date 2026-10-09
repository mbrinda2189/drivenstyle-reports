"""
daily_reports.py - Payout slip, summary, month check, Excel (v0.28.0)
=====================================================================

WHAT THIS MODULE DOES
---------------------
Four ways of LOOKING at the payout register. Nothing here changes it.

PAYOUT SLIP   GET /api/daily/slip            (page to print)
    "To pay": every Pending line, or "Paid on <date>": every line paid on
    that day - grouped as the desktop slip is (payout_app/slip.py, used as
    it is): one block per kind of labour, one per sales executive, then
    the internal team, each with its total, and a grand total.

SUMMARY       GET /api/daily/summary
    Pending and paid by person (register.pending_by_payee), paid by day,
    and by invoice month: due, paid, pending, on hold. Cancelled lines are
    never counted. Adjustment lines (after a re-issued invoice) are.

MONTH CHECK   GET /api/daily/month-check?month=YYYY-MM
    The control that ties the two tools together: for one month, the
    register's lines are set beside what the MONTHLY tool works out for the
    same month (reports/data.build_month - the figures of its Labour and
    Spot incentive sheets):
        labour by kind of work        must be equal
        spot incentive per executive  must be equal (exact amounts)
        internal team                 must be equal
    and, shown separately because it is NOT a difference:
        month-end rounding            the monthly report rounds each
                                      executive's total UP to the next
                                      Rs. 10; the daily lines are exact
                                      (Brinda, 05-10-2026).
    A difference almost always has one of two plain causes, so both are
    listed by invoice number:
        * an invoice in the monthly export that was never scanned daily
          (or is still In review / dated before the start date);
        * an invoice scanned daily that the monthly tool left out (open
          Scan review issue) or that is not in the export.
    A third cause is a master changed after posting: the register keeps
    the rate the line was posted with, the monthly tool uses the rate in
    force on the invoice date as the master says NOW.

EXCEL         GET /api/daily/export
    The register as a workbook: sheet "Payouts" (every line) and sheet
    "Invoices" (every invoice scanned, with its state).

All four are open to staff and admins: they show labour and incentive,
which staff handle anyway - no cost or profit.
"""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from html import escape
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import OTHERS, InvoicesRepo, month_label
from app.data.masters_repo import MastersRepo
from app.reports.data import LABOUR_GROUPS, build_month, labour_group, round_up_10
from payout_app import engine, register, slip
from web.backend.payout_store import PayoutStore

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SLIP_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1B2A41; margin: 24px; font-size: 14px; }}
  table {{ border-collapse: collapse; margin-bottom: 14px; }}
  button {{ font: inherit; font-weight: 600; min-height: 44px; padding: 0 18px; border-radius: 8px;
           border: 0; background: #1F5FBF; color: #fff; cursor: pointer; margin-bottom: 16px; }}
  @media print {{ button {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<button onclick="window.print()">Print</button>
{body}
</body></html>"""


def _money(value: float) -> float:
    return round(value, 2) + 0.0


def add_routes(api: FastAPI, connection, current_user) -> None:
    """Attach the addresses (all read-only, for every signed-in person)."""

    def month(text: str) -> tuple[int, int]:
        try:
            year, mon = map(int, text.split("-"))
            date(year, mon, 1)
            return year, mon
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "That is not a month.") from exc

    # ---- payout slip --------------------------------------------------------------
    @api.get("/api/daily/slip", response_class=HTMLResponse)
    def payout_slip(paid_on: str = "", who: dict = Depends(current_user)) -> str:
        day = None
        if paid_on:
            try:
                day = date.fromisoformat(paid_on)
            except ValueError as exc:
                raise HTTPException(400, "That is not a date.") from exc
        with connection() as conn:
            sheet = slip.build(PayoutStore(conn, who["email"]).lines(), day)
        return SLIP_PAGE.format(title=escape(f"Payout slip - {sheet.title}"),
                                body=slip.to_html(sheet))

    # ---- summary --------------------------------------------------------------------
    @api.get("/api/daily/summary")
    def summary(who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            rows = store.payout_rows()[1]
        lines = [l for l in register.payout_lines(rows) if l["status"] != register.CANCELLED]
        by_day: dict[date, list[float]] = {}
        by_month: dict[str, dict[str, float]] = {}
        for l in lines:
            if l["status"] == register.PAID and l["paid_date"]:
                slot = by_day.setdefault(l["paid_date"], [0, 0.0])
                slot[0] += 1
                slot[1] += l["amount"]
            if l["invoice_date"]:
                key = f"{l['invoice_date']:%Y-%m}"
                m = by_month.setdefault(key, {"due": 0.0, "paid": 0.0, "pending": 0.0, "hold": 0.0})
                m["due"] += l["amount"]
                m[{register.PAID: "paid", register.HOLD: "hold"}.get(l["status"], "pending")] += l["amount"]
        return {
            "by_payee": [{"type": t, "payee": p, "pending": pending, "paid": paid}
                         for t, p, pending, paid in register.pending_by_payee(rows)],
            "by_day": [{"date": d.isoformat(), "lines": n, "amount": _money(a)}
                       for d, (n, a) in sorted(by_day.items(), reverse=True)],
            "by_month": [{"month": key, "label": month_label(*map(int, key.split("-"))),
                          **{k: _money(v) for k, v in m.items()}}
                         for key, m in sorted(by_month.items(), reverse=True)]}

    # ---- month check ------------------------------------------------------------------
    @api.get("/api/daily/month-check")
    def month_check(month_text: str = "", who: dict = Depends(current_user)) -> dict:
        year, mon = month(month_text)
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            lines = [l for l in store.lines() if l["status"] != register.CANCELLED
                     and l["invoice_date"] and (l["invoice_date"].year, l["invoice_date"].month) == (year, mon)]
            states = {i["invoice_no"]: i["state"] for i in store.invoices()}
            start = store.start_date()
            masters = MastersRepo(conn, who["email"])
            invoices = InvoicesRepo(masters)
            read = invoices.scan_run(year, mon) is not None
            data = build_month(masters, invoices, InputsRepo(masters), year, mon) if read else None

        # The register's side.
        reg_labour = {engine.LABOUR_TYPE[g]: 0.0 for g in LABOUR_GROUPS}
        reg_incentive: dict[str, float] = {}
        reg_internal = 0.0
        for l in lines:
            if engine.is_labour(l["type"]):
                reg_labour[l["type"]] = reg_labour.get(l["type"], 0.0) + l["amount"]
            elif l["type"] == engine.INCENTIVE:
                reg_incentive[l["payee"]] = reg_incentive.get(l["payee"], 0.0) + l["amount"]
            elif l["type"] == engine.INTERNAL:
                reg_internal += l["amount"]
        in_register = {l["invoice_no"] for l in lines}

        out = {"month": f"{year:04d}-{mon:02d}", "label": month_label(year, mon),
               "monthly_read": read, "start_date": start.isoformat(),
               "register_invoices": len(in_register), "rows": [], "rounding": None,
               "not_scanned": [], "not_in_monthly": [], "left_out": []}
        if data is None:
            out["rows"] = (
                [{"group": "Labour", "label": t, "register": _money(a), "monthly": None,
                  "difference": None} for t, a in reg_labour.items() if a]
                + [{"group": "Spot incentive", "label": p, "register": _money(a), "monthly": None,
                    "difference": None} for p, a in sorted(reg_incentive.items())]
                + ([{"group": "Internal team", "label": engine.INTERNAL,
                     "register": _money(reg_internal), "monthly": None, "difference": None}]
                   if reg_internal else []))
            return out

        # The monthly tool's side - the same figures its sheets are written from.
        mon_labour = {engine.LABOUR_TYPE[g]: 0.0 for g in LABOUR_GROUPS}
        for line in data.lines:
            if line.labour:
                mon_labour[engine.LABOUR_TYPE[labour_group(line.product)]] += line.labour
        mon_incentive: dict[str, float] = {}
        for inv in data.invoices:
            if inv.incentive_payable > 0:
                payee = inv.executive              # named as engine.calculate names the payee
                if payee == OTHERS and inv.printed_executive:
                    payee = f"{OTHERS} ({inv.printed_executive})"
                mon_incentive[payee] = mon_incentive.get(payee, 0.0) + inv.incentive_payable

        def row(group: str, label: str, ours: float, theirs: float) -> dict:
            return {"group": group, "label": label, "register": _money(ours),
                    "monthly": _money(theirs), "difference": _money(ours - theirs)}

        rows = [row("Labour", t, reg_labour.get(t, 0.0), mon_labour.get(t, 0.0))
                for t in sorted(set(reg_labour) | set(mon_labour), key=lambda t: (t not in mon_labour, t))
                if reg_labour.get(t) or mon_labour.get(t)]
        rows += [row("Spot incentive", p, reg_incentive.get(p, 0.0), mon_incentive.get(p, 0.0))
                 for p in sorted(set(reg_incentive) | set(mon_incentive), key=str.lower)]
        if reg_internal or data.internal_incentive:
            rows.append(row("Internal team", engine.INTERNAL, reg_internal, data.internal_incentive))
        exact = sum(mon_incentive.values())
        out["rows"] = rows
        out["totals"] = {
            "register": _money(sum(r["register"] for r in rows)),
            "monthly": _money(sum(r["monthly"] for r in rows)),
            "difference": _money(sum(r["difference"] for r in rows))}
        # Not a difference: the monthly report rounds each executive up to Rs. 10.
        out["rounding"] = {"exact": _money(exact), "rounded": _money(data.incentive_payable),
                           "amount": _money(data.incentive_payable - exact),
                           "by_payee": [{"payee": p, "exact": _money(a), "rounded": round_up_10(a)}
                                        for p, a in sorted(mon_incentive.items(), key=lambda kv: kv[0].lower())]}
        with_lines = {i.invoice_no for i in data.invoices
                      if i.labour or i.incentive_payable > 0 or i.internal_incentive}
        out["not_scanned"] = [
            {"invoice_no": n, "why": states.get(n, "") or (
                "Dated before the start date" if next(
                    i for i in data.invoices if i.invoice_no == n).invoice_date < start
                else "Not scanned")}
            for n in sorted(with_lines - in_register)]
        monthly_numbers = {i.invoice_no for i in data.invoices}
        left = {l.invoice_no for l in data.left_out}
        out["left_out"] = sorted(in_register & left)
        out["not_in_monthly"] = sorted(in_register - monthly_numbers - left)
        return out

    # ---- Excel --------------------------------------------------------------------------
    @api.get("/api/daily/export")
    def export(who: dict = Depends(current_user)):
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            lines, invoices = store.lines(), store.invoices()
        book = Workbook()
        head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="0B2545")

        def sheet(ws, headings: list[str], rows: list[list], widths: list[int]) -> None:
            ws.append(headings)
            for cell in ws[1]:
                cell.font, cell.fill = head_font, head_fill
            for r in rows:
                ws.append(r)
            for i, width in enumerate(widths, start=1):
                ws.column_dimensions[ws.cell(1, i).column_letter].width = width
            ws.freeze_panes = "A2"

        ws = book.active
        ws.title = "Payouts"
        sheet(ws, ["Line ID", "Invoice no", "Invoice date", "Customer", "Car", "Type", "Pay to",
                   "Amount", "Working", "Status", "Paid date", "Mode", "Reference", "Proof",
                   "Remarks", "Entered by", "Entered at"],
              [[l["line_id"], l["invoice_no"], l["invoice_date"], l["customer"], l["car"],
                l["type"], l["payee"], l["amount"], l["working"], l["status"], l["paid_date"],
                l["mode"], l["reference"], l["proof"], l["remarks"], l["entered_by"],
                l["entered_at"]] for l in lines],
              [22, 16, 13, 28, 18, 20, 20, 12, 50, 11, 13, 12, 18, 30, 30, 26, 17])
        for row in ws.iter_rows(min_row=2):
            row[2].number_format = row[10].number_format = "DD-MM-YYYY"
            row[7].number_format = "#,##0.00"
        sheet(book.create_sheet("Invoices"),
              ["Invoice no", "Invoice date", "Customer", "Total", "Salesperson", "File name",
               "State", "Reason", "Scanned by", "Scanned at"],
              [[i["invoice_no"], i["invoice_date"], i["customer"], i["total"], i["salesperson"],
                i["file_name"], i["state"], i["reason"], i["scanned_by"], i["scanned_at"]]
               for i in invoices], [16, 13, 28, 12, 22, 30, 12, 50, 26, 17])
        with tempfile.TemporaryDirectory(prefix="dns_register_") as folder:
            path = Path(folder) / "register.xlsx"
            book.save(path)
            data = path.read_bytes()
        name = f"DriveNStyle_Payout_register_{datetime.now():%d-%m-%Y_%H%M}.xlsx"
        return Response(data, media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

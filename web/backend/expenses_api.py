"""
expenses_api.py - Zoho expense upload for Monthly inputs (v0.32.0)
==================================================================

WHAT THIS MODULE DOES
---------------------
The addresses behind the "Upload Zoho expenses" part of the Monthly inputs
screen. Brinda (10-11-2026) asked to upload Zoho's Expense export instead of
typing every head, with the tool sorting the accounts into heads.

    POST /api/monthly/{month}/expenses?filename=...   (the file as the body)
        Checks the file (app/data/expenses_io.read_expenses) and keeps it as
        months/<YYYY-MM>/expenses.<ext>, then answers with the PREVIEW below.
        Nothing is saved to the month's inputs yet.

    GET  /api/monthly/{month}/expenses
        The preview of the month's kept file, or {"file": null}.

    POST /api/monthly/{month}/expenses/apply   {"matches": {account: head}}
        Saves what the user confirmed:
          1. the account -> head matches, remembered for later months
             (inputs_repo.save_expense_matches, logged);
          2. the month's expense heads = the file's accounts added up per
             head (inputs_repo.save_costs - REPLACES the month's heads,
             logged), amounts EXCLUDING GST;
          3. the month's labour as booked in Zoho, by kind - the accounts
             marked "(labour)" - shown beside the tool's labour in the P&L
             (inputs_repo.save_books_labour, logged).
        The high-profit threshold is left as it is.

PREVIEW
    file          {name, at, by} of the kept file
    accounts      one row per Zoho account in the month: account, amount
                  (excl. GST), gst, rows, head (the saved match, or the
                  first suggestion - expenses_io.suggest_head), saved (was
                  the head saved before?), labour_kind
    heads         head names to choose from (usual heads, this and last
                  month's, every head used in a saved match)
    labour, not_used   the two special choices
    total, other_months, no_date   totals and rows left out (other months /
                  no date) so the user sees the file was read in full

WHO MAY USE IT: admins only, like everything on Monthly reports.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.data.expenses_io import (
    LABOUR, NOT_USED, ExpenseFileError, head_totals, labour_totals, read_expenses,
    suggest_head)
from app.data.inputs_repo import DEFAULT_HEADS, InputsRepo
from app.data.masters_repo import MastersRepo

EXTENSIONS = (".xlsx", ".csv")
MAX_BYTES = 30 * 1024 * 1024
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def ym(text: str) -> tuple[int, int]:
    """ "YYYY-MM" -> (year, month); anything else is "not found" (as monthly_api)."""
    m = _MONTH.match(text)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise HTTPException(404, "That is not a month.")
    return int(m.group(1)), int(m.group(2))


class ApplyBody(BaseModel):
    matches: dict[str, str]


def add_routes(api: FastAPI, connection, admin, data_dir: Path) -> None:
    """Attach the addresses. `data_dir` is the web tool's data folder."""
    months_dir = data_dir / "months"

    def note_path(month: str) -> Path:
        return months_dir / month / "expenses.json"

    def kept(month: str) -> tuple[Path, dict] | None:
        path = note_path(month)
        if not path.is_file():
            return None
        note = json.loads(path.read_text(encoding="utf-8"))
        file = months_dir / month / note["stored"]
        return (file, note) if file.is_file() else None

    def preview(month: str, who: dict) -> dict:
        year, mon = ym(month)
        found = kept(month)
        if not found:
            return {"file": None}
        file, note = found
        try:
            data = read_expenses(file, year, mon)
        except ExpenseFileError as exc:
            raise HTTPException(400, str(exc)) from exc
        with connection() as conn:
            inputs = InputsRepo(MastersRepo(conn, user=who["email"]))
            saved = inputs.expense_matches()
            _, before = inputs.previous_costs(year, mon)
            known = list(dict.fromkeys(
                list(DEFAULT_HEADS) + [h for h, _ in inputs.costs(year, mon)]
                + [h for h, _ in before]
                + [h for h in saved.values() if h not in (LABOUR, NOT_USED)]))
        rows = []
        for a in data.accounts:
            head = saved.get(a.account.lower())
            rows.append({"account": a.account, "amount": a.amount, "gst": a.gst, "rows": a.rows,
                         "head": head or suggest_head(a.account, a.descriptions, known),
                         "saved": head is not None, "labour_kind": a.labour_kind})
        heads = list(dict.fromkeys(known + [r["head"] for r in rows
                                            if r["head"] not in (LABOUR, NOT_USED)]))
        return {"file": {"name": note["name"], "at": note["at"], "by": note["by"]},
                "accounts": rows, "heads": heads, "labour": LABOUR, "not_used": NOT_USED,
                "total": data.total, "other_months": data.other_months,
                "no_date": data.no_date}

    @api.post("/api/monthly/{month}/expenses")
    async def upload(month: str, request: Request, filename: str,
                     who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        name = Path(filename.replace("\\", "/")).name or "expenses"
        ext = Path(name).suffix.lower()
        if ext not in EXTENSIONS:
            raise HTTPException(400, "Zoho expenses: choose the .xlsx or .csv export.")
        body = await request.body()
        if not body:
            raise HTTPException(400, "The file is empty.")
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "The file is larger than 30 MB.")
        folder = months_dir / month
        folder.mkdir(parents=True, exist_ok=True)
        trial = folder / f"expenses.new{ext}"
        trial.write_bytes(body)
        try:                               # checked before it replaces the kept file
            read_expenses(trial, year, mon)
        except ExpenseFileError as exc:
            trial.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
        for old in folder.glob("expenses.*"):
            if old != trial and old.suffix != ".json":
                old.unlink(missing_ok=True)
        final = folder / f"expenses{ext}"
        trial.replace(final)
        note_path(month).write_text(json.dumps({
            "name": name, "stored": final.name, "by": who["email"],
            "at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
        return preview(month, who)

    @api.get("/api/monthly/{month}/expenses")
    def get_preview(month: str, who: dict = Depends(admin)) -> dict:
        return preview(month, who)

    @api.post("/api/monthly/{month}/expenses/apply")
    def apply(month: str, body: ApplyBody, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        found = kept(month)
        if not found:
            raise HTTPException(400, "Upload the Zoho expense file first.")
        try:
            data = read_expenses(found[0], year, mon)
        except ExpenseFileError as exc:
            raise HTTPException(400, str(exc)) from exc
        # Every account in the file needs a head; matches for accounts not in
        # the file are ignored (the screen only sends the file's accounts).
        given = {k.lower(): " ".join(str(v).split()) for k, v in body.matches.items()}
        missing = [a.account for a in data.accounts if not given.get(a.account.lower())]
        if missing:
            raise HTTPException(400, "Choose a head for: " + ", ".join(missing))
        matches = {a.account: given[a.account.lower()] for a in data.accounts}
        lower = {k.lower(): v for k, v in matches.items()}
        # Saved largest first, so the Monthly inputs table reads like a P&L.
        heads = dict(sorted(head_totals(data.accounts, lower).items(), key=lambda h: -h[1]))
        labour = labour_totals(data.accounts, lower)
        with connection() as conn:
            inputs = InputsRepo(MastersRepo(conn, user=who["email"]))
            try:
                inputs.save_costs(year, mon, list(heads.items()))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            inputs.save_expense_matches(matches)
            inputs.save_books_labour(year, mon, labour)
        return {"heads": [[h, a] for h, a in heads.items()],
                "labour": labour, "total": round(sum(heads.values()), 2)}

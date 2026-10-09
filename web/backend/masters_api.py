"""
masters_api.py - Masters and the audit log for the web screens (v0.24.0)
========================================================================

WHAT THIS MODULE DOES
---------------------
Gives the Masters and Audit log screens their data. It contains NO rule of
its own: every check (no duplicates, 10-digit contact number, amounts not
negative, an incentive group must exist, the last dated amount cannot be
removed ...) and every audit entry comes from the desktop tool's own
`app/data/masters_repo.py`, used exactly as it is. This file only turns
what the browser sends into the calls that module already has, and its
answers into what a browser can read (dates as text, and so on).

THE FIVE MASTERS (app/data/master_defs.py)
    products, executives, cars, incentives, package_items
    The screens draw their columns and edit forms from GET /api/masters, so
    a field added to master_defs.py appears on the web without a change here.

ADDRESSES
    GET    /api/masters                          the masters, their fields, row counts
    GET    /api/masters/{master}/rows            every row (+ names for drop-downs)
    POST   /api/masters/{master}/rows            add a row
    PUT    /api/masters/{master}/rows/{id}       change a row
    POST   /api/masters/{master}/active          mark rows active / inactive
    POST   /api/masters/{master}/delete          delete rows
    POST   /api/masters/{master}/delete-all      delete every row (needs "DELETE")
    GET    /api/masters/{master}/rows/{id}/rates the dated amounts of a row
    POST   /api/masters/{master}/rows/{id}/rates/delete   remove one dated set
    GET    /api/audit                            audit entries          (admin)
    GET    /api/audit/export                     the same, as Excel     (admin)

WHO MAY DO WHAT (Brinda, 09-10-2026)
    Masters: every signed-in person, staff included - they enter cost
    prices and rates. Audit log: admins only. Whoever makes a change, their
    e-mail address is written in the audit log beside it.

DATED AMOUNTS
    Selling price, cost price, labour charge, incentive amount and bill
    value keep a history. When one of them is changed the screen sends the
    date the new amount applies from ("effective_from"); reports for an
    earlier month keep using the earlier amount. No date sent = today.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.data.excel_io import export_audit
from app.data.master_defs import ALL_MASTERS, MASTERS_BY_KEY, MasterDef
from app.data.masters_repo import MasterError, MastersRepo, RowChange

AUDIT_LIMIT = 1000            # rows shown on the Audit log screen at once
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class RowBody(BaseModel):
    values: dict
    effective_from: str | None = None       # YYYY-MM-DD; None = today


class IdsBody(BaseModel):
    ids: list[int]
    active: bool | None = None


class ConfirmBody(BaseModel):
    confirm: str


class RateBody(BaseModel):
    effective_from: str


def _day(text: str | None, what: str = "date") -> date | None:
    """ "2026-10-09" -> a date; a plain refusal for anything else."""
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(400, f"“{text}” is not a {what} (expected YYYY-MM-DD).") from exc


def _json(value):
    """A value as the browser gets it: a date becomes "YYYY-MM-DD" text."""
    return value.isoformat() if isinstance(value, date) else value


def _row(row: dict) -> dict:
    return {key: _json(value) for key, value in row.items()}


def _definition(mdef: MasterDef) -> dict:
    """A master's shape, for the screen to draw its table and edit form from."""
    return {
        "key": mdef.key, "title": mdef.title, "singular": mdef.singular,
        "filter_field": mdef.filter_field, "has_rates": mdef.has_rates,
        "fields": [{"key": f.key, "label": f.label, "kind": f.kind,
                    "required": f.required, "choices": list(f.choices),
                    "open_choice": f.open_choice, "lookup": f.lookup,
                    "dated": f.dated, "default": _json(f.default)}
                   for f in mdef.fields],
    }


def _refuse(exc: MasterError) -> HTTPException:
    """The repository's list of plain sentences, one per line."""
    problems = exc.args[0] if exc.args else ["Could not save."]
    if isinstance(problems, str):
        problems = [problems]
    return HTTPException(400, "\n".join(problems))


def add_routes(api: FastAPI, connection, current_user, admin) -> None:
    """Attach the addresses to the server. `connection` opens the database
    for one request; `current_user` / `admin` are main.py's role checks."""

    def known(master: str) -> MasterDef:
        if master not in MASTERS_BY_KEY:
            raise HTTPException(404, "There is no such master.")
        return MASTERS_BY_KEY[master]

    def clean(mdef: MasterDef, values: dict) -> dict:
        """Only the master's own fields; the date and id are never typed."""
        keys = {f.key for f in mdef.fields if f.kind != "date"}
        return {k: v for k, v in values.items() if k in keys}

    # ---- reading -------------------------------------------------------------
    @api.get("/api/masters")
    def masters(who: dict = Depends(current_user)) -> list[dict]:
        with connection() as conn:
            out = []
            for mdef in ALL_MASTERS:
                total, active = conn.execute(
                    f"SELECT COUNT(*), COALESCE(SUM(active), 0) FROM {mdef.key}").fetchone()
                out.append({**_definition(mdef), "rows": total, "active_rows": active})
            return out

    @api.get("/api/masters/{master}/rows")
    def rows(master: str, who: dict = Depends(current_user)) -> dict:
        mdef = known(master)
        with connection() as conn:
            repo = MastersRepo(conn, user=who["email"])
            lookups = {f.lookup: repo.lookup_names(f.lookup)
                       for f in mdef.fields if f.kind == "lookup"}
            return {"rows": [_row(r) for r in repo.list_rows(master)], "lookups": lookups}

    @api.get("/api/masters/{master}/rows/{row_id}/rates")
    def rates(master: str, row_id: int, who: dict = Depends(current_user)) -> list[dict]:
        if not known(master).has_rates:
            return []
        with connection() as conn:
            return [_row(r) for r in MastersRepo(conn, who["email"]).rate_history(master, row_id)]

    # ---- writing -------------------------------------------------------------
    @api.post("/api/masters/{master}/rows", status_code=201)
    def add_row(master: str, body: RowBody, who: dict = Depends(current_user)) -> dict:
        mdef = known(master)
        values = {f.key: f.default for f in mdef.fields if f.kind != "date"}
        values.update(clean(mdef, body.values))
        with connection() as conn:
            repo = MastersRepo(conn, user=who["email"])
            try:
                repo.save(master, [RowChange(None, values, _day(body.effective_from))])
            except MasterError as exc:
                raise _refuse(exc) from exc
            return _row(repo.get(master, repo.find_id(master, values)))

    @api.put("/api/masters/{master}/rows/{row_id}")
    def change_row(master: str, row_id: int, body: RowBody,
                   who: dict = Depends(current_user)) -> dict:
        mdef = known(master)
        with connection() as conn:
            repo = MastersRepo(conn, user=who["email"])
            stored = repo.get(master, row_id)
            if stored is None:
                raise HTTPException(404, "This row is no longer in the master. "
                                         "Someone may have deleted it.")
            # What the screen did not send keeps its stored value.
            values = {**clean(mdef, stored), **clean(mdef, body.values)}
            try:
                repo.save(master, [RowChange(row_id, values, _day(body.effective_from))])
            except MasterError as exc:
                raise _refuse(exc) from exc
            return _row(repo.get(master, row_id))

    @api.post("/api/masters/{master}/active")
    def set_active(master: str, body: IdsBody, who: dict = Depends(current_user)) -> dict:
        known(master)
        if body.active is None:
            raise HTTPException(400, "Say whether the rows become active or inactive.")
        with connection() as conn:
            changed = MastersRepo(conn, who["email"]).set_active(master, body.ids, body.active)
        return {"changed": changed}

    @api.post("/api/masters/{master}/delete")
    def delete_rows(master: str, body: IdsBody, who: dict = Depends(current_user)) -> dict:
        known(master)
        with connection() as conn:
            return {"deleted": MastersRepo(conn, who["email"]).delete(master, body.ids)}

    @api.post("/api/masters/{master}/delete-all")
    def delete_all(master: str, body: ConfirmBody, who: dict = Depends(current_user)) -> dict:
        """Every row of one master. The word DELETE must be typed (as on the
        desktop); the audit log keeps what each deleted row held."""
        known(master)
        if body.confirm != "DELETE":
            raise HTTPException(400, "Type DELETE (in capitals) to delete every row.")
        with connection() as conn:
            repo = MastersRepo(conn, who["email"])
            ids = [r["id"] for r in repo.list_rows(master)]
            return {"deleted": repo.delete(master, ids, source="Masters screen (Delete all)")}

    @api.post("/api/masters/{master}/rows/{row_id}/rates/delete")
    def delete_rate(master: str, row_id: int, body: RateBody,
                    who: dict = Depends(current_user)) -> list[dict]:
        if not known(master).has_rates:
            raise HTTPException(400, "This master has no dated amounts.")
        with connection() as conn:
            repo = MastersRepo(conn, who["email"])
            try:
                repo.delete_rate(master, row_id, _day(body.effective_from))
            except MasterError as exc:
                raise _refuse(exc) from exc
            return [_row(r) for r in repo.rate_history(master, row_id)]

    # ---- audit log (admin) -----------------------------------------------------
    def entries(conn, master, action, date_from, date_to, text, limit):
        return MastersRepo(conn, "").audit_entries(
            master or None, action or None, _day(date_from), _day(date_to), text, limit)

    @api.get("/api/audit")
    def audit(master: str = "", action: str = "", date_from: str = "", date_to: str = "",
              text: str = "", who: dict = Depends(admin)) -> dict:
        with connection() as conn:
            found = entries(conn, master, action, date_from, date_to, text, AUDIT_LIMIT + 1)
            names = [r[0] for r in conn.execute(
                "SELECT DISTINCT master FROM audit_log ORDER BY master")]
        titles = {m.key: m.title for m in ALL_MASTERS}
        return {"entries": found[:AUDIT_LIMIT], "more": len(found) > AUDIT_LIMIT,
                "limit": AUDIT_LIMIT,
                "masters": [{"key": n, "title": titles.get(n, n.capitalize())} for n in names]}

    @api.get("/api/audit/export")
    def audit_export(master: str = "", action: str = "", date_from: str = "",
                     date_to: str = "", text: str = "", who: dict = Depends(admin)):
        """Every entry the filters give (no limit), as an Excel file."""
        with connection() as conn:
            found = entries(conn, master, action, date_from, date_to, text, None)
        with tempfile.TemporaryDirectory(prefix="dns_audit_") as folder:
            path = Path(folder) / "audit.xlsx"
            export_audit(found, path, {m.key: m.title for m in ALL_MASTERS})
            data = path.read_bytes()
        name = f"DriveNStyle_Audit_log_{date.today():%d-%m-%Y}.xlsx"
        return Response(data, media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

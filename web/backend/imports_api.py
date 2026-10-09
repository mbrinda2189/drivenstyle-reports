"""
imports_api.py - Masters from and to Excel, for the web screens (v0.25.0)
=========================================================================

WHAT THIS MODULE DOES
---------------------
The browser's version of Masters > Import Excel and Export. As with the
rest of the server it holds no rule of its own: the sheet is read, its
columns matched, its rows checked and saved by the desktop tool's own
`app/data/excel_io.py` and `app/data/masters_repo.py`.

THE IMPORT, STEP BY STEP
    1. UPLOAD    The file is sent to the server and kept in a private
                 folder under a random name (the "token"). Nothing is saved
                 to the masters yet.
    2. PREVIEW   The server finds the heading row, suggests which column
                 is which field (last time's matches first), and answers
                 with the first rows AS THEY WILL BE SAVED and the rows
                 that will be left out, with the reason. Every time a
                 column match or the sheet is changed, the screen asks
                 again.
    3. IMPORT    Only now are rows added / updated - in one transaction,
                 each with an audit entry "Import: <file name>" and the
                 e-mail of the person. The column matches are remembered.
                 The uploaded file is then deleted.

ZOHO'S ITEM LIST (Items > Export in Zoho Books)
    Recognised by its headings; the columns are pre-set; the Rs. 1 labour
    items are left out; the amounts are final from the date given (later
    dated amounts are removed). Afterwards the products of the tool that
    are NOT in Zoho's list are shown. REMOVING THEM IS FOR ADMINS ONLY
    (Brinda, 09-10-2026) - it can delete many products at once. The server
    keeps the list it found with the token, so "remove" can only ever
    delete exactly those products, whatever the browser sends.

THE UPLOADED FILE
    * .xlsx or .csv, at most 20 MB; old .xls is refused with the advice to
      save it as .xlsx (excel_io.read_sheet).
    * It belongs to the person who uploaded it: nobody else's token works.
    * It is deleted after the import or on Cancel, and in any case after
      one hour. It is never kept.

EXPORT
    POST /api/masters/{master}/export with the ids of the rows the screen
    shows (its search and filters applied) -> an .xlsx in the desktop
    layout, e.g. Products_09-10-2026.xlsx. No ids = every row.

ADDRESSES
    POST   /api/masters/{master}/import/upload?filename=...   (file as the body)
    POST   /api/masters/{master}/import/{token}/preview
    POST   /api/masters/{master}/import/{token}/run
    POST   /api/masters/{master}/import/{token}/remove-missing      (admin)
    DELETE /api/masters/{master}/import/{token}
    POST   /api/masters/{master}/export
"""

from __future__ import annotations

import json
import re
import secrets
import tempfile
import time
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.data.excel_io import (
    ImportFileError, convert_rows, export_rows, is_zoho_item_export, read_sheet,
    suggest_mapping, zoho_item_mapping)
from app.data.master_defs import MASTERS_BY_KEY, MasterDef
from app.data.masters_repo import MastersRepo
from app.utils import first_of_next_month

MAX_BYTES = 20 * 1024 * 1024          # largest file accepted
KEEP_SECONDS = 60 * 60                # an uploaded file lives one hour at most
PREVIEW_ROWS = 5
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,80}$")

# What happens when an optional field is not in the sheet - shown beside its
# column chooser. The same sentences as the desktop dialog
# (app/widgets/import_dialog.py, which cannot be imported here: it is Qt).
FALLBACK_HINTS = {
    "category": "Not in sheet? Worked out from the HSN/SAC code.",
    "has_labour": "Not in sheet? Yes when the labour charge is above zero.",
    "active": "Not in sheet? Every imported row is active.",
    "incentive_group": "Must match a name in the Incentive master.",
}
ZOHO_NOTE = ("Zoho item list recognised. Names, SKU, HSN/SAC, prices and category "
             "(goods / service) come from Zoho. Labour, incentive group and “Vehicle "
             "needed” stay as they are in the tool. The ₹1 labour items are left out. "
             "After the import the products that are not in Zoho's list are shown.")


def financial_year_start(today: date | None = None) -> date:
    """1st April of the current Indian financial year."""
    today = today or date.today()
    return date(today.year if today.month >= 4 else today.year - 1, 4, 1)


def _plural(n: int, word: str = "row") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class PreviewBody(BaseModel):
    sheet: str | None = None
    mapping: dict[str, str | None] | None = None      # None = suggest it


class RunBody(BaseModel):
    sheet: str | None = None
    mapping: dict[str, str | None]
    effective_from: str | None = None
    add_new: bool = True


class ExportBody(BaseModel):
    ids: list[int] | None = None


def add_routes(api: FastAPI, connection, current_user, admin, uploads: Path) -> None:
    """Attach the addresses. `uploads` is the private folder for uploaded sheets."""

    def known(master: str) -> MasterDef:
        if master not in MASTERS_BY_KEY:
            raise HTTPException(404, "There is no such master.")
        return MASTERS_BY_KEY[master]

    # ---- the uploaded file ----------------------------------------------------
    def sweep() -> None:
        """Delete uploads older than an hour (called at every upload)."""
        if uploads.is_dir():
            for path in uploads.iterdir():
                if time.time() - path.stat().st_mtime > KEEP_SECONDS:
                    path.unlink(missing_ok=True)

    def note_path(token: str) -> Path:
        return uploads / f"{token}.json"

    def find(master: str, token: str, who: dict) -> dict:
        """The upload's notes - only for the person who uploaded it."""
        gone = HTTPException(404, "This upload is no longer on the server (it is kept "
                                  "for one hour). Choose the file again.")
        if not _TOKEN.match(token) or not note_path(token).is_file():
            raise gone
        note = json.loads(note_path(token).read_text(encoding="utf-8"))
        if note["user_id"] != who["id"] or note["master"] != master:
            raise gone
        return note

    def forget(token: str) -> None:
        for path in uploads.glob(f"{token}.*"):
            path.unlink(missing_ok=True)

    def read(mdef: MasterDef, note: dict, sheet: str | None):
        try:
            return read_sheet(uploads / note["stored"], mdef, sheet)
        except ImportFileError as exc:
            raise HTTPException(400, str(exc)) from exc

    def state(mdef: MasterDef, token: str, note: dict, repo: MastersRepo,
              sheet_name: str | None, mapping: dict | None) -> dict:
        """Everything the import window shows, for the given sheet and matches."""
        sheet = read(mdef, note, sheet_name)
        zoho = mdef.key == "products" and is_zoho_item_export(sheet.headers)
        if mapping is None:
            mapping = (zoho_item_mapping(sheet.headers) if zoho else
                       suggest_mapping(mdef, sheet.headers, repo.get_mapping(mdef.key)))
        # Only the master's importable fields, and only headings of this sheet.
        mapping = {f.key: (mapping.get(f.key) if mapping.get(f.key) in sheet.headers else None)
                   for f in mdef.importable_fields}
        records, problems = convert_rows(mdef, sheet, mapping)
        count = len(MastersRepo.split_zoho_items(records)[0]) if zoho else len(records)
        shown = [f for f in mdef.importable_fields if mapping.get(f.key)]
        default = None
        if mdef.has_rates:
            first_load = not repo.list_rows(mdef.key)
            default = (financial_year_start() if zoho or first_load
                       else first_of_next_month()).isoformat()
        return {
            "token": token, "file_name": note["file_name"],
            "sheet": sheet.sheet, "sheet_names": sheet.sheet_names,
            "header_row": sheet.header_row, "data_rows": len(sheet.rows),
            "headers": sheet.headers, "mapping": mapping,
            "fields": [{"key": f.key, "label": f.label, "required": f.required,
                        "kind": f.kind, "hint": FALLBACK_HINTS.get(f.key, "")}
                       for f in mdef.importable_fields],
            "missing": [f.label for f in mdef.importable_fields
                        if f.required and not mapping.get(f.key)],
            "preview_fields": [f.key for f in shown],
            "preview": [{f.key: rec.get(f.key) for f in shown}
                        for rec in records[:PREVIEW_ROWS]],
            "count": count, "problems": problems,
            "is_zoho": zoho, "zoho_note": ZOHO_NOTE if zoho else "",
            "has_rates": mdef.has_rates, "default_date": default,
            "can_choose_add_new": mdef.key == "products" and not zoho,
        }

    # ---- 1. upload ---------------------------------------------------------------
    @api.post("/api/masters/{master}/import/upload")
    async def upload(master: str, request: Request, filename: str,
                     who: dict = Depends(current_user)) -> dict:
        mdef = known(master)
        name = Path(filename.replace("\\", "/")).name or "sheet"
        ext = Path(name).suffix.lower()
        if ext not in (".xlsx", ".csv", ".xls"):
            raise HTTPException(400, "Choose an Excel (.xlsx) or CSV file.")
        if int(request.headers.get("content-length") or 0) > MAX_BYTES:
            raise HTTPException(413, "The file is larger than 20 MB.")
        data = await request.body()
        if not data:
            raise HTTPException(400, "The file is empty.")
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "The file is larger than 20 MB.")
        uploads.mkdir(parents=True, exist_ok=True)
        sweep()
        token = secrets.token_urlsafe(24)
        stored = f"{token}.data{ext}"
        (uploads / stored).write_bytes(data)
        note = {"user_id": who["id"], "master": master, "file_name": name, "stored": stored}
        note_path(token).write_text(json.dumps(note), encoding="utf-8")
        try:
            with connection() as conn:
                return state(mdef, token, note, MastersRepo(conn, who["email"]), None, None)
        except HTTPException:
            forget(token)                 # a file that cannot be read is not kept
            raise

    # ---- 2. preview -----------------------------------------------------------------
    @api.post("/api/masters/{master}/import/{token}/preview")
    def preview(master: str, token: str, body: PreviewBody,
                who: dict = Depends(current_user)) -> dict:
        mdef = known(master)
        note = find(master, token, who)
        with connection() as conn:
            return state(mdef, token, note, MastersRepo(conn, who["email"]),
                         body.sheet, body.mapping)

    # ---- 3. import --------------------------------------------------------------------
    @api.post("/api/masters/{master}/import/{token}/run")
    def run(master: str, token: str, body: RunBody, who: dict = Depends(current_user)) -> dict:
        mdef = known(master)
        note = find(master, token, who)
        if "missing_ids" in note:
            raise HTTPException(400, "This file has already been imported.")
        day = None
        if mdef.has_rates and body.effective_from:
            try:
                day = date.fromisoformat(body.effective_from)
            except ValueError as exc:
                raise HTTPException(400, "“Amounts apply from” is not a date.") from exc
        with connection() as conn:
            repo = MastersRepo(conn, who["email"])
            now = state(mdef, token, note, repo, body.sheet, body.mapping)
            if now["missing"]:
                raise HTTPException(400, "Choose the column for: "
                                         + ", ".join(now["missing"]) + ".")
            sheet = read(mdef, note, body.sheet)
            records, problems = convert_rows(mdef, sheet, now["mapping"])
            zoho, markers = now["is_zoho"], []
            if zoho:
                records, markers = MastersRepo.split_zoho_items(records)
            if not records:
                raise HTTPException(400, "There is no row to import.")
            source = f"Import: {note['file_name']}"
            result = repo.import_records(mdef.key, records, day, source=source,
                                         add_new=body.add_new or zoho, replace_later=zoho)
            repo.set_mapping(mdef.key, now["mapping"])

            skipped = problems + result.skipped
            warnings = list(result.warnings)
            if markers:
                warnings.append(f"{_plural(len(markers), '₹1 labour item')} in Zoho's list "
                                "left out (not products): " + "; ".join(markers) + ".")
            if result.not_added:
                warnings.append(f"{_plural(result.not_added)} with a name that is not in the "
                                "master left out (“Add items…” is unticked).")
            missing = []
            if zoho:
                col = sheet.headers.index(now["mapping"]["name"])
                names = [str(cells[col]).strip() for _, cells in sheet.rows
                         if cells[col] not in (None, "")]
                missing = [{"id": p["id"], "name": p["name"]}
                           for p in repo.products_not_in(names)]

        (uploads / note["stored"]).unlink(missing_ok=True)       # the sheet is not kept
        if missing:
            # Kept with the token so "remove" can delete exactly these and no others.
            note["missing_ids"] = [m["id"] for m in missing]
            note_path(token).write_text(json.dumps(note), encoding="utf-8")
        else:
            forget(token)
        return {"file_name": note["file_name"], "added": result.added,
                "updated": result.updated, "unchanged": result.unchanged,
                "rates_changed": result.rates_changed,
                "effective_from": day.isoformat() if day else None,
                "skipped": skipped, "warnings": warnings,
                "not_in_zoho": missing, "may_remove": who["role"] == "admin"}

    @api.post("/api/masters/{master}/import/{token}/remove-missing")
    def remove_missing(master: str, token: str, who: dict = Depends(admin)) -> dict:
        """Admins only: delete the products the Zoho import found missing from
        Zoho's list. The ids come from the server's own note, not the browser."""
        known(master)
        note = find(master, token, who)
        ids = note.get("missing_ids") or []
        with connection() as conn:
            repo = MastersRepo(conn, who["email"])
            names = [p["name"] for p in (repo.get("products", i) for i in ids) if p]
            removed = repo.delete(
                "products", ids,
                source=f"Import: {note['file_name']} (not in Zoho's item list)")
        forget(token)
        return {"removed": removed, "names": names}

    @api.delete("/api/masters/{master}/import/{token}")
    def cancel(master: str, token: str, who: dict = Depends(current_user)) -> dict:
        known(master)
        if _TOKEN.match(token) and note_path(token).is_file():
            find(master, token, who)          # only one's own upload
            forget(token)
        return {"ok": True}

    # ---- export -------------------------------------------------------------------------
    @api.post("/api/masters/{master}/export")
    def export(master: str, body: ExportBody, who: dict = Depends(current_user)):
        mdef = known(master)
        with connection() as conn:
            rows = MastersRepo(conn, who["email"]).list_rows(master)
        if body.ids is not None:
            wanted = set(body.ids)
            rows = [r for r in rows if r["id"] in wanted]
        with tempfile.TemporaryDirectory(prefix="dns_export_") as folder:
            path = Path(folder) / "export.xlsx"
            export_rows(mdef, rows, path)
            data = path.read_bytes()
        name = f"{mdef.title.replace(' ', '_')}_{date.today():%d-%m-%Y}.xlsx"
        return Response(data, media_type=XLSX, headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-File-Name": name})

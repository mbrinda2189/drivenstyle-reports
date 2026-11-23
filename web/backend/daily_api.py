"""
daily_api.py - The daily payouts for the web screens (v0.27.0)
==============================================================

WHAT THIS MODULE DOES
---------------------
The browser's version of the daily payout app: staff upload the day's
invoice PDFs, the labour and incentive of each invoice are worked out and
posted to the payout register, and each line is later marked paid with a
reference or a proof.

    Scan invoices   upload PDFs -> "Scan" posts what can be posted
    Review          invoices that could not be posted, with the fix
    Payouts         every line: Mark paid, Hold / Release, Reopen;
                    Recalculate (v0.35.0) - posted invoices worked out again
                    with today's masters, unpaid lines only;
                    Show working (v0.37.0) - how each invoice's labour and
                    incentive were reached, on screen, as a one-invoice
                    PDF / Excel, and as an Excel for a date range; staff
                    may mark a working as checked (optional)
    History         the log of every change

WHO MAY USE IT: staff and admins alike (Brinda, 09-10-2026 - staff may also
reopen a payment and cancel an invoice, always with a reason, always
logged). Two things are for admins only: the start date, and clearing the
whole register.

IT DECIDES NOTHING ABOUT MONEY. The amounts come from payout_app/engine.py
(which uses the monthly tool's own calculation), the posting rules from
payout_app/register.py and the payment rules from payout_app/service.py -
see payout_store.py, the bridge to the database.

THE FILES (all under data/web/daily/, outside Git)
    inbox/    PDFs uploaded and waiting for the next Scan
    pdfs/     every PDF that has been scanned, kept under its own name. An
              invoice saved again from Zoho under the same name replaces
              the old file; the register notices if it now says something
              else ("Re-issued").
    proofs/   payment proofs, named so the name says what it is, e.g.
              2026-10-05_GPay_UTR123_Kumaran.jpg (service.proof_name).
              At deployment these move to the S3 bucket (step 7).

WHAT ONE SCAN READS
    * every PDF in the inbox, and
    * the PDF of every invoice still "In review" - so an invoice that was
      waiting for a name to be matched is posted by the next scan (or at
      once, when the match is saved on the Review screen).
    PDFs of invoices already Posted are NOT read again: they would be left
    alone anyway, and reading is the slow part.

Reading the PDFs is done by `read_files` below (engine.read_files); the
tests put a stand-in there, because client invoices are never in Git.
"""

from __future__ import annotations

import io
import re
import secrets
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.data.invoices_repo import OTHERS_CHOICE, OTHERS_ID
from app.data.masters_repo import MastersRepo
from app.reports.pdf_export import PdfError
from payout_app import engine, register
from payout_app.service import PROOF_MAX_BYTES, PROOF_TYPES, proof_name
from web.backend import workings_export
from web.backend.payout_store import MASTER, PayoutError, PayoutStore, issues_for_screen

PDF_MAX_BYTES = 10 * 1024 * 1024
LOG_LIMIT = 500
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,80}$")

read_files = engine.read_files            # replaced by a stand-in in the tests


class MatchBody(BaseModel):
    kind: str
    printed: str = ""
    invoices: list[str] = []
    target_id: int


class InvoiceBody(BaseModel):
    invoice_no: str
    reason: str = ""


class PayBody(BaseModel):
    line_ids: list[str]
    paid_date: str
    mode: str
    reference: str = ""
    remarks: str = ""
    proof_token: str = ""


class LinesBody(BaseModel):
    line_ids: list[str]
    reason: str = ""
    hold: bool = True


class RecalcBody(BaseModel):
    invoice_nos: list[str] = []
    all_unpaid: bool = False


class DateBody(BaseModel):
    date: str


class CheckBody(BaseModel):
    checked: bool = True
    note: str = ""


class ConfirmBody(BaseModel):
    confirm: str


def _safe_name(filename: str, fallback: str) -> str:
    """The bare file name of an upload - never a path."""
    return Path(filename.replace("\\", "/")).name.strip() or fallback


def _line(line: dict) -> dict:
    """A payout line for the browser: dates as YYYY-MM-DD text; no sheet row."""
    out = {k: v for k, v in line.items() if k != "row"}
    for key in ("invoice_date", "paid_date"):
        out[key] = out[key].isoformat() if out[key] else ""
    return out


def add_routes(api: FastAPI, connection, current_user, admin, data_dir: Path) -> None:
    """Attach the addresses. `data_dir` is the web tool's data folder."""
    base = data_dir / "daily"
    inbox, pdfs, proofs = base / "inbox", base / "pdfs", base / "proofs"

    def refuse(exc: PayoutError) -> HTTPException:
        return HTTPException(400, str(exc))

    def day(text: str, what: str) -> date:
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise HTTPException(400, f"{what} is not a date.") from exc

    def inbox_files() -> list[Path]:
        return sorted(p for p in inbox.glob("*") if p.is_file()) if inbox.is_dir() else []

    def waiting_files(store: PayoutStore) -> list[Path]:
        """The PDFs of invoices still In review (not those also in the inbox)."""
        fresh = {p.name for p in inbox_files()}
        names = {i["file_name"] for i in store.invoices()
                 if i["state"] == register.IN_REVIEW and i["file_name"] not in fresh}
        return sorted(pdfs / n for n in names if (pdfs / n).is_file())

    def run_scan(store: PayoutStore, with_inbox: bool) -> dict:
        """Read, calculate, post; then move the inbox's PDFs to pdfs/."""
        new = inbox_files() if with_inbox else []
        paths = new + waiting_files(store)
        if not paths:
            raise HTTPException(400, "There is nothing to scan: upload invoice PDFs first.")
        try:
            report = store.scan(read_files(paths))
        except PayoutError as exc:
            raise refuse(exc) from exc
        pdfs.mkdir(parents=True, exist_ok=True)
        for path in new:                       # scanned: out of the inbox, kept by name
            shutil.move(str(path), str(pdfs / path.name))
        report["files_read"] = len(paths)
        return report

    # ---- overview ------------------------------------------------------------------
    def totals(lines: list[dict]) -> dict:
        today = date.today()
        def of(wanted):                       # (count, amount) of the lines chosen
            chosen = [l for l in lines if wanted(l)]
            return {"lines": len(chosen), "amount": round(sum(l["amount"] for l in chosen), 2)}
        return {"pending": of(lambda l: l["status"] == register.PENDING),
                "hold": of(lambda l: l["status"] == register.HOLD),
                "paid_today": of(lambda l: l["status"] == register.PAID
                                 and l["paid_date"] == today)}

    @api.get("/api/daily/overview")
    def overview(who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            invoices = store.invoices()
            return {"start_date": store.start_date().isoformat(),
                    "inbox": [{"name": p.name, "size": p.stat().st_size} for p in inbox_files()],
                    "in_review": sum(i["state"] == register.IN_REVIEW for i in invoices),
                    "invoices": len(invoices), "totals": totals(store.lines()),
                    "modes": list(register.MODES), "types": list(engine.LINE_TYPES)}

    # ---- Scan invoices -------------------------------------------------------------
    @api.post("/api/daily/files")
    async def upload(request: Request, filename: str, who: dict = Depends(current_user)) -> dict:
        name = _safe_name(filename, "invoice.pdf")
        if Path(name).suffix.lower() != ".pdf":
            raise HTTPException(400, f"{name}: only invoice PDFs can be scanned.")
        data = await request.body()
        if not data:
            raise HTTPException(400, f"{name} is empty.")
        if len(data) > PDF_MAX_BYTES:
            raise HTTPException(413, f"{name} is larger than 10 MB.")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, f"{name} is not a PDF file.")
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / name).write_bytes(data)
        return {"name": name, "size": len(data)}

    @api.delete("/api/daily/files/{name}")
    def remove_upload(name: str, who: dict = Depends(current_user)) -> dict:
        (inbox / _safe_name(name, "x")).unlink(missing_ok=True)
        return {"ok": True}

    @api.post("/api/daily/scan")
    def scan(who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            return run_scan(PayoutStore(conn, who["email"]), with_inbox=True)

    # ---- Review -----------------------------------------------------------------------
    @api.get("/api/daily/review")
    def review(who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            waiting = [i for i in store.invoices() if i["state"] == register.IN_REVIEW]
            paths = waiting_files(store)
            issues = (issues_for_screen(store.calculate(read_files(paths)),
                                        store.waiting_numbers()) if paths else [])
            return {"invoices": waiting, "issues": issues}

    @api.get("/api/daily/choices")
    def choices(who: dict = Depends(current_user)) -> dict:
        """What a name can be matched to - the monthly Scan review's lists."""
        with connection() as conn:
            masters = MastersRepo(conn, who["email"])
            others = {"id": OTHERS_ID, "text": OTHERS_CHOICE}
            return {
                "Item": [{"id": p["id"], "text": p["name"] + ("" if p["active"] else "  (inactive)")}
                         for p in masters.list_rows("products")],
                "Salesperson": [{"id": e["id"], "text": f"{e['name']} ({e['phone']})"
                                 + (f" – {e['branch']}" if e["branch"] else "")}
                                for e in masters.list_rows("executives")] + [others],
                "Car": [{"id": c["id"], "text": MastersRepo.display_name("cars", c)}
                        for c in masters.list_rows("cars")] + [others]}

    def after_fix(store: PayoutStore, done: str) -> dict:
        """A fix may let waiting invoices be posted: scan them again at once."""
        report = run_scan(store, with_inbox=False) if waiting_files(store) else None
        return {"done": done, "report": report}

    @api.post("/api/daily/match")
    def match(body: MatchBody, who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            try:
                done = store.save_match(body.kind, body.printed, body.invoices, body.target_id)
            except PayoutError as exc:
                raise refuse(exc) from exc
            return after_fix(store, done)

    @api.post("/api/daily/accept-totals")
    def accept_totals(body: InvoiceBody, who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            if not any(i["invoice_no"] == body.invoice_no and i["state"] == register.IN_REVIEW
                       for i in store.invoices()):
                raise HTTPException(404, "This invoice is not waiting for review.")
            return after_fix(store, store.accept_totals(body.invoice_no))

    @api.post("/api/daily/cancel")
    def cancel(body: InvoiceBody, who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            try:
                paid = PayoutStore(conn, who["email"]).cancel_invoice(body.invoice_no, body.reason)
            except PayoutError as exc:
                raise refuse(exc) from exc
            return {"paid_lines_left": paid}

    # ---- Payouts ------------------------------------------------------------------------
    @api.get("/api/daily/lines")
    def lines(who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            found = store.lines()
            # v0.37.0: which invoices have a stored working, and which are checked
            checks = {n: {"by": c["checked_by"], "at": c["checked_at"], "current": c["current"]}
                      for n, c in store.checks().items()}
            return {"lines": [_line(l) for l in found], "totals": totals(found),
                    "invoices": store.invoices(), "checks": checks,
                    "with_working": sorted(store.with_working())}

    @api.post("/api/daily/proofs")
    async def upload_proof(request: Request, filename: str,
                           who: dict = Depends(current_user)) -> dict:
        """Keep a proof until the payment it belongs to is recorded."""
        ext = Path(_safe_name(filename, "proof")).suffix.lower()
        if ext not in PROOF_TYPES:
            raise HTTPException(400, "The proof must be a picture or a PDF ("
                                + ", ".join(t.lstrip(".") for t in PROOF_TYPES) + ").")
        data = await request.body()
        if not data:
            raise HTTPException(400, "The proof file is empty.")
        if len(data) > PROOF_MAX_BYTES:
            raise HTTPException(413, "The proof file is larger than 10 MB. Please use a "
                                     "smaller picture or PDF.")
        waiting = proofs / "waiting"
        waiting.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(24)
        (waiting / f"{token}{ext}").write_bytes(data)
        return {"token": token + ext}

    def waiting_proof(token: str) -> Path | None:
        if not token:
            return None
        stem, ext = Path(token).stem, Path(token).suffix.lower()
        path = proofs / "waiting" / f"{stem}{ext}"
        if not _TOKEN.match(stem) or ext not in PROOF_TYPES or not path.is_file():
            raise HTTPException(400, "The proof is no longer on the server. Choose it again.")
        return path

    @api.post("/api/daily/pay")
    def pay(body: PayBody, who: dict = Depends(current_user)) -> dict:
        paid_on, now = day(body.paid_date, "The paid date"), datetime.now()
        proof = waiting_proof(body.proof_token)
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            try:
                store.check_payment(body.line_ids, paid_on, body.mode, body.reference,
                                    proof is not None, now)
                name = ""
                if proof is not None:
                    by_id = {l["line_id"]: l for l in store.lines()}
                    payees = [by_id[i]["payee"] for i in body.line_ids if i in by_id]
                    name = proof_name(paid_on, body.mode, body.reference, payees, proof.suffix)
                    n = 1
                    while (proofs / name).exists():            # never overwrite a proof
                        n += 1
                        name = f"{Path(name).stem}-{n}{proof.suffix.lower()}"
                done = store.record_payment(body.line_ids, paid_on, body.mode, body.reference,
                                            name, body.remarks, now)
            except PayoutError as exc:
                raise refuse(exc) from exc
        if proof is not None:                # recorded: the proof gets its lasting name
            shutil.move(str(proof), str(proofs / name))
        return {"paid": len(done), "amount": round(sum(l["amount"] for l in done), 2),
                "proof": name}

    @api.post("/api/daily/reopen")
    def reopen(body: LinesBody, who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            try:
                return {"reopened": len(PayoutStore(conn, who["email"]).reopen_payment(
                    body.line_ids, body.reason))}
            except PayoutError as exc:
                raise refuse(exc) from exc

    @api.post("/api/daily/hold")
    def hold(body: LinesBody, who: dict = Depends(current_user)) -> dict:
        with connection() as conn:
            try:
                return {"changed": len(PayoutStore(conn, who["email"]).set_hold(
                    body.line_ids, body.hold, body.reason))}
            except PayoutError as exc:
                raise refuse(exc) from exc

    @api.get("/api/daily/proofs/{name}")
    def proof_file(name: str, who: dict = Depends(current_user)):
        path = proofs / _safe_name(name, "x")
        if not path.is_file():
            raise HTTPException(404, "This proof is not on the server.")
        return FileResponse(path, filename=path.name)

    # ---- Recalculate (v0.35.0) ----------------------------------------------------------
    @api.get("/api/daily/recalculate")
    def recalc_preview(who: dict = Depends(current_user)) -> dict:
        """How many invoices "every invoice with unpaid lines" would cover."""
        with connection() as conn:
            return {"unpaid_invoices": PayoutStore(conn, who["email"]).with_unpaid_lines()}

    @api.post("/api/daily/recalculate")
    def recalculate(body: RecalcBody, who: dict = Depends(current_user)) -> dict:
        """
        Work posted invoices out again with today's masters and rules
        (register.py, RECALCULATE): unpaid lines are corrected, newly due
        lines added, PAID lines left exactly as they are. Staff and admins;
        every change is logged with the person's e-mail.
        """
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            posted = store.recalculable()
            numbers = store.with_unpaid_lines() if body.all_unpaid else \
                list(dict.fromkeys(n.strip() for n in body.invoice_nos if n.strip()))
            if not numbers:
                raise HTTPException(400, "Choose the invoices to recalculate.")
            unknown = [n for n in numbers if n not in posted]
            if unknown:
                raise HTTPException(400, "Only posted invoices can be recalculated: "
                                    + ", ".join(unknown) + ".")
            paths = [pdfs / posted[n] for n in numbers]
            missing = [p.name for p in paths if not p.is_file()]
            if missing:
                raise HTTPException(400, "The PDF is no longer on the server for: "
                                    + ", ".join(missing) + ". Scan it again first.")
            try:
                report = store.recalculate(read_files(paths), set(numbers))
            except PayoutError as exc:
                raise refuse(exc) from exc
            report["files_read"] = len(paths)
            return report

    # ---- Show working (v0.37.0) ---------------------------------------------------------
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def view_of(store: PayoutStore, invoice_no: str) -> dict:
        try:
            return store.working(invoice_no)
        except PayoutError as exc:
            raise HTTPException(404, str(exc)) from exc

    def for_browser(view: dict) -> dict:
        return {**view, "lines": [_line(l) for l in view["lines"]]}

    def file_name(invoice_no: str, ext: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in invoice_no)
        return f"Working_{safe}.{ext}"

    @api.get("/api/daily/working/{invoice_no}")
    def show_working(invoice_no: str, who: dict = Depends(current_user)) -> dict:
        """The stored working of one invoice, its history, lines and check."""
        with connection() as conn:
            return for_browser(view_of(PayoutStore(conn, who["email"]), invoice_no))

    @api.post("/api/daily/working/{invoice_no}/rebuild")
    def rebuild_working(invoice_no: str, who: dict = Depends(current_user)) -> dict:
        """For an invoice posted before v0.37.0: make its working from the kept
        PDF - saved only if it gives exactly the posted amounts."""
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            name = store.recalculable().get(invoice_no)
            if not name or not (pdfs / name).is_file():
                raise HTTPException(400, f"The PDF of {invoice_no} is no longer on the "
                                         "server. Scan it again first.")
            try:
                return for_browser(store.rebuild_working(read_files([pdfs / name]),
                                                         invoice_no))
            except PayoutError as exc:
                raise refuse(exc) from exc

    @api.post("/api/daily/working/{invoice_no}/check")
    def check_working(invoice_no: str, body: CheckBody,
                      who: dict = Depends(current_user)) -> dict:
        """Mark (or unmark) the invoice's working as checked - optional."""
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            view_of(store, invoice_no)
            try:
                return for_browser(store.set_check(invoice_no, body.checked, body.note))
            except PayoutError as exc:
                raise refuse(exc) from exc

    @api.get("/api/daily/working/{invoice_no}/file")
    def working_file(invoice_no: str, format: str = "pdf", who: dict = Depends(current_user)):
        """One invoice's working to download: format = pdf or xlsx."""
        with connection() as conn:
            view = view_of(PayoutStore(conn, who["email"]), invoice_no)
        if view["working"] is None:
            raise HTTPException(400, "This invoice's working is not saved yet. Open Show "
                                     "working and use “Make the working” first.")
        if format == "xlsx":
            out = io.BytesIO()
            workings_export.invoice_workbook(view).save(out)
            data, kind, ext = out.getvalue(), XLSX, "xlsx"
        elif format == "pdf":
            try:
                data, kind, ext = workings_export.invoice_pdf(view), "application/pdf", "pdf"
            except PdfError as exc:
                raise HTTPException(400, str(exc)) from exc
        else:
            raise HTTPException(400, "Choose pdf or xlsx.")
        return Response(data, media_type=kind, headers={
            "Content-Disposition": f'attachment; filename="{file_name(invoice_no, ext)}"'})

    @api.get("/api/daily/workings/export")
    def workings_range(date_from: str, date_to: str = "", who: dict = Depends(current_user)):
        """
        Every posted invoice DATED in the range (invoice date, inclusive) with
        its working, as an Excel to check with one's own formulas. Cancelled
        invoices and invoices in review are left out.
        """
        start = day(date_from, "The from date")
        end = day(date_to, "The to date") if date_to else start
        if end < start:
            raise HTTPException(400, "The to date is before the from date.")
        if (end - start).days > 92:
            raise HTTPException(400, "Choose at most three months at a time.")
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            # the register keeps the invoice date as dd-mm-yyyy text
            dated = {}
            for i in store.invoices():
                try:
                    on = datetime.strptime(i["invoice_date"], "%d-%m-%Y").date()
                except ValueError:
                    continue
                if i["state"] in (register.POSTED, register.REISSUED) and start <= on <= end:
                    dated[i["invoice_no"]] = on
            entries = [store.working(n) for n in dated]
        entries.sort(key=lambda e: (dated[e["invoice"]["invoice_no"]], e["invoice"]["invoice_no"]))
        if not entries:
            raise HTTPException(400, "No posted invoice is dated in this range.")
        span = f"{start:%d-%m-%Y}" + (f" to {end:%d-%m-%Y}" if end != start else "")
        out = io.BytesIO()
        workings_export.range_workbook(entries, f"Workings - invoices dated {span}").save(out)
        name = f"Workings_{start:%d-%m-%Y}" + (f"_to_{end:%d-%m-%Y}" if end != start else "")
        return Response(out.getvalue(), media_type=XLSX, headers={
            "Content-Disposition": f'attachment; filename="{name}.xlsx"'})

    # ---- History ---------------------------------------------------------------------------
    @api.get("/api/daily/log")
    def log(text: str = "", who: dict = Depends(current_user)) -> dict:
        """The payout register's own entries of the audit log (staff may see
        these; the full audit log stays with the admins)."""
        with connection() as conn:
            found = MastersRepo(conn, "").audit_entries(MASTER, text=text, limit=LOG_LIMIT + 1)
        return {"entries": found[:LOG_LIMIT], "more": len(found) > LOG_LIMIT}

    # ---- admin only ----------------------------------------------------------------------------
    @api.put("/api/daily/start-date")
    def set_start(body: DateBody, who: dict = Depends(admin)) -> dict:
        with connection() as conn:
            store = PayoutStore(conn, who["email"])
            store.set_start_date(day(body.date, "The start date"))
            return {"start_date": store.start_date().isoformat()}

    @api.post("/api/daily/clear")
    def clear(body: ConfirmBody, who: dict = Depends(admin)) -> dict:
        """Empty the register for a fresh start. A copy of the whole database
        is made first, beside it; the word CLEAR must be typed."""
        if body.confirm != "CLEAR":
            raise HTTPException(400, "Type CLEAR (in capitals) to empty the register.")
        with connection() as conn:
            source = Path(conn.execute("PRAGMA database_list").fetchone()["file"])
            backup = source.with_name(
                f"{source.stem}.before-clear-{datetime.now():%d-%m-%Y_%H%M%S}.db")
            copy = sqlite3.connect(str(backup))
            try:
                conn.backup(copy)
            finally:
                copy.close()
            lines, invoices = PayoutStore(conn, who["email"]).clear()
        return {"lines": lines, "invoices": invoices, "backup": backup.name}

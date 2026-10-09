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
    Payouts         every line: Mark paid, Hold / Release, Reopen
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

import re
import secrets
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.data.invoices_repo import OTHERS_CHOICE, OTHERS_ID
from app.data.masters_repo import MastersRepo
from payout_app import engine, register
from payout_app.service import PROOF_MAX_BYTES, PROOF_TYPES, proof_name
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


class DateBody(BaseModel):
    date: str


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
            return {"lines": [_line(l) for l in found], "totals": totals(found),
                    "invoices": store.invoices()}

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

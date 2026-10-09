"""
monthly_api.py - The monthly reports tool for the web screens (v0.26.0)
=======================================================================

WHAT THIS MODULE DOES
---------------------
The browser's version of the desktop tool's four monthly screens:

    Generate reports   upload the month's Zoho files, read the invoices,
                       make the Excel workbook (and the PDF)
    Scan review        what the reading could not settle, each with a fix;
                       the saved matches; every invoice read
    Monthly inputs     indirect costs, high-profit threshold, automatic
                       cost percentages
    History            workbooks made, months read; download, regenerate,
                       remove

IT CALCULATES NOTHING ITSELF. Reading the export (invoice_export.py),
matching and fixes (invoices_repo.py), inputs (inputs_repo.py) and the
workbook (reports/generate.py) are the desktop tool's own code, called in
the same order as its screens call them. The figures are therefore the
same - tests/test_baseline.py and test_web_monthly.py hold that.

WHAT IS DIFFERENT ON THE WEB
    * FILES ARE UPLOADED, not picked from a folder. The month's three files
      are kept on the server in data/web/months/<YYYY-MM>/ :
          invoices   Zoho's invoice export (.csv / .xlsx)        - needed
          payments   Zoho's "Payments Received" export           - optional
          rto        the dealership's delivery (RTO) list        - optional
      They stay there so that History > Regenerate can use them again
      without a new upload. A new upload of the same kind replaces the old.
    * WORKBOOKS ARE DOWNLOADED. They are written to data/web/output/ and
      sent to the browser on request; nothing is "opened" on the server.
    * THE PDF IS MADE BY LIBREOFFICE (reports/pdf_export.py), because the
      server has no Excel.
    * Questions the desktop asks in a message box ("5 issues are still
      open - generate anyway?") are asked by the screen, from the counts
      this module sends.

WHO MAY USE IT: ADMINS ONLY (Brinda, 09-10-2026) - these reports show cost
and profit. Every address here refuses staff.

The month is always part of the address as YYYY-MM, e.g. /api/monthly/2026-09/read.
"""

from __future__ import annotations

import dataclasses
import json
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.data.inputs_repo import AUTO_HEADS, DEFAULT_HEADS, InputsRepo
from app.data.invoice_export import ExportFileError, classify_export
from app.data.invoices_repo import (
    FIRM_GSTIN, OTHERS_CHOICE, OTHERS_ID, ZOHO_CATEGORY_SOURCE, InvoicesRepo, month_label)
from app.data.masters_repo import MastersRepo
from app.data.payments_io import PaymentsFileError, read_payments
from app.data.rto_list import RtoFileError, read_rto
from app.reports.generate import GenerateError, generate, make_pdf
from app.reports.issues_export import (
    default_file_name, export_issues, export_matches, matches_file_name)
from app.reports import pdf_export
from app.reports.pdf_export import PdfError, pdf_path_for
from app.sample_data import REPORTS

MAX_BYTES = 30 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")

# The three files of a month: kind -> (what it is called on screen, extensions).
FILE_KINDS = {
    "invoices": ("Zoho invoice export", (".csv", ".xlsx")),
    "payments": ("Zoho payments export", (".csv", ".xlsx")),
    "rto": ("Delivery (RTO) list", (".xlsx",)),
}


class GenerateBody(BaseModel):
    reports: list[str]
    pdf: bool = False


class FixBody(BaseModel):
    kind: str
    key: str
    target_id: int | None = None
    all_invoices: bool = False


class MatchBody(BaseModel):
    store: str
    kind: str
    key: str
    target_id: int | None = None


class InputsBody(BaseModel):
    costs: list[tuple[str, float]]
    threshold: float


class RatesBody(BaseModel):
    rates: dict[str, float]


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def add_routes(api: FastAPI, connection, admin, data_dir: Path) -> None:
    """Attach the addresses. `data_dir` is the web tool's data folder."""
    months_dir, output_dir = data_dir / "months", data_dir / "output"

    def ym(text: str) -> tuple[int, int]:
        m = _MONTH.match(text)
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise HTTPException(404, "That is not a month.")
        return int(m.group(1)), int(m.group(2))

    def repos(conn, who: dict):
        masters = MastersRepo(conn, user=who["email"])
        return masters, InvoicesRepo(masters), InputsRepo(masters)

    # ---- the month's uploaded files ------------------------------------------------
    def notes(month: str) -> dict:
        path = months_dir / month / "files.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def stored(month: str, kind: str) -> Path | None:
        """Where the month's file of this kind is kept, or None."""
        note = notes(month).get(kind)
        path = months_dir / month / note["stored"] if note else None
        return path if path and path.is_file() else None

    def files_for_screen(month: str) -> dict:
        saved = notes(month)
        return {kind: ({"name": saved[kind]["name"], "at": saved[kind]["at"],
                        "by": saved[kind]["by"]} if stored(month, kind) else None)
                for kind in FILE_KINDS}

    @api.post("/api/monthly/{month}/files/{kind}")
    async def upload(month: str, kind: str, request: Request, filename: str,
                     who: dict = Depends(admin)) -> dict:
        ym(month)
        if kind not in FILE_KINDS:
            raise HTTPException(404, "There is no such file.")
        label, extensions = FILE_KINDS[kind]
        name = Path(filename.replace("\\", "/")).name or kind
        ext = Path(name).suffix.lower()
        if ext not in extensions:
            raise HTTPException(400, f"{label}: choose a {' or '.join(extensions)} file.")
        data = await request.body()
        if not data:
            raise HTTPException(400, "The file is empty.")
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "The file is larger than 30 MB.")
        folder = months_dir / month
        folder.mkdir(parents=True, exist_ok=True)
        # Checked BEFORE it replaces the month's present file: a wrong file
        # (e.g. the invoice export chosen as the payments export) is refused
        # here, in plain words, not later while generating.
        trial = folder / f"{kind}.new{ext}"
        trial.write_bytes(data)
        try:
            if kind == "payments":
                read_payments(trial)
            elif kind == "rto":
                read_rto(trial)
            else:
                year, mon = ym(month)
                classify_export(trial, year, mon, FIRM_GSTIN)
        except (PaymentsFileError, RtoFileError, ExportFileError) as exc:
            trial.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
        for old in folder.glob(f"{kind}.*"):
            if old != trial:
                old.unlink(missing_ok=True)
        final = folder / f"{kind}{ext}"
        trial.replace(final)
        saved = notes(month)
        saved[kind] = {"name": name, "stored": final.name, "by": who["email"],
                       "at": datetime.now().isoformat(timespec="seconds")}
        (folder / "files.json").write_text(json.dumps(saved), encoding="utf-8")
        return files_for_screen(month)

    @api.delete("/api/monthly/{month}/files/{kind}")
    def remove_file(month: str, kind: str, who: dict = Depends(admin)) -> dict:
        ym(month)
        if kind not in FILE_KINDS:
            raise HTTPException(404, "There is no such file.")
        saved = notes(month)
        if kind in saved:
            (months_dir / month / saved[kind]["stored"]).unlink(missing_ok=True)
            del saved[kind]
            (months_dir / month / "files.json").write_text(json.dumps(saved), encoding="utf-8")
        return files_for_screen(month)

    # ---- Generate reports: what the screen shows for a month ----------------------------
    def scan_summary(invoices: InvoicesRepo, year: int, month: int) -> dict | None:
        run = invoices.scan_run(year, month)
        if run is None:
            return None
        files = invoices.scan_files(year, month)
        read = sum(f["status"] == "read" for f in files)
        open_issues = [i for i in invoices.issues(year, month) if i.status == "open"]
        return {"scanned_at": run["scanned_at"], "source": run["folder"], "read": read,
                "skipped": len(files) - read, "open_issues": len(open_issues),
                "invoices_held_back": len({n for i in open_issues for n in i.invoices})}

    def run_for_screen(run: dict) -> dict:
        path = Path(run["file_path"])
        here = output_dir.resolve() in path.resolve().parents and path.is_file()
        year, month = map(int, run["month"].split("-"))
        return {"id": run["id"], "month": run["month"], "label": month_label(year, month),
                "file_name": path.name, "generated_at": run["generated_at"],
                "user": run["user"], "invoices": run["invoices"], "left_out": run["left_out"],
                "sales": run["sales"], "gross_profit": run["gross_profit"],
                "reports": json.loads(run["reports_json"] or "[]"),
                # A workbook made on the desktop tool is not on this server.
                "available": here, "pdf_available": here and pdf_path_for(path).is_file()}

    @api.get("/api/monthly/{month}/overview")
    def overview(month: str, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        with connection() as conn:
            masters, invoices, inputs = repos(conn, who)
            last = next((r for r in inputs.runs() if r["month"] == month), None)
            return {"month": month, "label": month_label(year, mon), "reports": REPORTS,
                    "files": files_for_screen(month),
                    "scan": scan_summary(invoices, year, mon),
                    "masters": masters.counts(), "has_inputs": inputs.has_inputs(year, mon),
                    "last_run": run_for_screen(last) if last else None,
                    "pdf_possible": pdf_export.pdf_possible()}

    @api.post("/api/monthly/{month}/read")
    def read_invoices(month: str, who: dict = Depends(admin)) -> dict:
        """Read the month's uploaded invoice export and save its invoices -
        the same steps, in the same order, as the desktop "Read invoices"."""
        year, mon = ym(month)
        path, label = stored(month, "invoices"), month_label(year, mon)
        if path is None:
            raise HTTPException(400, "Upload the Zoho invoice export first.")
        name = notes(month)["invoices"]["name"]
        try:
            scan = classify_export(path, year, mon, FIRM_GSTIN)
        except ExportFileError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not scan.results:
            raise HTTPException(400, f"No invoice in {name} is dated in {label} "
                                     f"({_plural(scan.other_months, 'invoice')} from other "
                                     "months). Nothing was saved.")
        with connection() as conn:
            masters, invoices, _ = repos(conn, who)
            changes = lambda: conn.execute(                        # noqa: E731
                "SELECT COUNT(*) FROM audit_log WHERE source = ?",
                (ZOHO_CATEGORY_SOURCE,)).fetchone()[0]
            before = changes()
            counts = invoices.store_scan(year, mon, name, scan.results)
            changed = changes() - before
            log = [{"kind": "skip" if r.status == "skipped" else "error",
                    "text": f"{r.file_name}: {r.reason}"}
                   for r in scan.results if r.status in ("skipped", "error")]
            log.append({"kind": "ok", "text": f"{counts['read']} invoices ({scan.rows} lines "
                                              f"in the file) read for {label}."})
            if scan.other_months:
                log.append({"kind": "skip", "text": f"{_plural(scan.other_months, 'invoice')} "
                                                    "dated in other months ignored."})
            if changed:
                log.append({"kind": "skip", "text": "Category set from Zoho's item type for "
                                                    f"{_plural(changed, 'product')} (see the audit log)."})
            summary = scan_summary(invoices, year, mon)
            n = summary["open_issues"]
            log.append({"kind": "warn" if n else "ok",
                        "text": f"{_plural(n, 'issue')} to review."})
            return {"log": log, "scan": summary}

    @api.post("/api/monthly/{month}/generate")
    def generate_workbook(month: str, body: GenerateBody, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        unknown = [r for r in body.reports if r not in REPORTS]
        if unknown or not body.reports:
            raise HTTPException(400, "Tick at least one report.")
        return _generate(month, year, mon, [r for r in REPORTS if r in body.reports],
                         body.pdf, who)

    def _generate(month: str, year: int, mon: int, reports: list[str], pdf: bool,
                  who: dict) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        payments, rto = stored(month, "payments"), stored(month, "rto")
        with connection() as conn:
            masters, invoices, inputs = repos(conn, who)
            try:
                result = generate(masters, invoices, inputs, year, mon, output_dir, reports,
                                  str(payments or ""), str(rto or ""), pdf=pdf)
            except GenerateError as exc:
                raise HTTPException(400, str(exc)) from exc
            run = next(r for r in inputs.runs(latest_per_month=False)
                       if r["file_path"] == str(result.path))
            return {"run": run_for_screen(run), "payments_used": result.payments_used,
                    "rto_used": rto is not None, "pdf_error": result.pdf_error}

    # ---- History ----------------------------------------------------------------------------
    def find_run(inputs: InputsRepo, run_id: int) -> dict:
        run = next((r for r in inputs.runs(latest_per_month=False) if r["id"] == run_id), None)
        if run is None:
            raise HTTPException(404, "This workbook is no longer in History.")
        return run

    @api.get("/api/monthly/history")
    def history(who: dict = Depends(admin)) -> dict:
        with connection() as conn:
            _, invoices, inputs = repos(conn, who)
            months = []
            for m in invoices.months_read():
                year, mon = map(int, m["month"].split("-"))
                months.append({**m, "label": month_label(year, mon)})
            return {"runs": [run_for_screen(r) for r in inputs.runs()], "months": months,
                    "pdf_possible": pdf_export.pdf_possible()}

    @api.get("/api/monthly/runs/{run_id}/download")
    def download(run_id: int, pdf: bool = False, who: dict = Depends(admin)):
        with connection() as conn:
            run = find_run(repos(conn, who)[2], run_id)
        shown = run_for_screen(run)
        path = Path(run["file_path"])
        if pdf:
            path = pdf_path_for(path)
        if not shown["available"] or not path.is_file():
            raise HTTPException(404, "This file is not on the server. Use Regenerate to "
                                     "make it again.")
        return FileResponse(path, filename=path.name,
                            media_type="application/pdf" if pdf else XLSX)

    @api.post("/api/monthly/runs/{run_id}/regenerate")
    def regenerate(run_id: int, who: dict = Depends(admin)) -> dict:
        """The same reports again, from the data as it is NOW (fixes and
        master changes made since are included) and the month's files."""
        with connection() as conn:
            run = find_run(repos(conn, who)[2], run_id)
        year, mon = map(int, run["month"].split("-"))
        reports = [r for r in REPORTS if r in json.loads(run["reports_json"] or "[]")] or REPORTS
        was_pdf = pdf_path_for(Path(run["file_path"])).is_file()
        return _generate(run["month"], year, mon, reports, was_pdf, who)

    @api.post("/api/monthly/runs/{run_id}/pdf")
    def pdf_for_run(run_id: int, who: dict = Depends(admin)) -> dict:
        with connection() as conn:
            masters, invoices, inputs = repos(conn, who)
            run = find_run(inputs, run_id)
            if not run_for_screen(run)["available"]:
                raise HTTPException(404, "The workbook is not on the server. Use Regenerate.")
            year, mon = map(int, run["month"].split("-"))
            try:
                make_pdf(masters, invoices, inputs, year, mon, run["file_path"],
                         str(stored(run["month"], "payments") or ""),
                         str(stored(run["month"], "rto") or ""))
            except (PdfError, GenerateError) as exc:
                raise HTTPException(400, str(exc)) from exc
            return run_for_screen(run)

    @api.delete("/api/monthly/{month}/runs")
    def remove_runs(month: str, who: dict = Depends(admin)) -> dict:
        """Take a month out of the History list; its files on the server go too."""
        year, mon = ym(month)
        with connection() as conn:
            inputs = repos(conn, who)[2]
            paths = [Path(r["file_path"]) for r in inputs.runs(latest_per_month=False)
                     if r["month"] == month]
            removed = inputs.remove_runs(year, mon)
        for path in paths:
            if output_dir.resolve() in path.resolve().parents:
                path.unlink(missing_ok=True)
                pdf_path_for(path).unlink(missing_ok=True)
        return {"removed": removed}

    @api.delete("/api/monthly/{month}/invoices")
    def remove_month(month: str, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        with connection() as conn:
            return {"removed": repos(conn, who)[1].remove_month(year, mon)}

    # ---- Scan review ------------------------------------------------------------------------
    @api.get("/api/monthly/{month}/issues")
    def issues(month: str, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        with connection() as conn:
            _, invoices, _ = repos(conn, who)
            found = invoices.issues(year, mon)
            return {"label": month_label(year, mon),
                    "scan": scan_summary(invoices, year, mon),
                    "issues": [dataclasses.asdict(i) for i in found]}

    @api.get("/api/monthly/choices")
    def choices(who: dict = Depends(admin)) -> dict:
        """What an issue can be fixed with - the lists of the desktop's Fix column."""
        with connection() as conn:
            masters, _, _ = repos(conn, who)
            people = [{"id": e["id"], "text": f"{e['name']} ({e['phone']})"
                       + (f" – {e['branch']}" if e["branch"] else "")}
                      for e in masters.list_rows("executives")]
            cars = [{"id": c["id"], "text": MastersRepo.display_name("cars", c)}
                    for c in masters.list_rows("cars")]
            others = {"id": OTHERS_ID, "text": OTHERS_CHOICE}
            return {"product": [{"id": p["id"], "text": p["name"]
                                 + ("" if p["active"] else "  (inactive)")}
                                for p in masters.list_rows("products")],
                    "salesperson": people + [others], "car": cars + [others]}

    def open_issue(invoices: InvoicesRepo, year: int, mon: int, kind: str, key: str):
        """The issue as the SERVER sees it now - what is printed and whether
        it is grouped are never taken from the browser."""
        for issue in invoices.issues(year, mon):
            if issue.status == "open" and issue.kind == kind and issue.key == key:
                return issue
        raise HTTPException(404, "This issue is no longer open. Refresh the list.")

    @api.post("/api/monthly/{month}/fix")
    def fix(month: str, body: FixBody, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        with connection() as conn:
            masters, invoices, _ = repos(conn, who)
            issue = open_issue(invoices, year, mon, body.kind, body.key)
            target = body.target_id
            if issue.kind == "product":
                product = masters.get("products", target) if target is not None else None
                if product is None:
                    raise HTTPException(400, "Choose a product from the list.")
                invoices.map_product(issue.printed, target)
                done = f"“{issue.printed}” will be read as {product['name']}."
            elif issue.kind in ("salesperson", "car"):
                master = "executives" if issue.kind == "salesperson" else "cars"
                row = None if target in (None, OTHERS_ID) else masters.get(master, target)
                if target is None or (target != OTHERS_ID and row is None):
                    raise HTTPException(400, "Choose a "
                                        + ("sales executive" if master == "executives" else "car")
                                        + " from the list.")
                every = issue.grouped or (bool(issue.printed) and body.all_invoices)
                if issue.kind == "salesperson":
                    invoices.set_salesperson(issue.key, issue.printed, target, every)
                else:
                    invoices.set_car(issue.key, issue.printed, target, every)
                name = OTHERS_CHOICE if target == OTHERS_ID else MastersRepo.display_name(master, row)
                done = (f"{name} set for all invoices showing “{issue.printed}”." if every
                        else f"{name} set for invoice {issue.key}.")
            elif issue.kind in ("labour", "totals"):
                invoices.acknowledge(issue.key, issue.kind)
                done = f"Invoice {issue.key} accepted."
            else:
                raise HTTPException(400, "This entry is for information only.")
            return {"done": done, "scan": scan_summary(invoices, year, mon),
                    "issues": [dataclasses.asdict(i) for i in invoices.issues(year, mon)]}

    @api.get("/api/monthly/{month}/invoices")
    def invoices_read(month: str, who: dict = Depends(admin)) -> list[dict]:
        """Every invoice read for the month, as the tool understood it."""
        year, mon = ym(month)
        with connection() as conn:
            out = []
            for inv in repos(conn, who)[1].invoices(year, mon):
                items = [l for l in inv["lines"] if not l["is_labour_marker"]]
                out.append({
                    "invoice_no": inv["invoice_no"], "date": inv["invoice_date"],
                    "customer": inv["customer"],
                    "executive": inv["executive"], "printed_executive": inv["salesperson"] or "",
                    "car": inv["car"], "printed_car": inv["vehicle"] or "",
                    "items": len(items), "total": inv["total"],
                    "gst": ("No GST" if inv["tax_rate"] == 0 else
                            "Mixed" if inv["tax_rate"] < 0 else f"{inv['tax_rate']:g}%"),
                    "payment_mode": inv["payment_mode"] or "",
                    "lines": [{"no": l["line_no"], "description": l["description"],
                               "amount": l["amount"], "product": l["product"],
                               "marker": bool(l["is_labour_marker"])} for l in inv["lines"]]})
            return out

    def matches_for_screen(invoices: InvoicesRepo, year: int, mon: int) -> list[dict]:
        return [{**dataclasses.asdict(m), "type_label": m.type_label}
                for m in invoices.saved_matches(year, mon)]

    @api.get("/api/monthly/{month}/matches")
    def matches(month: str, who: dict = Depends(admin)) -> list[dict]:
        year, mon = ym(month)
        with connection() as conn:
            return matches_for_screen(repos(conn, who)[1], year, mon)

    def find_match(invoices: InvoicesRepo, year: int, mon: int, body: MatchBody):
        for m in invoices.saved_matches(year, mon):
            if (m.store, m.kind, m.key) == (body.store, body.kind, body.key):
                return m
        raise HTTPException(404, "This saved match is no longer there. Refresh the list.")

    @api.get("/api/monthly/match-choices/{kind}")
    def match_choices(kind: str, who: dict = Depends(admin)) -> list[dict]:
        if kind not in ("product", "executive", "car"):
            raise HTTPException(404, "Not found.")
        with connection() as conn:
            return [{"id": i, "text": text}
                    for text, i in repos(conn, who)[1].match_choices(kind)]

    @api.post("/api/monthly/{month}/matches/change")
    def change_match(month: str, body: MatchBody, who: dict = Depends(admin)) -> list[dict]:
        year, mon = ym(month)
        with connection() as conn:
            invoices = repos(conn, who)[1]
            match = find_match(invoices, year, mon, body)
            if body.target_id is None:
                raise HTTPException(400, "Choose what it should be matched to.")
            try:
                invoices.change_match(match, body.target_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            return matches_for_screen(invoices, year, mon)

    @api.post("/api/monthly/{month}/matches/remove")
    def remove_match(month: str, body: MatchBody, who: dict = Depends(admin)) -> list[dict]:
        year, mon = ym(month)
        with connection() as conn:
            invoices = repos(conn, who)[1]
            invoices.remove_match(find_match(invoices, year, mon, body))
            return matches_for_screen(invoices, year, mon)

    def excel(write, name: str) -> Response:
        """Run one of the desktop tool's Excel writers and send the file."""
        with tempfile.TemporaryDirectory(prefix="dns_sheet_") as folder:
            path = Path(folder) / "out.xlsx"
            write(path)
            data = path.read_bytes()
        return Response(data, media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @api.get("/api/monthly/{month}/issues/export")
    def issues_excel(month: str, who: dict = Depends(admin)):
        year, mon = ym(month)
        with connection() as conn:
            invoices = repos(conn, who)[1]
            return excel(lambda p: export_issues(invoices, year, mon, p),
                         default_file_name(year, mon))

    @api.get("/api/monthly/{month}/matches/export")
    def matches_excel(month: str, who: dict = Depends(admin)):
        year, mon = ym(month)
        with connection() as conn:
            invoices = repos(conn, who)[1]
            return excel(lambda p: export_matches(invoices, year, mon, p), matches_file_name())

    # ---- Monthly inputs ---------------------------------------------------------------------
    def inputs_for_screen(inputs: InputsRepo, year: int, mon: int) -> dict:
        rates = inputs.auto_rates()
        before_label, before = inputs.previous_costs(year, mon)
        return {"label": month_label(year, mon), "saved": inputs.has_inputs(year, mon),
                "costs": [[h, a] for h, a in inputs.costs(year, mon)],
                "default_heads": list(DEFAULT_HEADS),
                "previous": {"label": before_label, "costs": [[h, a] for h, a in before]},
                "threshold": inputs.threshold(year, mon),
                "auto_rates": [{"key": key, "head": head, "pct": rates[key]}
                               for key, head, _, _ in AUTO_HEADS]}

    @api.get("/api/monthly/{month}/inputs")
    def get_inputs(month: str, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        with connection() as conn:
            return inputs_for_screen(repos(conn, who)[2], year, mon)

    @api.put("/api/monthly/{month}/inputs")
    def save_inputs(month: str, body: InputsBody, who: dict = Depends(admin)) -> dict:
        year, mon = ym(month)
        if not 0 <= body.threshold <= 100:
            raise HTTPException(400, "The high-profit threshold must be between 0 and 100.")
        with connection() as conn:
            inputs = repos(conn, who)[2]
            try:
                inputs.save_costs(year, mon, [(h, float(a)) for h, a in body.costs])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            inputs.save_threshold(year, mon, body.threshold)
            return inputs_for_screen(inputs, year, mon)

    @api.put("/api/monthly/auto-rates")
    def save_rates(body: RatesBody, who: dict = Depends(admin)) -> list[dict]:
        with connection() as conn:
            inputs = repos(conn, who)[2]
            try:
                inputs.save_auto_rates(body.rates)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            rates = inputs.auto_rates()
            return [{"key": key, "head": head, "pct": rates[key]} for key, head, _, _ in AUTO_HEADS]

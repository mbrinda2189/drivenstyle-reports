/*
 * Generate.tsx - "Generate reports", the main monthly screen
 * ==========================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * The month's work, in the order it is done:
 *
 *   1  Choose the report month       (starts on last month)
 *   2  Upload Zoho's invoice export  (Invoice.csv or .xlsx)        needed
 *   3  Upload Zoho's payments export (for the payment mode report) optional
 *   4  Upload the delivery (RTO) list (for the new-car sheets)     optional
 *      then  [Read invoices]  ->  [Generate workbook]
 *
 * WHAT IS DIFFERENT FROM THE DESKTOP SCREEN
 *   * Files are UPLOADED and kept on the server for the month, so History >
 *     Regenerate can use them again. Each file is checked when it arrives;
 *     a wrong file is refused and the month's present file stays.
 *   * The workbook is DOWNLOADED (there is no folder to choose).
 *
 * READ INVOICES reads the uploaded export for the month and saves the
 * invoices, replacing an earlier reading of the month. Fixes made on Scan
 * review are kept. The log says what was read, skipped and ignored.
 *
 * GENERATE WORKBOOK asks first, as the desktop does, when
 *   * issues are still open on Scan review - those invoices are left out of
 *     every report and listed on the workbook's "Not included" sheet;
 *   * the P&L or cost % report is ticked but no indirect costs were entered
 *     on Monthly inputs - they would show as zero.
 *
 * All reading and calculating is done on the server by the desktop tool's
 * own code (web/backend/monthly_api.py). This screen only shows the result.
 */
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, FileKind, GenerateResult, LogLine, Overview, inr, monthlyApi, showDateTime } from "../api";
import { MonthPicker, useMonth } from "../month";

const FILES: { kind: FileKind; step: string; title: string; about: string; accept: string }[] = [
  { kind: "invoices", step: "Step 2", title: "Zoho invoice export",
    about: "Zoho Books › Sales › Invoices › Export. Invoice.csv or .xlsx.", accept: ".csv,.xlsx" },
  { kind: "payments", step: "Step 3 · optional", title: "Zoho payments export",
    about: "Payments Received export, for the payment mode report.", accept: ".csv,.xlsx" },
  { kind: "rto", step: "Step 4 · optional", title: "Delivery (RTO) list",
    about: "The dealership's list of cars delivered, for the new-car reports.", accept: ".xlsx" },
];
const MASTERS: [string, string][] = [["products", "Products"], ["executives", "Sales executives"],
                                     ["cars", "Cars"], ["incentives", "Incentives"]];
const NEEDS_COSTS = ["Indirect vs direct cost %", "Profit & loss"];
const PAYMENT_REPORT = "Payment mode analysis";

export default function Generate({ onExpired }: { onExpired: () => void }) {
  const [month, setMonth] = useMonth();
  const [view, setView] = useState<Overview | null>(null);
  const [ticked, setTicked] = useState<string[] | null>(null);     // null = all, until changed
  const [pdf, setPdf] = useState(true);
  const [log, setLog] = useState<LogLine[]>([]);
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const [ask, setAsk] = useState<"issues" | "inputs" | null>(null);
  const [made, setMade] = useState<GenerateResult | null>(null);
  const pickers = useRef<Record<string, HTMLInputElement | null>>({});

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  const refresh = useCallback(async (m: string) => {
    try {
      setView(await monthlyApi.overview(m));
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    setView(null);
    setLog([]);
    setProblem("");
    setAsk(null);
    setMade(null);
    void refresh(month);
  }, [month, refresh]);

  /** Run something slow: show what is happening, then read the month again. */
  const work = async (what: string, action: () => Promise<void>) => {
    setBusy(what);
    setProblem("");
    try {
      await action();
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
      await refresh(month);
    }
  };

  const fileChosen = (kind: FileKind) => (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void work("Checking the file…", async () => { await monthlyApi.upload(month, kind, file); });
  };

  const read = () => work("Reading the invoices…", async () => {
    setMade(null);
    setLog((await monthlyApi.read(month)).log);
  });

  if (!view) {
    return <><h1>Generate reports</h1>{problem ? <div className="error">{problem}</div>
      : <p className="muted">Reading…</p>}</>;
  }

  const reports = ticked ?? view.reports;
  const toggle = (name: string) =>
    setTicked(reports.includes(name) ? reports.filter((r) => r !== name) : [...reports, name]);
  const scan = view.scan;
  const run = made?.run ?? view.last_run;

  const generate = (sure: "issues" | "inputs" | "start") => {
    // The same two questions the desktop asks before writing the workbook.
    if (sure === "start" && scan && scan.open_issues > 0) return setAsk("issues");
    if (sure !== "inputs" && !view.has_inputs && NEEDS_COSTS.some((r) => reports.includes(r))) {
      return setAsk("inputs");
    }
    setAsk(null);
    void work("Building the workbook…", async () => {
      const result = await monthlyApi.generate(month, view.reports.filter((r) => reports.includes(r)),
                                               pdf && view.pdf_possible);
      setMade(result);
      setLog((old) => [...old,
        { kind: "ok", text: `${result.run.file_name}: ${result.run.invoices} invoices, sales ₹${inr(result.run.sales)}, gross profit ₹${inr(result.run.gross_profit)}` },
        ...(result.pdf_error ? [{ kind: "error" as const, text: `PDF not made: ${result.pdf_error}` }] : []),
        ...(result.run.left_out ? [{ kind: "warn" as const,
          text: `${result.run.left_out} invoice${result.run.left_out === 1 ? "" : "s"} left out (see the “Not included” sheet).` }] : []),
      ]);
    });
  };

  return (
    <>
      <h1>Generate reports</h1>
      <p className="muted">Upload the month's Zoho files, read the invoices, then make the workbook.</p>

      <div className="steps">
        <div className="card step">
          <div className="step-no">Step 1</div>
          <div className="step-title">Report month</div>
          <MonthPicker month={month} onChange={setMonth} disabled={Boolean(busy)} />
        </div>
        {FILES.map((f) => {
          const file = view.files[f.kind];
          return (
            <div className="card step" key={f.kind}>
              <div className="step-no">{f.step}</div>
              <div className="step-title">{f.title}</div>
              {file ? (
                <div className="file-kept">
                  <strong>{file.name}</strong>
                  <span className="muted">Uploaded {showDateTime(file.at)}</span>
                </div>
              ) : <div className="muted">{f.about}</div>}
              <div className="row-actions left">
                <button className={file ? "btn" : "btn primary"} disabled={Boolean(busy)}
                        onClick={() => pickers.current[f.kind]?.click()}>
                  {file ? "Replace" : "Upload file"}</button>
                {file && <button className="btn" disabled={Boolean(busy)} onClick={() =>
                  void work("Removing…", async () => { await monthlyApi.removeFile(month, f.kind); })}>Remove</button>}
              </div>
              <input type="file" hidden accept={f.accept} aria-label={f.title}
                     ref={(el) => { pickers.current[f.kind] = el; }} onChange={fileChosen(f.kind)} />
            </div>
          );
        })}
      </div>

      <div className="two-col">
        <div className="card">
          <div className="card-head">
            <h2>Reports to include</h2>
            <button className="link" onClick={() =>
              setTicked(reports.length === view.reports.length ? [] : view.reports)}>
              {reports.length === view.reports.length ? "Clear all" : "Select all"}</button>
          </div>
          <div className="report-grid">
            {view.reports.map((name) => (
              <label className="check" key={name}>
                <input type="checkbox" checked={reports.includes(name)} onChange={() => toggle(name)} />
                {name}
              </label>
            ))}
          </div>
          {reports.includes(PAYMENT_REPORT) && !view.files.payments && (
            <p className="muted">Without the payments export, the payment mode report uses the
              invoice type printed in Zoho (UPI / Cash / CHY).</p>
          )}
          <label className="check">
            <input type="checkbox" checked={pdf && view.pdf_possible} disabled={!view.pdf_possible}
                   onChange={(e) => setPdf(e.target.checked)} />
            Also make the PDF
            {!view.pdf_possible && <span className="muted"> – LibreOffice is not installed on this server</span>}
          </label>
        </div>

        <div className="card">
          <h2>Run</h2>
          <div className="masters-in-use">
            {MASTERS.map(([key, title]) => (
              <span key={key} className={view.masters[key] ? "badge grey" : "badge amber"}>
                {title}: {view.masters[key] ?? 0}</span>
            ))}
          </div>
          {scan ? (
            <p className="scan-line">
              <strong>{scan.read} invoice{scan.read === 1 ? "" : "s"} read</strong> · {scan.open_issues} need
              {scan.open_issues === 1 ? "s" : ""} attention · {scan.skipped} skipped
              <span className="muted"> · last read {showDateTime(scan.scanned_at)} from {scan.source.split(/[\\/]/).pop()}</span>
              {scan.open_issues > 0 && <> · <Link to="/monthly/review">Review issues</Link></>}
            </p>
          ) : <p className="muted">{view.label} has not been read yet.</p>}

          <div className="row-actions left">
            <button className="btn" disabled={Boolean(busy) || !view.files.invoices} onClick={() => void read()}>
              Read invoices</button>
            <button className="btn primary" disabled={Boolean(busy) || !scan || !reports.length}
                    onClick={() => generate("start")}>Generate workbook</button>
          </div>
          {busy && <div className="note" role="status">{busy}</div>}
          {problem && <div className="error lines" role="alert">{problem}</div>}

          {ask === "issues" && scan && (
            <div className="apply-from">
              <strong>{scan.open_issues} issue{scan.open_issues === 1 ? " is" : "s are"} still open on Scan review.</strong>
              <p>{scan.invoices_held_back} invoice{scan.invoices_held_back === 1 ? "" : "s"} will be left out
                of the reports and listed on the “Not included” sheet.</p>
              <div className="row-actions left">
                <button className="btn primary" onClick={() => generate("issues")}>Generate anyway</button>
                <Link className="btn" to="/monthly/review">Review issues</Link>
              </div>
            </div>
          )}
          {ask === "inputs" && (
            <div className="apply-from">
              <strong>No indirect costs have been entered for {view.label}.</strong>
              <p>The profit &amp; loss and cost % reports will show indirect costs as zero.</p>
              <div className="row-actions left">
                <Link className="btn primary" to="/monthly/inputs">Enter them first</Link>
                <button className="btn" onClick={() => generate("inputs")}>Generate anyway</button>
              </div>
            </div>
          )}

          {run && (
            <div className="result">
              <div><strong>{run.file_name}</strong>
                <span className="muted"> · made {showDateTime(run.generated_at)}</span></div>
              <div className="muted">{run.invoices} invoices · sales ₹{inr(run.sales)} · gross profit ₹{inr(run.gross_profit)}</div>
              <div className="row-actions left">
                {run.available
                  ? <a className="btn primary" href={monthlyApi.downloadUrl(run.id)}>Download workbook</a>
                  : <span className="muted">This workbook was made on the desktop tool. Generate to make it here.</span>}
                {run.pdf_available && <a className="btn" href={monthlyApi.downloadUrl(run.id, true)}>Download PDF</a>}
              </div>
            </div>
          )}

          {log.length > 0 && (
            <ul className="log" aria-label="Log">
              {log.map((line, i) => <li key={i} className={line.kind}>{line.text}</li>)}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}

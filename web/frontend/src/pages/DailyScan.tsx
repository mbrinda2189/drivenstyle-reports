/*
 * DailyScan.tsx - "Scan invoices": the day's PDFs become payout lines
 * ===================================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 *   1. Choose the invoice PDFs saved from Zoho today (several at once).
 *      They are sent to the server and wait there ("Waiting to be scanned").
 *   2. Press Scan. For each invoice the server works out the labour, the
 *      spot incentive and the internal team amount and posts them to the
 *      payout register - with the same calculation as the monthly reports.
 *
 * AFTER A SCAN the screen says what became of every file:
 *      Posted            new lines in the register (listed, with total)
 *      Already posted    the invoice was posted before - left alone. An
 *                        invoice is never posted twice, whoever scans.
 *      In review         something must be decided first (an item, a
 *                        salesperson or a car not in the masters) -> Review
 *      Re-issued         the same invoice number now says something else:
 *                        unpaid lines are corrected, paid ones get an
 *                        adjustment line
 *      Before start date / Cancelled / Not used   left alone, with the reason
 * The numbers always add up to the number of files read.
 *
 * Invoices still "In review" are tried again by every scan, so nothing
 * needs to be uploaded twice.
 */
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, DailyOverview, ScanReport, dailyApi, inr, showDate } from "../api";

const TALLY: [string, string][] = [["posted", "Posted"], ["already posted", "Already posted"],
  ["re-issued", "Re-issued"], ["in review", "In review"], ["before start date", "Before start date"],
  ["cancelled", "Cancelled"], ["not used", "Not used"]];

export function ScanResult({ report }: { report: ScanReport }) {
  return (
    <div className="card">
      <h2>Result of the scan</h2>
      <div className="masters-in-use">
        <span className="badge blue plain">Files read: {report.tally.files ?? 0}</span>
        {TALLY.filter(([key]) => report.tally[key]).map(([key, title]) => (
          <span key={key} className={key === "posted" ? "badge green"
            : key === "in review" ? "badge amber" : "badge grey"}>{title}: {report.tally[key]}</span>
        ))}
      </div>
      {report.warnings.concat(report.notes).map((text, i) => <div key={i} className="warn">{text}</div>)}

      {report.posted.length > 0 && (
        <>
          <h3>Posted to the register · ₹{inr(report.posted_total)}</h3>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Invoice</th><th>Type</th><th>Pay to</th><th className="num">Amount (₹)</th><th>Working</th></tr></thead>
              <tbody>
                {report.posted.map((l) => (
                  <tr key={l.line_id}><td>{l.invoice_no}</td><td>{l.type}</td>
                    <td>{l.payee || "—"}</td><td className="num">{inr(l.amount)}</td>
                    <td className="working">{l.working}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {report.review.length > 0 && (
        <>
          <h3>In review · <Link to="/daily/review">go to Review</Link></h3>
          <ul className="details open">
            {report.review.map((r) => <li key={r.file_name}><strong>{r.invoice_no}</strong> – {r.reasons.join(" ")}</li>)}
          </ul>
        </>
      )}
      {report.not_used.length > 0 && (
        <>
          <h3>Not used</h3>
          <ul className="details open">
            {report.not_used.map((r) => <li key={r.file_name}><strong>{r.file_name}</strong> – {r.reasons.join(" ")}</li>)}
          </ul>
        </>
      )}
      {report.corrected > 0 && <p className="muted">{report.corrected} existing line(s) corrected.</p>}
    </div>
  );
}

export default function DailyScan({ onExpired }: { onExpired: () => void }) {
  const [view, setView] = useState<DailyOverview | null>(null);
  const [report, setReport] = useState<ScanReport | null>(null);
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const picker = useRef<HTMLInputElement>(null);

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem((old) => [old, error instanceof Error ? error.message : "Something went wrong."]
      .filter(Boolean).join("\n"));
  }, [onExpired]);

  const refresh = useCallback(async () => {
    try {
      setView(await dailyApi.overview());
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Send the chosen PDFs one after another; a refused file does not stop the rest. */
  const filesChosen = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])];
    event.target.value = "";
    setProblem("");
    for (let i = 0; i < files.length; i += 1) {
      setBusy(`Uploading ${i + 1} of ${files.length}…`);
      try {
        await dailyApi.upload(files[i]);
      } catch (error) {
        fail(error);
      }
    }
    setBusy("");
    await refresh();
  };

  const scan = async () => {
    setBusy("Reading the invoices and posting…");
    setProblem("");
    try {
      setReport(await dailyApi.scan());
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
      await refresh();
    }
  };

  if (!view) {
    return <><h1>Scan invoices</h1>{problem ? <div className="error lines">{problem}</div>
      : <p className="muted">Reading…</p>}</>;
  }
  const canScan = view.inbox.length > 0 || view.in_review > 0;

  return (
    <>
      <h1>Scan invoices</h1>
      <p className="muted">Upload today's invoice PDFs, then scan. Invoices dated before {showDate(view.start_date)} are left alone.</p>

      <div className="card dropzone">
        <div>
          <h2>Add invoice PDFs</h2>
          <div className="muted">Choose the files saved from Zoho. An invoice already posted is skipped.</div>
        </div>
        <div className="row-actions">
          <button className="btn" disabled={Boolean(busy)} onClick={() => picker.current?.click()}>Choose files</button>
          <button className="btn primary" disabled={Boolean(busy) || !canScan} onClick={() => void scan()}>
            Scan{view.inbox.length > 0 ? ` ${view.inbox.length} file${view.inbox.length === 1 ? "" : "s"}` : ""}</button>
        </div>
        <input ref={picker} type="file" accept=".pdf,application/pdf" multiple hidden onChange={filesChosen}
               aria-label="Invoice PDFs to scan" />
      </div>

      {busy && <div className="note" role="status">{busy}</div>}
      {problem && <div className="error lines" role="alert">{problem}</div>}
      {view.in_review > 0 && (
        <div className="note">{view.in_review} invoice{view.in_review === 1 ? " is" : "s are"} waiting in{" "}
          <Link to="/daily/review">Review</Link> and will be tried again by the next scan.</div>
      )}

      {view.inbox.length > 0 && (
        <div className="card table-card">
          <h2 className="in-card">Waiting to be scanned ({view.inbox.length})</h2>
          <div className="table-scroll short">
            <table>
              <tbody>
                {view.inbox.map((f) => (
                  <tr key={f.name}>
                    <td>{f.name}</td>
                    <td className="num muted">{Math.max(1, Math.round(f.size / 1024))} KB</td>
                    <td className="row-actions"><button className="btn" disabled={Boolean(busy)} onClick={async () => {
                      await dailyApi.removeUpload(f.name).catch(fail);
                      await refresh();
                    }}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {report && <ScanResult report={report} />}
    </>
  );
}

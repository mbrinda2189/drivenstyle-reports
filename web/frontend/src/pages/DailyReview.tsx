/*
 * DailyReview.tsx - Invoices the daily scan could not post yet
 * ============================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * An invoice is held back ("In review") when something on it is not in the
 * masters - an item name, the salesperson, the vehicle - or its totals do
 * not agree. Nothing is guessed: until it is settled, no line of that
 * invoice is posted.
 *
 * TO DECIDE (one row per thing, however many invoices it holds up)
 *   Click the row, choose the master record ("Others (not in master)" is
 *   offered for a salesperson or vehicle), Save. The choice is remembered
 *   for every invoice showing that name - and it is THE SAME saved match
 *   the monthly Scan review uses, so it is made once for both tools.
 *   A totals difference is accepted per invoice, after checking in Zoho.
 *   As soon as a fix is saved the waiting invoices are scanned again, and
 *   what can now be posted is posted (shown under "Result of the scan").
 *
 *   If the name is simply missing from the masters, add it on Masters
 *   instead; the next scan then posts the invoice by itself.
 *
 * INVOICES WAITING
 *   The invoices held back, with the reason. "Cancel invoice" (reason
 *   needed) marks one as not to be posted at all.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, Choice, PayoutInvoice, ReviewIssue, ScanReport, dailyApi } from "../api";
import { Chooser } from "../month";
import { ScanResult } from "./DailyScan";

type Lists = Record<"Item" | "Salesperson" | "Car", Choice[]>;

export default function DailyReview({ onExpired }: { onExpired: () => void }) {
  const [issues, setIssues] = useState<ReviewIssue[] | null>(null);
  const [waiting, setWaiting] = useState<PayoutInvoice[]>([]);
  const [lists, setLists] = useState<Lists | null>(null);
  const [open, setOpen] = useState("");
  const [pick, setPick] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState("");
  const [reason, setReason] = useState("");
  const [report, setReport] = useState<ScanReport | null>(null);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  const load = useCallback(async () => {
    try {
      const [reply, choices] = await Promise.all([dailyApi.review(), dailyApi.choices()]);
      setIssues(reply.issues);
      setWaiting(reply.invoices);
      setLists(choices);
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    void load();
  }, [load]);

  const id = (i: ReviewIssue) => `${i.kind}|${i.printed}|${i.invoices.join(",")}`;

  /** Save a fix; the server scans the waiting invoices again and says what it posted. */
  const fix = async (action: () => Promise<{ done: string; report: ScanReport | null }>) => {
    setBusy(true);
    setProblem("");
    try {
      const reply = await action();
      setNotice(reply.done);
      setReport(reply.report);
      setOpen("");
      await load();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (invoiceNo: string) => {
    setProblem("");
    try {
      const reply = await dailyApi.cancel(invoiceNo, reason);
      setNotice(`Invoice ${invoiceNo} cancelled.` + (reply.paid_lines_left.length
        ? ` Already paid and left as they are: ${reply.paid_lines_left.join(", ")}.` : ""));
      setCancelling("");
      setReason("");
      await load();
    } catch (error) {
      fail(error);
    }
  };

  return (
    <>
      <h1>Review</h1>
      <p className="muted">Invoices the scan could not post yet. A fix here is remembered, also for the monthly reports.</p>
      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      <div className="card table-card">
        <h2 className="in-card">To decide</h2>
        <div className="table-scroll">
          <table className="rows wrap">
            <thead><tr><th>Type</th><th>What needs deciding</th><th>Invoices</th><th>Fix</th></tr></thead>
            <tbody>
              {issues === null && <tr><td colSpan={4} className="muted">Reading…</td></tr>}
              {issues?.length === 0 && <tr><td colSpan={4} className="muted">Nothing to decide.
                {waiting.length === 0 && " Every invoice scanned so far is posted."}</td></tr>}
              {issues?.map((issue) => (
                <tr key={id(issue)} onClick={() => { if (open !== id(issue)) { setOpen(id(issue)); setPick(null); } }}>
                  <td className="nowrap"><span className="badge amber">{issue.kind}</span></td>
                  <td>{issue.message}</td>
                  <td>{issue.invoices.join(", ")}</td>
                  <td className="fix-cell">
                    {open !== id(issue) ? <span className="muted">Click to {issue.kind === "Totals" ? "check or accept" : "choose"}</span>
                      : issue.kind === "Totals" ? (
                        <div className="fix" onClick={(e) => e.stopPropagation()}>
                          {issue.invoices.map((no) => (
                            <button key={no} className="btn primary" disabled={busy}
                                    onClick={() => void fix(() => dailyApi.acceptTotals(no))}>Accept {no}</button>
                          ))}
                        </div>
                      ) : lists && (
                        <div className="fix" onClick={(e) => e.stopPropagation()}>
                          <Chooser choices={lists[issue.kind]} placeholder="Type to find…"
                                   label={`Master record for ${issue.printed || issue.invoices.join(", ")}`}
                                   onPick={setPick} />
                          <button className="btn primary" disabled={pick === null || busy} onClick={() =>
                            void fix(() => dailyApi.match(issue.kind, issue.printed, issue.invoices, pick as number))}>
                            Save</button>
                          {issue.suggestions.length > 0 &&
                            <span className="muted hint">Likely: {issue.suggestions.join("; ")}</span>}
                        </div>
                      )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card table-card">
        <h2 className="in-card">Invoices waiting ({waiting.length})</h2>
        <div className="table-scroll">
          <table className="wrap">
            <thead><tr><th>Invoice</th><th>Date</th><th>Customer</th><th>Salesperson</th><th>Why it waits</th><th /></tr></thead>
            <tbody>
              {waiting.length === 0 && <tr><td colSpan={6} className="muted">No invoice is waiting.</td></tr>}
              {waiting.map((inv) => (
                <tr key={inv.invoice_no}>
                  <td className="nowrap"><strong>{inv.invoice_no}</strong></td>
                  <td className="nowrap">{inv.invoice_date}</td>
                  <td>{inv.customer}</td>
                  <td>{inv.salesperson}</td>
                  <td>{inv.reason}</td>
                  <td className="fix-cell">
                    {cancelling === inv.invoice_no ? (
                      <div className="fix">
                        <input className="chooser" value={reason} placeholder="Reason for cancelling"
                               aria-label={`Reason for cancelling ${inv.invoice_no}`}
                               onChange={(e) => setReason(e.target.value)} />
                        <button className="btn danger" disabled={!reason.trim()} onClick={() => void cancel(inv.invoice_no)}>Cancel invoice</button>
                        <button className="btn" onClick={() => setCancelling("")}>Back</button>
                      </div>
                    ) : <div className="row-actions"><button className="btn" onClick={() => { setCancelling(inv.invoice_no); setReason(""); }}>Cancel invoice…</button></div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {report && <ScanResult report={report} />}
      <div className="row-actions left"><Link className="btn" to="/daily/payouts">Go to Payouts</Link></div>
    </>
  );
}

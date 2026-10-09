/*
 * History.tsx - Workbooks made and months read
 * ============================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * WORKBOOKS (the latest of each month, newest month first)
 *   Download     the Excel workbook (and the PDF when one was made)
 *   Make PDF     the PDF for that workbook, from the data as it is now
 *   Regenerate   the same reports again - e.g. after fixing Scan review
 *                issues or correcting a rate. Earlier months still use the
 *                amounts that applied then (effective dates).
 *   Remove       takes the month out of this list and deletes its
 *                workbooks from the server.
 *   A workbook made on the DESKTOP tool (brought across with the data) is
 *   listed with its figures, but its file is not on the server: Regenerate
 *   makes it here. That needs the month's Zoho files to be uploaded on
 *   Generate reports only if the payments or RTO sheets are wanted - the
 *   invoices themselves are already in the database.
 *
 * MONTHS READ INTO THE TOOL
 *   Every month whose invoices are in the tool. These feed the month-on-
 *   month Trend report. "Remove month" takes a month's invoices out (it
 *   then leaves the trend); reading its export again brings it back. The
 *   masters, the name matches and the month's Monthly inputs stay.
 *
 * Removing asks for confirmation in the row itself; both removals are
 * written to the audit log by the server.
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, Run, inr, monthlyApi, showDateTime } from "../api";

type Months = Awaited<ReturnType<typeof monthlyApi.history>>["months"];

export default function History({ onExpired }: { onExpired: () => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [months, setMonths] = useState<Months>([]);
  const [pdfPossible, setPdfPossible] = useState(false);
  const [asking, setAsking] = useState("");            // "run|2026-09" or "month|2026-09"
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");

  const load = useCallback(async () => {
    try {
      const reply = await monthlyApi.history();
      setRuns(reply.runs);
      setMonths(reply.months);
      setPdfPossible(reply.pdf_possible);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    }
  }, [onExpired]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Run an action, say what it did, read the lists again. */
  const act = async (what: string, action: () => Promise<string>) => {
    setBusy(what);
    setProblem("");
    setNotice("");
    setAsking("");
    try {
      setNotice(await action());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setBusy("");
      await load();
    }
  };

  return (
    <>
      <h1>History</h1>
      <p className="muted">Workbooks already made, and the months whose invoices are in the tool.</p>
      {busy && <div className="note" role="status">{busy}</div>}
      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      <div className="card table-card">
        <h2 className="in-card">Workbooks</h2>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Month</th><th className="num">Invoices</th><th className="num">Left out</th>
                       <th className="num">Sales (₹)</th><th className="num">Gross profit (₹)</th>
                       <th>Generated on</th><th>By</th><th /></tr></thead>
            <tbody>
              {runs === null && <tr><td colSpan={8} className="muted">Reading…</td></tr>}
              {runs?.length === 0 && <tr><td colSpan={8} className="muted">No workbook has been generated yet.</td></tr>}
              {runs?.map((r) => (
                <tr key={r.id}>
                  <td><strong>{r.label}</strong>{!r.available && <span className="badge grey">Made on the desktop</span>}</td>
                  <td className="num">{r.invoices}</td>
                  <td className="num">{r.left_out}</td>
                  <td className="num">{inr(r.sales)}</td>
                  <td className="num">{inr(r.gross_profit)}</td>
                  <td>{showDateTime(r.generated_at)}</td>
                  <td>{r.user}</td>
                  <td className="row-actions">
                    {asking === `run|${r.month}` ? (
                      <>
                        <span>Remove {r.label} from History?</span>
                        <button className="btn danger" onClick={() => void act("Removing…", async () => {
                          await monthlyApi.removeRuns(r.month);
                          return `${r.label} removed from History.`;
                        })}>Yes</button>
                        <button className="btn" onClick={() => setAsking("")}>No</button>
                      </>
                    ) : (
                      <>
                        {r.available && <a className="btn primary" href={monthlyApi.downloadUrl(r.id)}>Download</a>}
                        {r.pdf_available && <a className="btn" href={monthlyApi.downloadUrl(r.id, true)}>PDF</a>}
                        {r.available && !r.pdf_available && pdfPossible && (
                          <button className="btn" disabled={Boolean(busy)} onClick={() => void act("Making the PDF…", async () => {
                            await monthlyApi.makePdf(r.id);
                            return `PDF made for ${r.label}.`;
                          })}>Make PDF</button>
                        )}
                        <button className="btn" disabled={Boolean(busy)} onClick={() => void act("Building the workbook…", async () => {
                          const done = await monthlyApi.regenerate(r.id);
                          return `${done.run.file_name} made.` + (done.pdf_error ? ` PDF not made: ${done.pdf_error}` : "");
                        })}>Regenerate</button>
                        <button className="btn" disabled={Boolean(busy)} onClick={() => setAsking(`run|${r.month}`)}>Remove</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card table-card">
        <h2 className="in-card">Months read into the tool</h2>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Month</th><th className="num">Invoices</th><th>Read on</th><th>From</th><th /></tr></thead>
            <tbody>
              {months.length === 0 && <tr><td colSpan={5} className="muted">No month has been read yet.</td></tr>}
              {months.map((m) => (
                <tr key={m.month}>
                  <td><strong>{m.label}</strong></td>
                  <td className="num">{m.invoices}</td>
                  <td>{showDateTime(m.scanned_at)}</td>
                  <td>{m.folder.split(/[\\/]/).pop()}</td>
                  <td className="row-actions">
                    {asking === `month|${m.month}` ? (
                      <>
                        <span>Take {m.invoices} invoices of {m.label} out of the tool?</span>
                        <button className="btn danger" onClick={() => void act("Removing…", async () => {
                          const done = await monthlyApi.removeMonth(m.month);
                          return `${done.removed} invoices of ${m.label} removed. Read the export again to bring them back.`;
                        })}>Yes</button>
                        <button className="btn" onClick={() => setAsking("")}>No</button>
                      </>
                    ) : <button className="btn" disabled={Boolean(busy)} onClick={() => setAsking(`month|${m.month}`)}>Remove month</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

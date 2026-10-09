/*
 * DailySummary.tsx - Payout slip, summary and month check
 * =======================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * Three ways of looking at the payout register. Nothing here changes it.
 *
 * PAYOUT SLIP
 *   One sheet to pay from, or to file: "To pay" (every pending line) or
 *   "Paid on <date>". Grouped as the desktop slip: one block per kind of
 *   labour, one per sales executive, then the internal team, each with its
 *   total. It opens in a new tab with a Print button (print, or "Save as
 *   PDF" in the print window).
 *
 * SUMMARY
 *   Pending and paid by person; what was paid on each day; and by invoice
 *   month: due, paid, pending, on hold. Cancelled lines are not counted.
 *
 * MONTH CHECK
 *   The control between the two tools. For one month the register is set
 *   beside the monthly tool's own figures (those of its Labour and Spot
 *   incentive sheets). Every row should show a difference of 0.00.
 *     * The monthly report rounds each executive's incentive UP to the
 *       next Rs. 10; the daily lines are exact. That rounding is shown in
 *       its own box - it is expected, not an error.
 *     * A real difference nearly always has a plain cause, which is listed
 *       by invoice number: an invoice in Zoho's export that was never
 *       scanned daily (or is still in Review), or an invoice scanned daily
 *       that the monthly tool left out or does not have.
 *   The month must have been read on Monthly reports > Generate reports;
 *   until then only the register's side is shown.
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, DailySummary as Summary, MonthCheck, dailyApi, inr, showDate, today } from "../api";
import { MonthPicker, useMonth } from "../month";

type Tab = "slip" | "summary" | "check";

export default function DailySummary({ onExpired }: { onExpired: () => void }) {
  const [tab, setTab] = useState<Tab>("slip");
  const [month, setMonth] = useMonth();
  const [paidOn, setPaidOn] = useState(today());
  const [summary, setSummary] = useState<Summary | null>(null);
  const [check, setCheck] = useState<MonthCheck | null>(null);
  const [problem, setProblem] = useState("");

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  useEffect(() => {
    setProblem("");
    if (tab === "summary") dailyApi.summary().then(setSummary).catch(fail);
    if (tab === "check") {
      setCheck(null);
      dailyApi.monthCheck(month).then(setCheck).catch(fail);
    }
  }, [tab, month, fail]);

  const diff = (value: number | null) => (value === null ? "—"
    : <span className={Math.abs(value) < 0.005 ? "ok-text" : "amber-text"}>{inr(value)}</span>);

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Summary</h1>
          <p className="muted">The payout slip, totals, and the check against the monthly reports.</p>
        </div>
        <a className="btn" href={dailyApi.exportUrl}>Export register to Excel</a>
      </div>

      <div className="subtabs" role="tablist">
        {([["slip", "Payout slip"], ["summary", "Summary"], ["check", "Month check"]] as [Tab, string][])
          .map(([key, title]) => (
            <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                    className={tab === key ? "subtab on" : "subtab"}>{title}</button>))}
      </div>
      {problem && <div className="error lines" role="alert">{problem}</div>}

      {tab === "slip" && (
        <div className="two-col">
          <div className="card">
            <h2>To pay</h2>
            <p className="muted">Every pending line, grouped by kind of labour and by person, with totals.</p>
            <a className="btn primary" href={dailyApi.slipUrl()} target="_blank" rel="noreferrer">Open the slip</a>
          </div>
          <div className="card">
            <h2>Paid on a day</h2>
            <p className="muted">What went out on one day, for filing with the proofs.</p>
            <div className="fix">
              <input type="date" value={paidOn} max={today()} aria-label="Paid on"
                     onChange={(e) => setPaidOn(e.target.value)} />
              <a className="btn primary" href={dailyApi.slipUrl(paidOn)} target="_blank" rel="noreferrer">Open the slip</a>
            </div>
          </div>
        </div>
      )}

      {tab === "summary" && (summary === null ? <p className="muted">Reading…</p> : (
        <>
          <div className="card table-card">
            <h2 className="in-card">By person</h2>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Type</th><th>Pay to</th><th className="num">Pending (₹)</th><th className="num">Paid (₹)</th></tr></thead>
                <tbody>
                  {summary.by_payee.length === 0 && <tr><td colSpan={4} className="muted">The register is empty.</td></tr>}
                  {summary.by_payee.map((r) => (
                    <tr key={`${r.type}|${r.payee}`}><td>{r.type}</td><td>{r.payee || "—"}</td>
                      <td className="num">{inr(r.pending)}</td><td className="num">{inr(r.paid)}</td></tr>
                  ))}
                  {summary.by_payee.length > 0 && (
                    <tr className="total-row"><td>Total</td><td />
                      <td className="num">{inr(summary.by_payee.reduce((s, r) => s + r.pending, 0))}</td>
                      <td className="num">{inr(summary.by_payee.reduce((s, r) => s + r.paid, 0))}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="two-col">
            <div className="card table-card">
              <h2 className="in-card">By invoice month</h2>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Month</th><th className="num">Due (₹)</th><th className="num">Paid (₹)</th>
                             <th className="num">Pending (₹)</th><th className="num">On hold (₹)</th></tr></thead>
                  <tbody>
                    {summary.by_month.length === 0 && <tr><td colSpan={5} className="muted">Nothing yet.</td></tr>}
                    {summary.by_month.map((m) => (
                      <tr key={m.month}><td>{m.label}</td><td className="num">{inr(m.due)}</td>
                        <td className="num">{inr(m.paid)}</td><td className="num">{inr(m.pending)}</td>
                        <td className="num">{inr(m.hold)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="card table-card">
              <h2 className="in-card">Paid, by day</h2>
              <div className="table-scroll short">
                <table>
                  <thead><tr><th>Paid on</th><th className="num">Lines</th><th className="num">Amount (₹)</th><th /></tr></thead>
                  <tbody>
                    {summary.by_day.length === 0 && <tr><td colSpan={4} className="muted">No payment recorded yet.</td></tr>}
                    {summary.by_day.map((d) => (
                      <tr key={d.date}><td>{showDate(d.date)}</td><td className="num">{d.lines}</td>
                        <td className="num">{inr(d.amount)}</td>
                        <td className="row-actions"><a href={dailyApi.slipUrl(d.date)} target="_blank" rel="noreferrer">Slip</a></td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      ))}

      {tab === "check" && (
        <>
          <div className="card filters">
            <MonthPicker month={month} onChange={setMonth} />
            <span className="muted grow-text">Register (daily payouts) beside the monthly tool, for invoices dated in the month.</span>
          </div>
          {check === null ? <p className="muted">Reading…</p> : (
            <>
              {!check.monthly_read && (
                <div className="note">The monthly tool has not read {check.label} yet, so only the register's
                  side is shown. An admin reads it on Monthly reports › Generate reports.</div>
              )}
              {check.totals && (
                <div className={Math.abs(check.totals.difference) < 0.005 ? "result" : "apply-from"}>
                  <strong>{Math.abs(check.totals.difference) < 0.005
                    ? `${check.label}: the register agrees with the monthly tool.`
                    : `${check.label}: the register is ₹${inr(Math.abs(check.totals.difference))} ${
                      check.totals.difference < 0 ? "below" : "above"} the monthly tool.`}</strong>{" "}
                  <span className="muted">{check.register_invoices} invoice{check.register_invoices === 1 ? "" : "s"} of the month in the register.</span>
                </div>
              )}
              <div className="card table-card top-gap">
                <div className="table-scroll">
                  <table>
                    <thead><tr><th>Kind</th><th>Labour type / pay to</th><th className="num">Register (₹)</th>
                               <th className="num">Monthly tool (₹)</th><th className="num">Difference (₹)</th></tr></thead>
                    <tbody>
                      {check.rows.length === 0 && <tr><td colSpan={5} className="muted">No line of this month in the register.</td></tr>}
                      {check.rows.map((r) => (
                        <tr key={`${r.group}|${r.label}`}><td>{r.group}</td><td>{r.label}</td>
                          <td className="num">{inr(r.register)}</td>
                          <td className="num">{r.monthly === null ? "—" : inr(r.monthly)}</td>
                          <td className="num">{diff(r.difference)}</td></tr>
                      ))}
                      {check.totals && (
                        <tr className="total-row"><td>Total</td><td />
                          <td className="num">{inr(check.totals.register)}</td>
                          <td className="num">{inr(check.totals.monthly)}</td>
                          <td className="num">{diff(check.totals.difference)}</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {check.rounding && (
                <div className="card">
                  <h2>Month-end rounding – expected, not a difference</h2>
                  <p className="muted">The monthly Spot incentive report rounds each executive's total up to the
                    next ₹10. The daily lines are exact.</p>
                  <p>Exact ₹{inr(check.rounding.exact)} → in the monthly report ₹{inr(check.rounding.rounded)}
                    {" "}(rounding ₹{inr(check.rounding.amount)}).</p>
                </div>
              )}

              {(check.not_scanned.length > 0 || check.not_in_monthly.length > 0 || check.left_out.length > 0) && (
                <div className="card">
                  <h2>Where a difference comes from</h2>
                  {check.not_scanned.length > 0 && (
                    <>
                      <h3>In the monthly tool, not in the register ({check.not_scanned.length})</h3>
                      <ul className="details">
                        {check.not_scanned.map((n) => <li key={n.invoice_no}><strong>{n.invoice_no}</strong> – {n.why}</li>)}
                      </ul>
                    </>
                  )}
                  {check.left_out.length > 0 && (
                    <>
                      <h3>In the register, left out by the monthly tool (open Scan review issue)</h3>
                      <p>{check.left_out.join(", ")}</p>
                    </>
                  )}
                  {check.not_in_monthly.length > 0 && (
                    <>
                      <h3>In the register, not in the monthly tool's invoices</h3>
                      <p>{check.not_in_monthly.join(", ")}</p>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}

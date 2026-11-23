/*
 * WorkingDialog.tsx - "Show working" for one invoice (v0.37.0)
 * ============================================================
 *
 * WHY: the client's staff check the daily payouts by hand. This window
 * shows, for ONE invoice, how the tool reached every amount - in the order
 * she would check it on paper (Brinda, 23-11-2026):
 *
 *   1. What was read      invoice no, date, customer, car, executive, total
 *   2. Items              each item as printed and the master product it was
 *                         read as (same name / saved match), qty, typed price,
 *                         discount share, paid, fixed price and where from
 *   3. Labour             per kind of work: rate x qty = amount, rate date
 *   4. Spot incentive     every incentive x qty, package, then the steps with
 *                         the invoice's own numbers (paid vs fixed prices,
 *                         share earned, payable) - not rounded here
 *   5. Internal team      internal incentive x qty
 *   6. Payout lines       the lines the working gives, with their status now
 *   History / check       when it was calculated, by whom and why (Posted,
 *                         Recalculated ...); "Mark as checked" - OPTIONAL,
 *                         never needed to pay, logged in History
 *
 * The working shown is the one STORED when the amounts were written
 * (payout_store.py), so a master changed later does not change it.
 * Invoices posted before v0.37.0 have none: "Make the working" works it out
 * from the kept PDF and keeps it only if it gives the very amounts posted.
 *
 * Downloads: this invoice as PDF or Excel. WorkingsExportDialog (below) is
 * the Excel for a day / date range, with check formulas.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, WorkingView, dailyApi, downloadFile, inr, showDate, today } from "../api";

const qty = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

export default function WorkingDialog({ invoiceNo, onClose, onChanged, onExpired }: {
    invoiceNo: string; onClose: () => void; onChanged: () => void; onExpired: () => void }) {
  const [view, setView] = useState<WorkingView | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  // Read the working once per invoice (not again each time the Payouts list
  // behind the window is read again).
  useEffect(() => {
    dailyApi.working(invoiceNo).then(setView).catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceNo]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  /** Run a server action that answers with the new view. */
  const run = async (action: () => Promise<WorkingView>, changes = true) => {
    setBusy(true);
    setProblem("");
    try {
      setView(await action());
      if (changes) onChanged();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const get = async (format: "pdf" | "xlsx") => {
    setBusy(true);
    setProblem("");
    try {
      await downloadFile(dailyApi.workingFileUrl(invoiceNo, format), `Working_${invoiceNo}.${format}`);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const w = view?.working ?? null;
  const status = Object.fromEntries((view?.lines ?? []).map((l) => [l.line_id, l.status]));
  const adjustments = (view?.lines ?? []).filter((l) => l.line_id.includes("-ADJ"));
  const check = view?.check ?? null;

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog wide working" role="dialog" aria-modal="true" aria-labelledby="working-title">
        <div className="dialog-col">
          <h2 id="working-title">Working - invoice {invoiceNo}</h2>
          <div className="dialog-body">
            {!view && !problem && <p className="muted">Reading…</p>}

            {view && !w && (
              <div className="note blue">
                <p>This invoice was posted before the tool kept the full working (v0.37.0).</p>
                {view.rebuildable ? (
                  <p>“Make the working” works it out again from its PDF. It is kept only if it gives
                    exactly the amounts already posted; if the masters have changed since, you will be
                    told, and Recalculate… brings the unpaid lines up to date.</p>
                ) : <p className="muted">It is not posted, so there is no working to show.</p>}
                {view.lines.length > 0 && (
                  <p className="muted">Short working of each line: {view.lines.map((l) =>
                    `${l.type} ₹${inr(l.amount)}: ${l.working}`).join(" · ")}</p>
                )}
              </div>
            )}

            {w && (
              <>
                <h3>1. What was read from the invoice</h3>
                <table className="rows plain compact">
                  <tbody>
                    <tr><th>Invoice</th><td>{w.invoice_no} · {showDate(w.invoice_date)}</td>
                      <th>Sales executive</th><td>{w.executive}{w.printed_executive && ` (printed: ${w.printed_executive})`}
                        {w.branch && ` · ${w.branch}`}</td></tr>
                    <tr><th>Customer</th><td>{w.customer}</td><th>Car</th><td>{w.car}</td></tr>
                    <tr><th>Invoice total</th><td>₹{inr(w.total)}</td>
                      <th>Discount / GST</th><td>₹{inr(w.discount)} / ₹{inr(w.gst)}</td></tr>
                  </tbody>
                </table>
                {w.markers > 0 && <p className="muted small">{w.markers} “Labour charges” line(s) of ₹1 are only markers
                  that labour was done; labour comes from the Product master.</p>}

                <h3>2. Items on the invoice</h3>
                <div className="table-scroll">
                  <table className="rows plain compact">
                    <thead><tr><th>Printed on invoice</th><th>Read as</th><th className="num">Qty</th>
                      <th className="num">Typed / unit</th><th className="num">Discount</th>
                      <th className="num">Paid (with GST)</th><th className="num">Fixed / unit</th><th>Fixed price from</th>
                      <th className="num">Fixed value</th><th className="num">Labour</th><th className="num">Incentive</th></tr></thead>
                    <tbody>
                      {w.items.map((i, n) => (
                        <tr key={n}>
                          <td>{i.printed}</td>
                          <td>{i.product}{i.matched !== "Same name" && <span className="badge amber">saved match</span>}</td>
                          <td className="num">{qty(i.qty)}</td><td className="num">{inr(i.typed_unit)}</td>
                          <td className="num">{inr(i.discount)}</td><td className="num">{inr(i.paid)}</td>
                          <td className="num">{inr(i.fixed_price)}</td>
                          <td>{i.fixed_source_text}{i.in_package && " - in package"}</td>
                          <td className="num">{inr(i.fixed_value)}</td><td className="num">{inr(i.labour)}</td>
                          <td className="num">{inr(i.incentive)}</td>
                        </tr>
                      ))}
                      <tr className="total">
                        <td colSpan={4}>Total</td>
                        <td className="num">{inr(w.items.reduce((s, i) => s + i.discount, 0))}</td>
                        <td className="num">{inr(w.incentive.paid)}</td><td colSpan={2} />
                        <td className="num">{inr(w.items.reduce((s, i) => s + i.fixed_value, 0))}</td>
                        <td className="num">{inr(w.labour.total)}</td>
                        <td className="num">{inr(w.items.reduce((s, i) => s + i.incentive, 0))}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <h3>3. Labour <span className="muted small">(Product master labour charge × quantity, rate in force on the invoice date)</span></h3>
                {w.labour.groups.length === 0 && <p className="muted">No item on this invoice carries labour.</p>}
                {w.labour.groups.length > 0 && (
                  <table className="rows plain compact">
                    <thead><tr><th>Kind</th><th>Product</th><th>Rate from</th><th className="num">Rate</th>
                      <th className="num">Qty</th><th className="num">Amount (₹)</th></tr></thead>
                    <tbody>
                      {w.labour.groups.map((g) => [
                        ...g.items.map((i, n) => (
                          <tr key={`${g.kind}${n}`}><td>{n === 0 ? g.kind : ""}</td><td>{i.product}</td>
                            <td>{showDate(i.rate_from)}</td><td className="num">{inr(i.rate)}</td>
                            <td className="num">{qty(i.qty)}</td><td className="num">{inr(i.amount)}</td></tr>)),
                        <tr key={`${g.kind}-t`} className="total"><td colSpan={5}>Labour - {g.kind}</td>
                          <td className="num">{inr(g.total)}</td></tr>,
                      ])}
                    </tbody>
                  </table>
                )}

                <h3>4. Spot incentive <span className="muted small">(payable to {w.incentive.payee})</span></h3>
                {w.incentive.items.length > 0 && (
                  <table className="rows plain compact">
                    <thead><tr><th>Product</th><th>Incentive group</th><th>Rate from</th>
                      <th className="num">Incentive / unit</th><th className="num">Qty</th><th className="num">Amount (₹)</th></tr></thead>
                    <tbody>{w.incentive.items.map((i, n) => (
                      <tr key={n}><td>{i.product}</td><td>{i.group}</td><td>{showDate(i.rate_from)}</td>
                        <td className="num">{inr(i.rate)}</td><td className="num">{qty(i.qty)}</td>
                        <td className="num">{inr(i.amount)}</td></tr>))}</tbody>
                  </table>
                )}
                {w.incentive.package && (
                  <p>Package sold: <strong>{w.incentive.package.name}</strong> (all its items are on the invoice:
                    {" "}{w.incentive.package.items.join(", ")}). Package incentive ₹{inr(w.incentive.package.incentive)};
                    its items count at the coupon value ₹{inr(w.incentive.package.coupon_value)} as their fixed price.</p>
                )}
                <ol className="working-steps">{w.incentive.steps.map((s) => <li key={s}>{s}</li>)}</ol>
                <p><strong>Spot incentive payable: ₹{inr(w.incentive.payable)}</strong></p>

                <h3>5. Internal team incentive</h3>
                {w.internal.items.length === 0 ? <p className="muted">None on this invoice.</p> : (
                  <table className="rows plain compact">
                    <thead><tr><th>Product</th><th className="num">Rate</th><th className="num">Qty</th>
                      <th className="num">Amount (₹)</th></tr></thead>
                    <tbody>
                      {w.internal.items.map((i, n) => <tr key={n}><td>{i.product}</td><td className="num">{inr(i.rate)}</td>
                        <td className="num">{qty(i.qty)}</td><td className="num">{inr(i.amount)}</td></tr>)}
                      <tr className="total"><td colSpan={3}>Internal team</td><td className="num">{inr(w.internal.total)}</td></tr>
                    </tbody>
                  </table>
                )}

                <h3>6. Payout lines</h3>
                <table className="rows plain compact">
                  <thead><tr><th>Line</th><th>Type</th><th>Pay to</th><th className="num">Amount (₹)</th><th>Status now</th></tr></thead>
                  <tbody>
                    {w.lines.map((l) => <tr key={l.line_id}><td>{l.line_id}</td><td>{l.type}</td><td>{l.payee || "—"}</td>
                      <td className="num">{inr(l.amount)}</td><td>{status[l.line_id] ?? ""}</td></tr>)}
                    <tr className="total"><td colSpan={3}>Total</td>
                      <td className="num">{inr(w.lines.reduce((s, l) => s + l.amount, 0))}</td><td /></tr>
                  </tbody>
                </table>
                {adjustments.length > 0 && <p className="muted small">Adjustment lines (invoice re-issued after payment):{" "}
                  {adjustments.map((l) => `${l.line_id} ₹${inr(l.amount)} (${l.status})`).join("; ")}</p>}

                <h3>History of this working</h3>
                <ul className="details">{view!.history.map((h, n) => (
                  <li key={h.id}>{h.why} on {h.made_at} by {h.made_by} - lines ₹{inr(h.amount)}
                    {n === 0 ? " (shown above)" : ""}</li>))}</ul>

                <div className={`check-box ${check ? (check.current ? "done" : "old") : ""}`}>
                  {check ? (
                    <p><strong>{check.current ? "✓ Checked" : "Checked an earlier working"}</strong> by {check.checked_by} on {check.checked_at}
                      {check.note && ` - ${check.note}`}
                      {!check.current && ". The invoice was recalculated since; check it again."}</p>
                  ) : <p className="muted">Not marked as checked. Checking is optional - a line can be paid without it.</p>}
                  <form className="inline" onSubmit={(e: FormEvent) => {
                    e.preventDefault();
                    void run(() => dailyApi.checkWorking(invoiceNo, true, note)).then(() => setNote(""));
                  }}>
                    <input aria-label="Note (optional)" placeholder="Note (optional)" value={note}
                           onChange={(e) => setNote(e.target.value)} />
                    <button className="btn primary" disabled={busy}>
                      {check?.current ? "Check again" : "Mark as checked"}</button>
                    {check && <button type="button" className="btn" disabled={busy}
                      onClick={() => void run(() => dailyApi.checkWorking(invoiceNo, false))}>Remove check</button>}
                  </form>
                </div>
              </>
            )}
            {problem && <div className="error lines" role="alert">{problem}</div>}
          </div>
          <div className="dialog-buttons">
            {view && !w && view.rebuildable && (
              <button className="btn primary" disabled={busy}
                      onClick={() => void run(() => dailyApi.rebuildWorking(invoiceNo))}>
                {busy ? "Working it out…" : "Make the working"}</button>
            )}
            {w && <>
              <button className="btn" disabled={busy} onClick={() => void get("pdf")}>Download PDF</button>
              <button className="btn" disabled={busy} onClick={() => void get("xlsx")}>Download Excel</button>
            </>}
            <button type="button" className="btn" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workings of a day or a date range, as Excel (one row per invoice, one per
// item, check formulas beside the tool's amounts)
// ---------------------------------------------------------------------------
export function WorkingsExportDialog({ onClose, onExpired }: { onClose: () => void; onExpired: () => void }) {
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      await downloadFile(dailyApi.workingsExportUrl(from, to), `Workings_${from}_to_${to}.xlsx`);
      onClose();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="workings-title">
        <form onSubmit={save}>
          <h2 id="workings-title">Workings to Excel</h2>
          <div className="dialog-body">
            <p>Every posted invoice <strong>dated</strong> in the range, with its full working: sheet
              “Invoices” (one row per invoice, every figure in its own column, check formulas beside the
              tool's amounts) and sheet “Items” (one row per item, rate × qty as formulas).</p>
            <div className="form-grid top-gap">
              <label htmlFor="w-from">Invoice date from
                <input id="w-from" type="date" required value={from} max={today()}
                       onChange={(e) => setFrom(e.target.value)} /></label>
              <label htmlFor="w-to">to
                <input id="w-to" type="date" required value={to} min={from}
                       onChange={(e) => setTo(e.target.value)} /></label>
            </div>
            <p className="muted top-gap">At most three months at a time.</p>
            {problem && <div className="error lines" role="alert">{problem}</div>}
          </div>
          <div className="dialog-buttons">
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button className="btn primary" disabled={busy || !from || !to}>
              {busy ? "Preparing…" : "Download Excel"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

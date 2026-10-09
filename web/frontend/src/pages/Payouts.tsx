/*
 * Payouts.tsx - Every labour and incentive line, and marking it paid
 * ==================================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * The payout register: one line per amount to pay for an invoice -
 * Labour - Floor mat / Sunfilm / Other (no payee: the fitter is not
 * recorded), Spot incentive (to the sales executive), Internal team.
 *
 *   [ To pay ]  [ Paid today ]  [ On hold ]                       tiles
 *   Type | Status | Pay to | Search                               filters
 *   tick lines, then:
 *      Mark paid…      date, mode, reference and / or a proof (photo,
 *                      screenshot or PDF). One reference and one proof may
 *                      cover several lines - a person is often paid for
 *                      several invoices with one transfer.
 *      Hold…           keeps a line out of "to pay", with a reason
 *      Release         a held line is pending again
 *      Reopen…         undoes a recorded payment, with a reason. The line
 *                      is pending again and what it held stays in History.
 *      Cancel invoice… (lines of ONE invoice ticked) the invoice is not to
 *                      be paid: its unpaid lines are cancelled, paid ones
 *                      are left exactly as they are.
 *
 * THE RULES ARE THE SERVER'S (payout_app/service.py, word for word):
 *   * Paid needs a reference or a proof; the paid date cannot be in the future.
 *   * Only Pending or Hold lines can be paid. If one of the ticked lines
 *     was meanwhile paid or cancelled by someone else, NOTHING is recorded
 *     and the lines are named.
 *   * Only the payment details of a line are ever changed here - never its
 *     amount. The amount is what the scan calculated; hover over it to see
 *     the working.
 */
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, DailyTotals, PayoutLine, dailyApi, inr, showDate, today } from "../api";

type Ask = "pay" | "hold" | "reopen" | "cancel" | null;
const BADGE: Record<string, string> = { Pending: "badge amber", Paid: "badge green",
                                        Hold: "badge grey", Cancelled: "badge grey" };

export default function Payouts({ onExpired }: { onExpired: () => void }) {
  const [lines, setLines] = useState<PayoutLine[] | null>(null);
  const [totals, setTotals] = useState<DailyTotals | null>(null);
  const [modes, setModes] = useState<string[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [type, setType] = useState("");
  const [status, setStatus] = useState("Pending");
  const [payee, setPayee] = useState("");
  const [search, setSearch] = useState("");
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [ask, setAsk] = useState<Ask>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  const load = useCallback(async () => {
    try {
      const [reply, view] = await Promise.all([dailyApi.lines(), dailyApi.overview()]);
      setLines(reply.lines);
      setTotals(reply.totals);
      setModes(view.modes);
      setTypes(view.types);
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    void load();
  }, [load]);

  const payees = useMemo(() => [...new Set((lines ?? []).map((l) => l.payee).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b)), [lines]);

  const shown = useMemo(() => {
    const words = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return (lines ?? []).filter((l) => {
      if (status && l.status !== status) return false;
      if (type === "Labour (all)" ? !l.type.startsWith("Labour") : type && l.type !== type) return false;
      if (payee && l.payee !== payee) return false;
      const text = `${l.invoice_no} ${l.customer} ${l.car} ${l.payee} ${l.reference}`.toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [lines, status, type, payee, search]);

  const chosen = shown.filter((l) => ticked.has(l.line_id));
  const ids = chosen.map((l) => l.line_id);
  const sum = chosen.reduce((s, l) => s + l.amount, 0);
  const all = (wanted: string[]) => chosen.length > 0 && chosen.every((l) => wanted.includes(l.status));
  const oneInvoice = new Set(chosen.map((l) => l.invoice_no)).size === 1;
  const allTicked = shown.length > 0 && chosen.length === shown.length;

  const tick = (id: string) => {
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setTicked(next);
  };

  /** Run an action on the ticked lines, say what happened, read the register again. */
  const act = async (action: () => Promise<string>) => {
    setProblem("");
    setNotice("");
    try {
      setNotice(await action());
      setTicked(new Set());
      setAsk(null);
      setReason("");
    } catch (error) {
      fail(error);
    }
    await load();
  };
  const n = (count: number) => `${count} line${count === 1 ? "" : "s"}`;

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Payouts</h1>
          <p className="muted">Labour and incentive to pay. Tick the lines, then record the payment.</p>
        </div>
        <div className="row-actions">
          <a className="btn" href={dailyApi.slipUrl()} target="_blank" rel="noreferrer">Payout slip (to pay)</a>
          <a className="btn" href={dailyApi.exportUrl}>Export to Excel</a>
        </div>
      </div>

      {totals && (
        <div className="tiles">
          <div className="card tile amber"><div className="muted">To pay</div>
            <div className="tile-no">₹{inr(totals.pending.amount)}</div><div className="muted">{n(totals.pending.lines)}</div></div>
          <div className="card tile"><div className="muted">Paid today</div>
            <div className="tile-no">₹{inr(totals.paid_today.amount)}</div><div className="muted">{n(totals.paid_today.lines)}</div></div>
          <div className="card tile"><div className="muted">On hold</div>
            <div className="tile-no">₹{inr(totals.hold.amount)}</div><div className="muted">{n(totals.hold.lines)}</div></div>
        </div>
      )}

      <div className="card filters">
        <label>Type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            <option>Labour (all)</option>
            {types.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {["Pending", "Paid", "Hold", "Cancelled"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label>Pay to
          <select value={payee} onChange={(e) => setPayee(e.target.value)}>
            <option value="">Everyone</option>
            {payees.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label className="grow">Search
          <input type="search" value={search} placeholder="Invoice, customer, reference…"
                 onChange={(e) => setSearch(e.target.value)} />
        </label>
      </div>

      <div className="bulk">
        <span className="muted">{shown.length} shown
          {chosen.length > 0 && ` · ${n(chosen.length)} ticked · ₹${inr(sum)}`}</span>
        <div className="spacer" />
        {(ask === "hold" || ask === "reopen" || ask === "cancel") ? (
          <form className="inline" onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void act(async () => {
              if (ask === "hold") return `${n((await dailyApi.hold(ids, true, reason)).changed)} put on hold.`;
              if (ask === "reopen") return `${n((await dailyApi.reopen(ids, reason)).reopened)} reopened - pending again.`;
              const invoice = chosen[0].invoice_no;
              const left = (await dailyApi.cancel(invoice, reason)).paid_lines_left;
              return `Invoice ${invoice} cancelled.` + (left.length ? ` Already paid and left as they are: ${left.join(", ")}.` : "");
            });
          }}>
            <label htmlFor="why">{ask === "hold" ? "Reason for holding" : ask === "reopen" ? "Reason for reopening"
              : `Reason for cancelling invoice ${chosen[0]?.invoice_no}`}</label>
            <input id="why" className="wide-input" value={reason} autoFocus onChange={(e) => setReason(e.target.value)} />
            <button className={ask === "cancel" ? "btn danger" : "btn primary"} disabled={!reason.trim()}>
              {ask === "hold" ? "Hold" : ask === "reopen" ? "Reopen" : "Cancel invoice"}</button>
            <button type="button" className="btn" onClick={() => setAsk(null)}>Back</button>
          </form>
        ) : (
          <>
            <button className="btn primary" disabled={!all(["Pending", "Hold"])} onClick={() => setAsk("pay")}>Mark paid…</button>
            <button className="btn" disabled={!all(["Pending"])} onClick={() => { setAsk("hold"); setReason(""); }}>Hold…</button>
            <button className="btn" disabled={!all(["Hold"])} onClick={() => void act(async () =>
              `${n((await dailyApi.hold(ids, false, "")).changed)} released.`)}>Release</button>
            <button className="btn" disabled={!all(["Paid"])} onClick={() => { setAsk("reopen"); setReason(""); }}>Reopen…</button>
            <button className="btn" disabled={!chosen.length || !oneInvoice} onClick={() => { setAsk("cancel"); setReason(""); }}>Cancel invoice…</button>
          </>
        )}
      </div>

      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      <div className="card table-card">
        <div className="table-scroll tall">
          <table className="rows">
            <thead>
              <tr>
                <th><input type="checkbox" checked={allTicked} aria-label="Tick every line shown"
                           onChange={() => setTicked(allTicked ? new Set() : new Set(shown.map((l) => l.line_id)))} /></th>
                <th>Invoice</th><th>Date</th><th>Customer</th><th>Car</th><th>Type</th><th>Pay to</th>
                <th className="num">Amount (₹)</th><th>Status</th><th>Paid on</th><th>Mode</th><th>Reference</th>
                <th>Proof</th><th>Remarks</th>
              </tr>
            </thead>
            <tbody>
              {lines === null && <tr><td colSpan={14} className="muted">Reading…</td></tr>}
              {lines !== null && shown.length === 0 && <tr><td colSpan={14} className="muted">
                {lines.length === 0 ? "The register is empty. Scan invoices to post the first lines."
                  : "No line matches the filters."}</td></tr>}
              {shown.map((l) => (
                <tr key={l.line_id} className={l.status === "Cancelled" ? "inactive" : ""} onClick={() => tick(l.line_id)}>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={ticked.has(l.line_id)} onChange={() => tick(l.line_id)}
                           aria-label={`Tick ${l.line_id}`} /></td>
                  <td title={l.line_id}>{l.invoice_no}</td>
                  <td>{showDate(l.invoice_date)}</td>
                  <td>{l.customer}</td>
                  <td>{l.car}</td>
                  <td>{l.type}</td>
                  <td>{l.payee || "—"}</td>
                  <td className="num" title={l.working}>{inr(l.amount)}</td>
                  <td><span className={BADGE[l.status]}>{l.status}</span></td>
                  <td>{showDate(l.paid_date)}</td>
                  <td>{l.mode}</td>
                  <td>{l.reference}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {l.proof && <a href={dailyApi.proofUrl(l.proof)} target="_blank" rel="noreferrer">View</a>}</td>
                  <td>{l.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {ask === "pay" && (
        <PayDialog lines={chosen} modes={modes} onClose={() => setAsk(null)} onExpired={onExpired}
                   onPaid={(text) => void act(async () => text)} />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Recording a payment for the ticked lines
// ---------------------------------------------------------------------------
function PayDialog({ lines, modes, onClose, onPaid, onExpired }: {
    lines: PayoutLine[]; modes: string[]; onClose: () => void;
    onPaid: (text: string) => void; onExpired: () => void }) {
  const [paidDate, setPaidDate] = useState(today());
  const [mode, setMode] = useState(modes[0] ?? "Cash");
  const [reference, setReference] = useState("");
  const [remarks, setRemarks] = useState("");
  const [proof, setProof] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const total = lines.reduce((s, l) => s + l.amount, 0);
  const who = [...new Set(lines.map((l) => l.payee || l.type))];

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
      // The proof goes first and waits on the server; it gets its lasting
      // name only when the payment itself is recorded.
      const token = proof ? (await dailyApi.uploadProof(proof)).token : "";
      const done = await dailyApi.pay({ line_ids: lines.map((l) => l.line_id), paid_date: paidDate,
                                        mode, reference, remarks, proof_token: token });
      onPaid(`${done.paid} line${done.paid === 1 ? "" : "s"} marked paid · ₹${inr(done.amount)}`
        + (done.proof ? ` · proof saved as ${done.proof}` : ""));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="pay-title">
        <form onSubmit={save}>
          <h2 id="pay-title">Mark paid</h2>
          <div className="dialog-body">
            <div className="result">
              <div><strong>₹{inr(total)}</strong> · {lines.length} line{lines.length === 1 ? "" : "s"}</div>
              <div className="muted">{who.join(", ")}</div>
            </div>
            <div className="form-grid top-gap">
              <label htmlFor="paid-date">Paid on
                <input id="paid-date" type="date" required max={today()} value={paidDate}
                       onChange={(e) => setPaidDate(e.target.value)} /></label>
              <label htmlFor="paid-mode">Mode
                <select id="paid-mode" value={mode} onChange={(e) => setMode(e.target.value)}>
                  {modes.map((m) => <option key={m}>{m}</option>)}</select></label>
              <label htmlFor="paid-ref">Reference (UTR, voucher no…)
                <input id="paid-ref" value={reference} onChange={(e) => setReference(e.target.value)} /></label>
              <label htmlFor="paid-proof">Proof (photo, screenshot or PDF, up to 10 MB)
                <input id="paid-proof" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,.pdf"
                       onChange={(e) => setProof(e.target.files?.[0] ?? null)} /></label>
              <label htmlFor="paid-remarks" className="wide">Remarks
                <input id="paid-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} /></label>
            </div>
            <p className="muted top-gap">A payment needs a reference or a proof. One reference and one proof
              can cover all the ticked lines.</p>
            {problem && <div className="error lines" role="alert">{problem}</div>}
          </div>
          <div className="dialog-buttons">
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button className="btn primary" disabled={busy || (!reference.trim() && !proof)}>Mark paid</button>
          </div>
        </form>
      </div>
    </div>
  );
}

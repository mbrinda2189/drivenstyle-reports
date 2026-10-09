/*
 * MonthlyInputs.tsx - Figures that are not on the invoices
 * ========================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * Entered once per month, used by the Profit & loss and the "Indirect vs
 * direct cost %" reports:
 *
 *   INDIRECT COSTS       expense heads (Rent, Salaries, Electricity ...) and
 *                        the month's amount for each, with a running total.
 *                        A month with nothing saved starts with the usual
 *                        heads at zero. "Copy from <month>" fills in the
 *                        latest earlier month, since most heads repeat.
 *   HIGH-PROFIT THRESHOLD  products whose margin is at or above this % are
 *                        listed in the high-profit report (default 40 %).
 *   AUTOMATIC COSTS      Breakage / returns / transport (4 %) and Compliance
 *                        GST (3 %) are worked out by the tool on the month's
 *                        PRODUCT COST - do not type them as heads. The two
 *                        percentages are ONE setting for all months.
 *
 * Edits are held until "Save inputs" (the heading says "unsaved changes").
 * The server refuses a head entered twice or a negative amount, and writes
 * every saved change to the audit log (app/data/inputs_repo.py).
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, Inputs, inr, monthlyApi } from "../api";
import { MonthPicker, useMonth } from "../month";

type CostRow = { head: string; amount: string };

export default function MonthlyInputs({ onExpired }: { onExpired: () => void }) {
  const [month, setMonth] = useMonth();
  const [data, setData] = useState<Inputs | null>(null);
  const [rows, setRows] = useState<CostRow[]>([]);
  const [threshold, setThreshold] = useState("40");
  const [rates, setRates] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  const show = (reply: Inputs) => {
    setData(reply);
    // Nothing saved for the month yet: the usual heads, at zero.
    setRows(reply.saved ? reply.costs.map(([head, amount]) => ({ head, amount: String(amount) }))
      : reply.default_heads.map((head) => ({ head, amount: "0" })));
    setThreshold(String(reply.threshold));
    setRates(Object.fromEntries(reply.auto_rates.map((r) => [r.key, String(r.pct)])));
    setDirty(false);
  };

  useEffect(() => {
    setData(null);
    setNotice("");
    setProblem("");
    monthlyApi.inputs(month).then(show).catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]);

  const edit = (index: number, change: Partial<CostRow>) => {
    setRows(rows.map((r, i) => (i === index ? { ...r, ...change } : r)));
    setDirty(true);
  };
  const total = rows.reduce((sum, r) => sum + (Number(r.amount) || 0), 0);

  const save = async () => {
    setProblem("");
    setNotice("");
    try {
      const changed = data?.auto_rates.some((r) => Number(rates[r.key]) !== r.pct);
      if (changed) {
        await monthlyApi.saveRates(Object.fromEntries(
          Object.entries(rates).map(([key, value]) => [key, Number(value) || 0])));
      }
      show(await monthlyApi.saveInputs(month,
        rows.map((r) => [r.head, Number(r.amount) || 0] as [string, number]), Number(threshold) || 0));
      setNotice("Inputs saved.");
    } catch (error) {
      fail(error);
    }
  };

  const pickMonth = (next: string) => {
    if (!dirty || window.confirm("There are unsaved changes for this month. Leave without saving?")) {
      setMonth(next);
    }
  };

  if (!data) {
    return <><h1>Monthly inputs</h1>{problem ? <div className="error">{problem}</div>
      : <p className="muted">Reading…</p>}</>;
  }
  const before = data.previous;

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Monthly inputs {dirty && <span className="badge amber">Unsaved changes</span>}</h1>
          <p className="muted">Figures for {data.label} that are not on the invoices.
            {!data.saved && " Nothing has been saved for this month yet."}</p>
        </div>
        <MonthPicker month={month} onChange={pickMonth} />
      </div>
      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      <div className="two-col">
        <div className="card">
          <div className="card-head">
            <h2>Indirect costs</h2>
            {before.label && (
              <button className="btn" onClick={() => {
                setRows(before.costs.map(([head, amount]) => ({ head, amount: String(amount) })));
                setDirty(true);
              }}>Copy from {before.label}</button>
            )}
          </div>
          <table className="inputs">
            <thead><tr><th>Expense head</th><th className="num">Amount (₹)</th><th /></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td><input value={r.head} aria-label={`Expense head ${i + 1}`}
                             onChange={(e) => edit(i, { head: e.target.value })} /></td>
                  <td><input className="num" type="number" min="0" step="0.01" value={r.amount}
                             aria-label={`Amount for ${r.head || `row ${i + 1}`}`}
                             onChange={(e) => edit(i, { amount: e.target.value })} /></td>
                  <td><button className="btn" aria-label={`Remove ${r.head || `row ${i + 1}`}`} onClick={() => {
                    setRows(rows.filter((_, j) => j !== i));
                    setDirty(true);
                  }}>Remove</button></td>
                </tr>
              ))}
              <tr className="total"><td>Total</td><td className="num">{inr(total)}</td><td /></tr>
            </tbody>
          </table>
          <button className="btn" onClick={() => { setRows([...rows, { head: "", amount: "0" }]); setDirty(true); }}>
            Add expense head</button>
        </div>

        <div className="card">
          <h2>Report settings</h2>
          <label className="short">High-profit threshold (%)
            <input type="number" min="0" max="100" step="1" value={threshold}
                   onChange={(e) => { setThreshold(e.target.value); setDirty(true); }} />
          </label>
          <p className="muted">Products with a margin at or above this appear in the high-profit report.</p>

          <h3>Automatic indirect costs – all months</h3>
          <p className="muted">Worked out by the tool on the month's product cost. Do not also type them
            as expense heads. A change applies to every report generated afterwards, whichever month.</p>
          {data.auto_rates.map((r) => (
            <label className="short" key={r.key}>{r.head} (% of product cost)
              <input type="number" min="0" max="100" step="0.5" value={rates[r.key] ?? ""}
                     onChange={(e) => { setRates({ ...rates, [r.key]: e.target.value }); setDirty(true); }} />
            </label>
          ))}
        </div>
      </div>
      <div className="row-actions left">
        <button className="btn primary" disabled={!dirty && data.saved} onClick={() => void save()}>Save inputs</button>
      </div>
    </>
  );
}

/*
 * ZohoExpenses.tsx - Upload Zoho's Expense export on Monthly inputs (v0.32.0)
 * ==========================================================================
 *
 * WHAT THIS PART OF THE SCREEN DOES
 * ---------------------------------
 * Instead of typing every expense head, upload the month's Zoho Expense
 * export (.xlsx or .csv). The server adds the file up per Zoho ACCOUNT and
 * proposes a HEAD for each (web/backend/expenses_api.py,
 * app/data/expenses_io.py):
 *
 *   Account (Zoho)          Amount excl. GST   Head
 *   Rent Expense                 2,30,000.00   Rent
 *   Aravind                        35,000.00   Salaries
 *   Labour For Sunfilm Front       29,100.00   Labour - shown beside the tool's labour
 *   ...
 *
 * A head confirmed once is remembered for every later month ("remembered"
 * badge); only new accounts need a decision. Any head can be changed - type
 * a new name to make a new head. Two special choices:
 *   LABOUR    the tool works labour out from the Product master, so this
 *             amount is NOT an expense head; it is shown under the P&L beside
 *             the tool's labour ("Labour - tool vs Zoho").
 *   NOT USED  left out altogether.
 *
 * "Use these figures" REPLACES the month's expense heads with the totals per
 * head (excl. GST), remembers the matches and keeps the Zoho labour. The
 * high-profit threshold and the automatic % are not touched. Heads can still
 * be edited by hand afterwards in the table above.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ExpensePreview, inr, monthlyApi, showDateTime } from "../api";

const LABOUR_TEXT = "Labour – shown beside the tool's labour";
const NOT_USED_TEXT = "Not used";

export default function ZohoExpenses({ month, dirty, onApplied, onError }: {
  month: string;
  dirty: boolean;                                // unsaved typing in the table above
  onApplied: (message: string) => void;          // the screen reloads the month's inputs
  onError: (error: unknown) => void;
}) {
  const [preview, setPreview] = useState<ExpensePreview | null>(null);
  const [heads, setHeads] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const take = (reply: ExpensePreview) => {
    setPreview(reply);
    setHeads(Object.fromEntries((reply.accounts ?? []).map((a) => [a.account, a.head])));
  };

  useEffect(() => {
    setPreview(null);
    monthlyApi.expenses(month).then(take).catch(onError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]);

  const labour = preview?.labour ?? "(labour)";
  const notUsed = preview?.not_used ?? "(not used)";
  // On screen the two special choices read as words; they are sent as markers.
  const shown = (head: string) => head === labour ? LABOUR_TEXT : head === notUsed ? NOT_USED_TEXT : head;
  const stored = (text: string) => text === LABOUR_TEXT ? labour : text === NOT_USED_TEXT ? notUsed : text.trim();

  // Totals per head as they will be saved, and the labour kept for the P&L.
  const totals = useMemo(() => {
    const byHead = new Map<string, number>();
    let labourTotal = 0, unused = 0;
    for (const a of preview?.accounts ?? []) {
      const h = heads[a.account] ?? "";
      if (h === labour) labourTotal += a.amount;
      else if (h === notUsed || !h) unused += a.amount;
      else byHead.set(h, (byHead.get(h) ?? 0) + a.amount);
    }
    // largest first - the order they are saved in (expenses_api.apply)
    return { byHead: [...byHead.entries()].sort((x, y) => y[1] - x[1]), labourTotal, unused };
  }, [preview, heads, labour, notUsed]);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      take(await monthlyApi.uploadExpenses(month, file));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
      if (picker.current) picker.current.value = "";
    }
  };

  const apply = async () => {
    if (dirty && !window.confirm("The expense heads above have unsaved changes. Replace them with " +
                                 "the figures from the Zoho file?")) return;
    const missing = (preview?.accounts ?? []).filter((a) => !heads[a.account]);
    if (missing.length) {
      onError(new Error("Choose a head for: " + missing.map((a) => a.account).join(", ")));
      return;
    }
    setBusy(true);
    try {
      const reply = await monthlyApi.applyExpenses(month, heads);
      onApplied(`Zoho expenses used: ${reply.heads.length} heads, ₹ ${inr(reply.total)}` +
                (Object.keys(reply.labour).length ? "; labour as per Zoho kept for the P&L." : "."));
      take(await monthlyApi.expenses(month));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  };

  const choices = [...(preview?.heads ?? []), LABOUR_TEXT, NOT_USED_TEXT];
  const listId = `expense-heads-${month}`;

  return (
    <div className="card">
      <div className="card-head">
        <h2>Zoho expenses</h2>
        <button className="btn" disabled={busy} onClick={() => picker.current?.click()}>
          {preview?.file ? "Upload another file" : "Upload Zoho expenses"}</button>
        <input ref={picker} type="file" accept=".xlsx,.csv" hidden aria-label="Zoho expense file"
               onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
      </div>
      {!preview?.file ? (
        <p className="muted">Upload the month's Expense export from Zoho (.xlsx or .csv) to fill in the
          expense heads instead of typing them. Amounts are taken excluding GST.</p>
      ) : (
        <>
          <p className="muted">{preview.file.name} · uploaded {showDateTime(preview.file.at)} by {preview.file.by}
            {preview.other_months ? ` · ${preview.other_months} rows of other months left out` : ""}
            {preview.no_date ? ` · ${preview.no_date} rows without a date left out` : ""}</p>
          <p className="muted">Choose a head for each Zoho account. A choice is remembered for later
            months. Type a new name to make a new head.</p>
          <datalist id={listId}>{choices.map((c) => <option key={c} value={c} />)}</datalist>
          <table className="inputs">
            <thead><tr><th>Zoho account</th><th className="num">Amount excl. GST (₹)</th><th>Head</th></tr></thead>
            <tbody>
              {(preview.accounts ?? []).map((a) => (
                <tr key={a.account}>
                  <td>{a.account}{a.saved && <span className="badge grey" style={{ marginLeft: 6 }}>remembered</span>}</td>
                  <td className="num">{inr(a.amount)}</td>
                  <td><input list={listId} value={shown(heads[a.account] ?? "")}
                             aria-label={`Head for ${a.account}`}
                             onChange={(e) => setHeads({ ...heads, [a.account]: stored(e.target.value) })} /></td>
                </tr>
              ))}
              <tr className="total"><td>Total in the file</td><td className="num">{inr(preview.total ?? 0)}</td><td /></tr>
            </tbody>
          </table>

          <h3>What will be saved</h3>
          <table className="inputs">
            <tbody>
              {totals.byHead.map(([h, amount]) => (
                <tr key={h}><td>{h}</td><td className="num">{inr(amount)}</td></tr>
              ))}
              <tr className="total"><td>Expense heads</td>
                <td className="num">{inr(totals.byHead.reduce((s, [, v]) => s + v, 0))}</td></tr>
              {totals.labourTotal > 0 && <tr><td>Labour as per Zoho (shown beside the tool's labour, not a head)</td>
                <td className="num">{inr(totals.labourTotal)}</td></tr>}
              {totals.unused > 0 && <tr><td>Not used</td><td className="num">{inr(totals.unused)}</td></tr>}
            </tbody>
          </table>
          <div className="row-actions left">
            <button className="btn primary" disabled={busy} onClick={() => void apply()}>
              Use these figures for the month</button>
          </div>
          <p className="muted">This replaces the month's expense heads above. The high-profit threshold
            and the automatic percentages are not changed.</p>
        </>
      )}
    </div>
  );
}

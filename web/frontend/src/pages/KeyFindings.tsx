/*
 * KeyFindings.tsx - Why the month's figures moved (v0.36.0; tables v0.36.1)
 * ========================================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * Shows the key findings the tool has drafted for the chosen month - the
 * same list that opens the two PDFs and the Excel "Key findings" sheet - and
 * lets an ADMIN (this whole tab is admin only) adjust the WORDS before the
 * reports are made. The figures can never be changed.
 *
 * LAYOUT (v0.36.1, approved by Brinda 16-11-2026)
 * -----------------------------------------------
 *   [ Management | Internal team ]      two tabs, one per report
 *   one TABLE per section (Profit bridge, Sales, ...) with the columns
 *       Particulars | This month | <previous month> | Change | Change % |
 *       Avg <months> | Change | Change % | Leave out
 *   (the average columns only when there are two or more earlier months);
 *   under each row, in small grey text, the SENTENCE that prints in the
 *   report - always visible. ✎ opens it for editing; an edited row shows
 *   "Edited" and "Use the tool's sentence".
 *   "Leave out" ticks a finding out of the report: the row is greyed.
 *   Remarks (your own lines) at the end of each tab.
 *   A SAVE BAR fixed at the bottom of the screen: "3 unsaved changes –
 *   Save" when something on the tab was changed, "No changes to save"
 *   otherwise. (v0.36.0's pale Save button gave no reason why it could not
 *   be pressed: nothing had been changed.)
 *
 * The % columns are left blank when a % would mislead - the earlier figure
 * is a loss, nil, or below the threshold - the same rule as the sentences,
 * Excel and PDF (app/reports/findings.py, pct_change).
 *
 * COMPARISONS (worked out on the server): the previous month read into the
 * tool, and the average of up to three months before this one. A finding is
 * listed when its change is worth at least "Smallest change listed" against
 * either - ONE setting for all months.
 *
 * Saved changes are used the next time the reports are made: Generate
 * reports, or History > Regenerate / Make PDF. Each Save writes its changes
 * to the audit log.
 */
import { Fragment, useCallback, useEffect, useState } from "react";
import { ApiError, Finding, FindingsPart, Findings, inr, monthlyApi } from "../api";
import { MonthPicker, useMonth } from "../month";

/** What the admin is changing in one report, before "Save". */
type Draft = {
  texts: Record<string, string>;      // key -> sentence typed (missing = the tool's)
  hidden: Record<string, boolean>;
  remarks: string[];
};

function draftOf(part: FindingsPart): Draft {
  return {
    texts: Object.fromEntries(part.rows.filter((r) => r.edited).map((r) => [r.key, r.text])),
    hidden: Object.fromEntries(part.rows.map((r) => [r.key, r.hidden])),
    remarks: [...part.remarks],
  };
}

/** How many things differ between the saved state and the draft. */
function changes(part: FindingsPart, d: Draft): number {
  let n = 0;
  for (const r of part.rows) {
    const typed = (d.texts[r.key] ?? r.draft).trim();
    const savedText = r.edited ? r.text : r.draft;
    if (typed !== savedText) n += 1;
    if (!!d.hidden[r.key] !== r.hidden) n += 1;
  }
  const a = d.remarks.filter((t) => t.trim());
  if (a.length !== part.remarks.length || a.some((t, i) => t.trim() !== part.remarks[i])) n += 1;
  return n;
}

/** A figure as the reports show it. */
function figure(kind: Finding["kind"], value: number | null, change = false): string {
  if (value === null || value === undefined) return "";
  if (kind === "pct") {
    return change ? `${value >= 0 ? "+" : "−"}${Math.abs(value * 100).toFixed(1)} pts`
      : `${(value * 100).toFixed(1)}%`;
  }
  if (kind === "count") {
    const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
    return change && value > 0 ? `+${text}` : text.replace("-", "−");
  }
  const text = inr(Math.abs(value));
  if (value < 0) return `−${text}`;
  return change && value > 0 ? `+${text}` : text;
}

function percent(value: number | null): string {
  if (value === null || value === undefined) return "";
  return `${value >= 0 ? "+" : "−"}${Math.abs(value * 100).toFixed(1)}%`;
}

export default function KeyFindings({ onExpired }: { onExpired: () => void }) {
  const [month, setMonth] = useMonth();
  const [data, setData] = useState<Findings | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [tab, setTab] = useState<"management" | "internal">("management");
  const [editing, setEditing] = useState<string | null>(null);   // key of the row being edited
  const [threshold, setThreshold] = useState("");
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  const show = (reply: Findings) => {
    setData(reply);
    setDrafts(Object.fromEntries(reply.parts.map((p) => [p.part, draftOf(p)])));
    setThreshold(String(reply.threshold));
    setEditing(null);
  };

  const load = useCallback(() => {
    setData(null);
    setProblem("");
    monthlyApi.findings(month).then(show).catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]);

  useEffect(() => {
    setNotice("");
    load();
  }, [load]);

  const pending = (p: FindingsPart) => (drafts[p.part] ? changes(p, drafts[p.part]) : 0);
  const anyPending = !!data && data.parts.some((p) => pending(p) > 0);
  const change = (part: string, update: (d: Draft) => Draft) => {
    setNotice("");
    setDrafts({ ...drafts, [part]: update(drafts[part]) });
  };

  const save = async (part: FindingsPart) => {
    const d = drafts[part.part];
    setBusy(true);
    setProblem("");
    setNotice("");
    try {
      // Only what differs from the tool is sent: a sentence typed back to
      // the draft counts as "the tool's sentence".
      const edits = part.rows.map((r) => {
        const typed = (d.texts[r.key] ?? "").trim();
        return { key: r.key, text: typed && typed !== r.draft ? typed : "", hidden: !!d.hidden[r.key] };
      }).filter((e) => e.text || e.hidden);
      show(await monthlyApi.saveFindings(month, part.part, edits, d.remarks.filter((t) => t.trim())));
      setNotice(`${part.title}: saved. Generate the reports again (or History > Make PDF) to `
        + "see the changes in the PDF.");
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const saveThreshold = async () => {
    const amount = Number(threshold);
    if (!Number.isFinite(amount) || amount < 0) {
      setProblem("Type an amount of 0 or more.");
      return;
    }
    if (anyPending && !window.confirm("Unsaved changes to the findings will be lost. Go on?")) return;
    setBusy(true);
    setProblem("");
    try {
      await monthlyApi.saveFindingsThreshold(amount);
      setNotice(`Smallest change listed is now ₹${inr(amount)} (all months).`);
      load();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const pickMonth = (next: string) => {
    if (!anyPending || window.confirm("There are unsaved changes. Leave without saving?")) setMonth(next);
  };

  const heading = (
    <div className="title-row">
      <div>
        <h1>Key findings</h1>
        <p className="muted">Why the figures moved – the first page of both PDFs and the Excel
          “Key findings” sheet.</p>
      </div>
      <MonthPicker month={month} onChange={pickMonth} />
    </div>
  );

  if (!data) {
    return <>{heading}{problem ? <div className="error lines" role="alert">{problem}</div>
      : <p className="muted">Working out the findings…</p>}</>;
  }

  const part = data.parts.find((p) => p.part === tab) ?? data.parts[0];
  const d = part ? drafts[part.part] : undefined;
  const n = part ? pending(part) : 0;
  const avg = !!data.avg_label;
  const avgHead = avg ? `Avg ${data.avg_label.replace(/ \d{4}$/, "")}` : "";
  const columns = avg ? 9 : 6;

  // the rows of the tab, section by section
  const sections: { name: string; rows: Finding[] }[] = [];
  for (const r of part?.rows ?? []) {
    const last = sections[sections.length - 1];
    if (last && last.name === r.section) last.rows.push(r);
    else sections.push({ name: r.section, rows: [r] });
  }

  return (
    <div className="findings-page">
      {heading}
      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      <div className="card">
        <div className="findings-settings">
          <div>
            {data.comparable ? (
              <p>{data.label} compared with <strong>{data.prev_label}</strong>
                {avg ? <> and with the <strong>average of {data.avg_label}</strong> ({data.avg_months} months).</>
                  : ". An average needs two or more earlier months."}</p>
            ) : (
              <p>No month before {data.label} has been read into the tool, so there is nothing to
                compare with yet. The reports will have no key findings page.</p>
            )}
            <p className="muted">% change is left blank when the earlier figure is a loss, nil or
              below the smallest change listed – a % of those would mislead.</p>
          </div>
          <label className="short">Smallest change listed (₹, all months)
            <span className="inline">
              <input type="number" min="0" step="100" value={threshold}
                     onChange={(e) => setThreshold(e.target.value)} />
              <button className="btn" disabled={busy || Number(threshold) === data.threshold}
                      onClick={() => void saveThreshold()}>Apply</button>
            </span>
          </label>
        </div>
      </div>

      {data.comparable && part && d && (
        <>
          <div className="report-tabs" role="tablist">
            {data.parts.map((p) => (
              <button key={p.part} role="tab" aria-selected={p.part === part.part}
                      className={`report-tab${p.part === part.part ? " on" : ""}`}
                      onClick={() => { setTab(p.part); setEditing(null); }}>
                {p.part === "management" ? "Management" : "Internal team"}
                <span className="count">{p.rows.length}</span>
                {pending(p) > 0 && <span className="badge amber">Unsaved</span>}
              </button>
            ))}
          </div>

          <div className="card findings">
            <p className="muted">{part.rows.length} finding{part.rows.length === 1 ? "" : "s"} of
              ₹{inr(data.threshold)} or more; {part.smaller} smaller comparison{part.smaller === 1 ? " is" : "s are"} in
              the Excel “Drivers” sheet only. Amounts in ₹.</p>
            {part.rows.length === 0 && <p className="muted">No change of ₹{inr(data.threshold)} or more.</p>}

            {sections.map((s) => (
              <Fragment key={s.name}>
                <h3 className="findings-section">{s.name}</h3>
                <div className="table-scroll">
                  <table className="findings-table">
                    <thead>
                      <tr>
                        <th>Particulars</th>
                        <th className="num">This month</th>
                        <th className="num">{data.prev_label}</th>
                        <th className="num">Change</th>
                        <th className="num">Change %</th>
                        {avg && <><th className="num">{avgHead}</th><th className="num">Change</th>
                          <th className="num">Change %</th></>}
                        <th className="center">Leave out</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.rows.map((r) => {
                        const hidden = !!d.hidden[r.key];
                        const text = d.texts[r.key] ?? r.draft;
                        const edited = text.trim() !== r.draft;
                        const open = editing === r.key;
                        return (
                          <Fragment key={r.key}>
                            <tr className={`figures${hidden ? " left-out" : ""}${r.headline ? " headline" : ""}`}>
                              <td>{r.label}</td>
                              <td className="num">{figure(r.kind, r.now)}</td>
                              <td className="num">{figure(r.kind, r.prev)}</td>
                              <td className="num">{figure(r.kind, r.change_prev, true)}</td>
                              <td className="num">{percent(r.pct_prev)}</td>
                              {avg && <>
                                <td className="num">{figure(r.kind, r.avg)}</td>
                                <td className="num">{figure(r.kind, r.change_avg, true)}</td>
                                <td className="num">{percent(r.pct_avg)}</td>
                              </>}
                              <td className="center">
                                <input type="checkbox" checked={hidden} aria-label={`Leave out ${r.label}`}
                                       onChange={(e) => change(part.part, (x) => ({ ...x, hidden: { ...x.hidden, [r.key]: e.target.checked } }))} />
                              </td>
                            </tr>
                            <tr className={`sentence${hidden ? " left-out" : ""}`}>
                              <td colSpan={columns}>
                                {open ? (
                                  <div className="sentence-edit">
                                    <textarea rows={2} value={text} autoFocus aria-label={`Sentence for ${r.label}`}
                                              onChange={(e) => change(part.part, (x) => ({ ...x, texts: { ...x.texts, [r.key]: e.target.value } }))} />
                                    <button className="btn" onClick={() => setEditing(null)}>Done</button>
                                  </div>
                                ) : (
                                  <div className="sentence-line">
                                    <span className="text">{text}</span>
                                    <button className="icon-btn" title="Edit the sentence" aria-label={`Edit the sentence for ${r.label}`}
                                            disabled={hidden} onClick={() => setEditing(r.key)}>✎</button>
                                    {edited && <span className="badge blue plain">Edited</span>}
                                    {edited && <button className="link-btn" onClick={() => change(part.part, (x) => {
                                      const texts = { ...x.texts };
                                      texts[r.key] = r.draft;
                                      return { ...x, texts };
                                    })}>Use the tool's sentence</button>}
                                  </div>
                                )}
                              </td>
                            </tr>
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Fragment>
            ))}

            <h3 className="findings-section">Remarks</h3>
            <p className="muted">Your own lines, printed at the end of the findings.</p>
            {d.remarks.map((t, i) => (
              <div className="remark" key={i}>
                <textarea rows={2} value={t} aria-label={`Remark ${i + 1}`}
                          onChange={(e) => change(part.part, (x) => ({ ...x, remarks: x.remarks.map((v, j) => (j === i ? e.target.value : v)) }))} />
                <button className="btn" onClick={() => change(part.part, (x) => ({ ...x, remarks: x.remarks.filter((_, j) => j !== i) }))}>
                  Remove</button>
              </div>
            ))}
            <button className="btn" onClick={() => change(part.part, (x) => ({ ...x, remarks: [...x.remarks, ""] }))}>
              Add remark</button>
          </div>

          <div className={`save-bar${n ? " pending" : ""}`} role="region" aria-label="Save">
            <span>{n ? `${part.title}: ${n} unsaved change${n === 1 ? "" : "s"}`
              : `${part.title}: no changes to save – the report uses the sentences shown.`}</span>
            {n > 0 && <button className="btn" disabled={busy}
                              onClick={() => { setDrafts({ ...drafts, [part.part]: draftOf(part) }); setEditing(null); }}>
              Undo changes</button>}
            <button className="btn primary" disabled={busy || !n} onClick={() => void save(part)}>
              {busy ? "Saving…" : "Save"}</button>
          </div>
        </>
      )}
    </div>
  );
}

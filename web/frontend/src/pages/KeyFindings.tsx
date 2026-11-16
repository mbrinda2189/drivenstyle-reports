/*
 * KeyFindings.tsx - Why the month's figures moved (v0.36.0)
 * =========================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * Shows the key findings the tool has drafted for the chosen month - the
 * same list that opens the two PDFs and the Excel "Key findings" sheet - and
 * lets an ADMIN (this whole tab is admin only) adjust the WORDS before the
 * reports are made:
 *
 *   * change the sentence of a finding (the figures cannot be changed);
 *   * "Leave out" a finding - it stays on this screen, greyed, and in the
 *     Excel "Drivers" sheet, but not in the PDF or the "Key findings" sheet;
 *   * "Use the tool's sentence" - undo an edit;
 *   * add remarks of your own; they print at the end, under "Remarks".
 *
 * Each report (Management / Internal team) is saved on its own with its
 * "Save" button; every change is written to the audit log.
 *
 * COMPARISONS (worked out on the server, app/reports/findings.py):
 *   the previous month read into the tool, and the average of up to three
 *   months before this one. A finding is listed when its change is worth at
 *   least the amount in "Smallest change listed" against either. That amount
 *   is ONE setting for all months (default Rs. 1,000).
 *
 * The edits are used the next time the reports are made: Generate reports,
 * or History > Regenerate / Make PDF.
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, Finding, FindingsPart, Findings, inr, monthlyApi } from "../api";
import { MonthPicker, useMonth } from "../month";

/** What the admin is changing in one report, before "Save". */
type Draft = {
  texts: Record<string, string>;      // key -> sentence typed (missing = unchanged)
  hidden: Record<string, boolean>;
  remarks: string[];
  dirty: boolean;
};

function draftOf(part: FindingsPart): Draft {
  return {
    texts: Object.fromEntries(part.rows.filter((r) => r.edited).map((r) => [r.key, r.text])),
    hidden: Object.fromEntries(part.rows.map((r) => [r.key, r.hidden])),
    remarks: [...part.remarks],
    dirty: false,
  };
}

/** A figure as the reports show it. */
function figure(kind: Finding["kind"], value: number | null, change = false): string {
  if (value === null || value === undefined) return "–";
  if (kind === "pct") {
    return change ? `${value >= 0 ? "+" : "−"}${Math.abs(value * 100).toFixed(1)} pts`
      : `${(value * 100).toFixed(1)}%`;
  }
  if (kind === "count") {
    const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
    return change && value > 0 ? `+${text}` : text;
  }
  const text = `₹${inr(Math.abs(value))}`;
  if (value < 0) return `−${text}`;
  return change && value > 0 ? `+${text}` : text;
}

export default function KeyFindings({ onExpired }: { onExpired: () => void }) {
  const [month, setMonth] = useMonth();
  const [data, setData] = useState<Findings | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
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

  const anyDirty = Object.values(drafts).some((d) => d.dirty);
  const change = (part: string, update: (d: Draft) => Draft) =>
    setDrafts({ ...drafts, [part]: { ...update(drafts[part]), dirty: true } });

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
    if (anyDirty && !window.confirm("Unsaved changes to the findings will be lost. Go on?")) return;
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
    if (!anyDirty || window.confirm("There are unsaved changes. Leave without saving?")) setMonth(next);
  };

  const heading = (
    <div className="title-row">
      <div>
        <h1>Key findings {anyDirty && <span className="badge amber">Unsaved changes</span>}</h1>
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

  return (
    <>
      {heading}
      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      <div className="card">
        <div className="findings-settings">
          <div>
            {data.comparable ? (
              <p>{data.label} compared with <strong>{data.prev_label}</strong>
                {data.avg_label && <> and with the <strong>average of {data.avg_label}</strong> ({data.avg_months} months)</>}.
                {!data.avg_label && " An average needs two or more earlier months."}</p>
            ) : (
              <p>No month before {data.label} has been read into the tool, so there is nothing to
                compare with yet. The reports will have no key findings page.</p>
            )}
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

      {data.comparable && data.parts.map((part) => {
        const d = drafts[part.part];
        if (!d) return null;
        let section = "";
        return (
          <div className="card findings" key={part.part}>
            <div className="card-head">
              <h2>{part.title}</h2>
              <button className="btn primary" disabled={busy || !d.dirty}
                      onClick={() => void save(part)}>Save {part.title.toLowerCase()}</button>
            </div>
            <p className="muted">{part.rows.length} finding{part.rows.length === 1 ? "" : "s"} of
              ₹{inr(data.threshold)} or more; {part.smaller} smaller comparison{part.smaller === 1 ? "" : "s"} are
              in the Excel “Drivers” sheet only.</p>
            {part.rows.length === 0 && <p className="muted">No change of ₹{inr(data.threshold)} or more.</p>}
            {part.rows.map((r) => {
              const head = r.section !== section ? (section = r.section) : null;
              const hidden = !!d.hidden[r.key];
              const text = d.texts[r.key] ?? r.draft;
              const edited = text.trim() !== r.draft;
              return (
                <div key={r.key}>
                  {head && <h3 className="findings-section">{head}</h3>}
                  <div className={`finding${hidden ? " left-out" : ""}${r.headline ? " headline" : ""}`}>
                    <div className="finding-top">
                      <strong>{r.label}</strong>
                      <span className="finding-figures">
                        {r.kind !== "effect" && <span>This month {figure(r.kind, r.now)}</span>}
                        <span>vs {data.prev_label}: {figure(r.kind, r.change_prev, true)}</span>
                        {data.avg_label && <span>vs average: {figure(r.kind, r.change_avg, true)}</span>}
                      </span>
                    </div>
                    <textarea rows={2} value={text} disabled={hidden}
                              aria-label={`Sentence for ${r.label}`}
                              onChange={(e) => change(part.part, (x) => ({ ...x, texts: { ...x.texts, [r.key]: e.target.value } }))} />
                    <div className="row-actions left">
                      <label className="check">
                        <input type="checkbox" checked={hidden}
                               onChange={(e) => change(part.part, (x) => ({ ...x, hidden: { ...x.hidden, [r.key]: e.target.checked } }))} />
                        Leave out of the report
                      </label>
                      {edited && <button className="btn" onClick={() => change(part.part, (x) => {
                        const texts = { ...x.texts };
                        delete texts[r.key];
                        return { ...x, texts };
                      })}>Use the tool's sentence</button>}
                      {edited && <span className="badge blue plain">Edited</span>}
                    </div>
                  </div>
                </div>
              );
            })}

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
            <div className="row-actions left">
              <button className="btn" onClick={() => change(part.part, (x) => ({ ...x, remarks: [...x.remarks, ""] }))}>
                Add remark</button>
              <button className="btn primary" disabled={busy || !d.dirty}
                      onClick={() => void save(part)}>Save {part.title.toLowerCase()}</button>
            </div>
          </div>
        );
      })}
    </>
  );
}

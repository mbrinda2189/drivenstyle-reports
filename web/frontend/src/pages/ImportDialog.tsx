/*
 * ImportDialog.tsx - Import a master from an Excel or CSV sheet
 * =============================================================
 *
 * WHAT THIS WINDOW DOES
 * ---------------------
 * Opened by Masters > Import Excel once the file has been sent to the
 * server. Before anything is saved it shows how the sheet will be read:
 *
 *   +----------------------------------------------------------------+
 *   |  Import products                                               |
 *   |  items.xlsx · headings on row 3 · 42 rows                      |
 *   |  Sheet [Sheet1 v]                    (only if several sheets)  |
 *   |  Match the columns                                             |
 *   |    Product name *     [Item Name        v]                     |
 *   |    Selling price      [Rate             v]                     |
 *   |    Category           [Not in this sheet v]  From HSN/SAC...   |
 *   |  Preview (first 5 rows, as they will be saved)                 |
 *   |  Amounts apply from [01-10-2026]   (products and incentives)   |
 *   |  2 rows will be left out: Row 7: Selling price "abc"...        |
 *   |                                     [Cancel] [Import 40 rows]  |
 *   +----------------------------------------------------------------+
 *
 * The server does all the reading (the desktop tool's excel_io.py): each
 * time a column match or the sheet is changed, this window asks it again
 * and redraws the preview and the "left out" list from its answer.
 *
 * AFTER THE IMPORT the same window shows what was done: added / updated /
 * unchanged, rows left out and notes.
 *
 * ZOHO'S ITEM LIST is recognised by the server; its columns are pre-set
 * and "Add items..." is fixed to Yes. Afterwards the products that are
 * NOT in Zoho's list are shown. Removing them is for ADMINS ONLY (Brinda,
 * 09-10-2026); staff see the list and a note. Whether the person may
 * remove is the SERVER's answer (`may_remove`), and the server keeps the
 * list itself, so only exactly those products can be removed.
 *
 * Cancel (or Esc) tells the server to delete the uploaded file.
 */
import { useEffect, useState } from "react";
import { ApiError, ImportResult, ImportState, MasterDef, Value, importApi, inr, showDate } from "../api";

const NOT_IN_SHEET = "";          // the "— Not in this sheet —" choice

interface Props {
  def: MasterDef;
  start: ImportState;             // the server's first reading of the file
  onClose: (changed: boolean) => void;
  onExpired: () => void;
}

const plural = (n: number, word = "row") => `${n} ${word}${n === 1 ? "" : "s"}`;

export default function ImportDialog({ def, start, onClose, onExpired }: Props) {
  const [state, setState] = useState(start);
  const [from, setFrom] = useState(start.default_date ?? "");
  const [addNew, setAddNew] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [removed, setRemoved] = useState<string | null>(null);   // what was decided about Zoho's missing items

  const fail = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  };

  /** Ask the server to read the file again with another sheet or other matches. */
  const reread = async (sheet: string, mapping: Record<string, string | null> | null) => {
    setBusy(true);
    setProblem("");
    try {
      const next = await importApi.preview(def.key, state.token, sheet, mapping);
      setState(next);
      if (mapping === null && next.default_date) setFrom(next.default_date);   // another sheet
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    // Nothing was imported: the uploaded file is deleted on the server.
    void importApi.cancel(def.key, state.token).catch(() => undefined);
    onClose(false);
  };
  const close = () => (result ? onClose(true) : cancel());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const run = async () => {
    setBusy(true);
    setProblem("");
    try {
      setResult(await importApi.run(def.key, state.token, state.sheet, state.mapping,
                                    state.has_rates ? from : null, addNew || state.is_zoho));
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const removeMissing = async () => {
    setBusy(true);
    setProblem("");
    try {
      const done = await importApi.removeMissing(def.key, state.token);
      setRemoved(`${plural(done.removed, "product")} removed. Each removal is in the audit log.`);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const cell = (kind: string | undefined, value: Value | undefined) =>
    kind === "money" ? inr(Number(value || 0)) : kind === "bool" ? (value ? "Yes" : "No")
      : String(value ?? "");
  const kindOf = (key: string) => state.fields.find((f) => f.key === key)?.kind;
  const labelOf = (key: string) => state.fields.find((f) => f.key === key)?.label ?? key;

  // ---- after the import: what was done -----------------------------------------
  if (result) {
    const missing = result.not_in_zoho;
    return (
      <div className="overlay">
        <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
          <div className="dialog-col">
            <h2 id="import-title">Import complete</h2>
            <div className="dialog-body">
              <p>{def.title} imported from {result.file_name}.</p>
              <p><strong>{result.added} added, {result.updated} updated, {result.unchanged} unchanged.</strong>
                {result.rates_changed > 0 && result.effective_from &&
                  ` ${plural(result.rates_changed, def.singular)} got new amounts from ${showDate(result.effective_from)}.`}</p>

              {missing.length > 0 && (
                <div className="apply-from">
                  <strong>{plural(missing.length, "product")} in the tool {missing.length === 1 ? "is" : "are"} not in Zoho's item list</strong>
                  <ul className="names">
                    {missing.slice(0, 12).map((p) => <li key={p.id}>{p.name}</li>)}
                    {missing.length > 12 && <li>… and {missing.length - 12} more</li>}
                  </ul>
                  {removed ? <p><strong>{removed}</strong></p>
                    : result.may_remove ? (
                      <>
                        <p>Remove them from the Product master? Their labour and incentive
                          settings go with them. Each removal is kept in the audit log.</p>
                        <div className="row-actions left">
                          <button className="btn danger" disabled={busy} onClick={() => void removeMissing()}>Remove them</button>
                          <button className="btn" disabled={busy} onClick={() => setRemoved("They were kept.")}>Keep them</button>
                        </div>
                      </>
                    ) : <p>They were kept. Only an admin can remove them, by importing Zoho's list.</p>}
                </div>
              )}

              {result.skipped.length > 0 && (
                <>
                  <h3>{plural(result.skipped.length)} left out</h3>
                  <ul className="details">{result.skipped.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </>
              )}
              {result.warnings.length > 0 && (
                <>
                  <h3>Notes</h3>
                  <ul className="details">{result.warnings.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </>
              )}
              {problem && <div className="error lines" role="alert">{problem}</div>}
            </div>
            <div className="dialog-buttons">
              <button className="btn primary" onClick={() => onClose(true)}>Close</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ---- before the import: match the columns, look at the preview ----------------
  const blocked = state.missing.length > 0 || state.count === 0 || (state.has_rates && !from);
  return (
    <div className="overlay">
      <div className="dialog wide" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="dialog-col">
          <h2 id="import-title">Import {def.title.toLowerCase()}</h2>
          <div className="dialog-body">
            <p className="muted">{state.file_name} · headings found on row {state.header_row} · {plural(state.data_rows, "data row")}</p>

            {state.sheet_names.length > 1 && (
              <label className="short" htmlFor="import-sheet">Sheet
                <select id="import-sheet" value={state.sheet} disabled={busy}
                        onChange={(e) => void reread(e.target.value, null)}>
                  {state.sheet_names.map((n) => <option key={n}>{n}</option>)}
                </select>
              </label>
            )}
            {state.is_zoho && <div className="note blue">{state.zoho_note}</div>}

            <h3>Match the columns</h3>
            <div className="match-grid">
              {state.fields.map((f) => (
                <div className="match-row" key={f.key}>
                  <label htmlFor={`col-${f.key}`}>{f.label}{f.required && " *"}</label>
                  <select id={`col-${f.key}`} value={state.mapping[f.key] ?? NOT_IN_SHEET} disabled={busy}
                          onChange={(e) => void reread(state.sheet,
                            { ...state.mapping, [f.key]: e.target.value || null })}>
                    <option value={NOT_IN_SHEET}>— Not in this sheet —</option>
                    {state.headers.map((h) => <option key={h}>{h}</option>)}
                  </select>
                  <span className="muted hint">{f.hint}</span>
                </div>
              ))}
            </div>

            <h3>Preview (first {state.preview.length || 5} rows, as they will be saved)</h3>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>{state.preview_fields.map((k) => (
                    <th key={k} className={kindOf(k) === "money" ? "num" : ""}>{labelOf(k)}</th>))}</tr>
                </thead>
                <tbody>
                  {state.preview.length === 0 && (
                    <tr><td className="muted" colSpan={Math.max(1, state.preview_fields.length)}>
                      No row can be read with these column matches.</td></tr>
                  )}
                  {state.preview.map((row, i) => (
                    <tr key={i}>{state.preview_fields.map((k) => (
                      <td key={k} className={kindOf(k) === "money" ? "num" : ""}>{cell(kindOf(k), row[k])}</td>))}</tr>
                  ))}
                </tbody>
              </table>
            </div>

            {state.has_rates && (
              <div className="apply-from">
                <label htmlFor="import-from">Amounts apply from
                  <input id="import-from" type="date" required value={from}
                         onChange={(e) => setFrom(e.target.value)} />
                </label>
                <p className="muted">From {showDate(from)}. {def.title} already in the tool keep
                  their old amounts for earlier months.</p>
              </div>
            )}

            {def.key === "products" && (
              <label className="check" htmlFor="import-add-new"
                     title="Untick when the sheet only supplies labour / incentive for items already in the master: rows with a new name are then left out.">
                <input id="import-add-new" type="checkbox" checked={addNew || state.is_zoho}
                       disabled={!state.can_choose_add_new}
                       onChange={(e) => setAddNew(e.target.checked)} />
                Add items that are not in the Product master
              </label>
            )}

            {(state.missing.length > 0 || state.problems.length > 0) && (
              <div className="warn lines">
                {state.missing.length > 0 && `Choose the column for: ${state.missing.join(", ")}.\n`}
                {state.problems.length > 0 &&
                  `${plural(state.problems.length)} will be left out:\n${state.problems.slice(0, 3).join("\n")}`
                  + (state.problems.length > 3 ? `\n…and ${state.problems.length - 3} more.` : "")}
              </div>
            )}
            {problem && <div className="error lines" role="alert">{problem}</div>}
          </div>
          <div className="dialog-buttons">
            <button className="btn" onClick={cancel}>Cancel</button>
            <button className="btn primary" disabled={busy || blocked} onClick={() => void run()}>
              Import {plural(state.count)}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

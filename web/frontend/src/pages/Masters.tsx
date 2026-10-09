/*
 * Masters.tsx - Products, sales executives, cars, incentives, packages
 * ====================================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * One tab per master. In each tab: search, a filter (category / branch /
 * segment / package), active or inactive, and the rows.
 *
 *   Click a row          opens its edit form (EditDialog below)
 *   Add                  the same form, empty
 *   Tick rows            then Mark active / Mark inactive / Delete
 *   Delete all           every row of the tab - the word DELETE must be typed
 *   Import Excel         choose a sheet -> ImportDialog (match columns, preview)
 *   Export to Excel      the rows the search and filters show, as .xlsx
 *
 * WHERE THE RULES ARE
 *   Not here. The columns and the form are drawn from what the server
 *   says each master holds (app/data/master_defs.py), and every check - no
 *   duplicates, 10-digit contact number, an incentive group that exists -
 *   is made by the desktop tool's own masters_repo.py on the server. When
 *   it refuses, its sentences are shown in the form, one per line.
 *
 * AMOUNTS WITH A DATE
 *   Selling price, cost price, labour charge, incentive amount and bill
 *   value keep a history. When one of them is changed (or a row is added)
 *   the form asks "Amounts apply from": reports for earlier months keep
 *   the earlier amount. The form lists the history and lets a set entered
 *   with a wrong date be taken out (never the last one).
 *
 * WHY THE TABLE IS PLAIN
 *   The rows are plain text - no input box in every cell. With ~200
 *   products that keeps scrolling smooth (the desktop tool's v0.6.1
 *   lesson); the controls exist only for the row that was clicked.
 *
 * Staff may use this screen too (Brinda, 09-10-2026). Every change is in
 * the audit log with the e-mail of the person who made it.
 */
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, Field, ImportState, MasterDef, Rate, Row, Value, importApi, inr, mastersApi,
         showDate, today } from "../api";
import ImportDialog from "./ImportDialog";

type Status = "all" | "active" | "inactive";

/** A cell as text: amounts with Indian grouping, Yes / No, dd-mm-yyyy. */
function show(field: Field, value: Value | undefined): string {
  if (field.kind === "money") return inr(Number(value || 0));
  if (field.kind === "bool") return value ? "Yes" : "No";
  if (field.kind === "date") return showDate(value as string | null);
  return String(value ?? "");
}

export default function Masters({ onExpired }: { onExpired: () => void }) {
  const [defs, setDefs] = useState<MasterDef[] | null>(null);
  const [tab, setTab] = useState("products");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [lookups, setLookups] = useState<Record<string, string[]>>({});
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [status, setStatus] = useState<Status>("all");
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const [asking, setAsking] = useState<"delete" | "delete-all" | null>(null);
  const [word, setWord] = useState("");
  const [problem, setProblem] = useState("");
  const [notice, setNotice] = useState("");
  const [importing, setImporting] = useState<ImportState | null>(null);
  const [busy, setBusy] = useState("");                 // "Reading the file…" etc.
  const filePicker = useRef<HTMLInputElement>(null);

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  /** Read the tab's rows again, and the row counts shown on the tabs. */
  const refresh = useCallback(async (master: string) => {
    try {
      const [list, reply] = await Promise.all([mastersApi.list(), mastersApi.rows(master)]);
      setDefs(list);
      setRows(reply.rows);
      setLookups(reply.lookups);
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    setRows(null);
    setTicked(new Set());
    setSearch("");
    setFilter("");
    setStatus("all");
    setAsking(null);
    setProblem("");
    setNotice("");
    void refresh(tab);
  }, [tab, refresh]);

  const def = defs?.find((d) => d.key === tab);
  const columns = def?.fields ?? [];
  const filterField = def?.fields.find((f) => f.key === def.filter_field);

  /** The values offered in the filter drop-down: those actually in the rows. */
  const filterValues = useMemo(() => {
    if (!filterField || !rows) return [];
    return [...new Set(rows.map((r) => String(r[filterField.key] ?? "")).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
  }, [rows, filterField]);

  /** The rows the search and filters leave. */
  const shown = useMemo(() => {
    const words = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return (rows ?? []).filter((r) => {
      if (status !== "all" && Boolean(r.active) !== (status === "active")) return false;
      if (filter && filterField && String(r[filterField.key] ?? "") !== filter) return false;
      if (!words.length) return true;
      const text = columns.filter((f) => f.kind !== "bool" && f.kind !== "date")
        .map((f) => String(r[f.key] ?? "")).join(" ").toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [rows, search, filter, status, filterField, columns]);

  const tickedShown = shown.filter((r) => ticked.has(r.id)).map((r) => r.id);
  const allTicked = shown.length > 0 && tickedShown.length === shown.length;

  const tick = (id: number) => {
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setTicked(next);
  };
  const tickAll = () => setTicked(allTicked ? new Set() : new Set(shown.map((r) => r.id)));

  /** Run a bulk action, say what it did, and read the rows again. */
  const bulk = async (action: () => Promise<string>) => {
    setProblem("");
    setNotice("");
    try {
      setNotice(await action());
      setTicked(new Set());
      setAsking(null);
      setWord("");
      await refresh(tab);
    } catch (error) {
      fail(error);
    }
  };
  const rowsWord = (n: number) => `${n} row${n === 1 ? "" : "s"}`;

  /** A file was chosen: send it; the server answers with how it reads it. */
  const fileChosen = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";                // so the same file can be chosen again
    if (!file) return;
    setProblem("");
    setNotice("");
    setBusy("Reading the file…");
    try {
      setImporting(await importApi.upload(tab, file));
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
    }
  };

  const exportShown = async () => {
    setProblem("");
    setBusy("Making the Excel file…");
    try {
      await importApi.exportRows(tab, shown.map((r) => r.id));
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
    }
  };

  if (!defs || !def) {
    return <><h1>Masters</h1>{problem ? <div className="error">{problem}</div>
      : <p className="muted">Reading…</p>}</>;
  }

  return (
    <>
      <h1>Masters</h1>
      <p className="muted">Click a row to change it. Every change is recorded in the audit log.</p>

      <div className="subtabs" role="tablist">
        {defs.map((d) => (
          <button key={d.key} role="tab" aria-selected={d.key === tab}
                  className={d.key === tab ? "subtab on" : "subtab"} onClick={() => setTab(d.key)}>
            {d.title} <span className="count">{d.rows}</span>
          </button>
        ))}
      </div>

      <div className="card filters">
        <label className="grow">Search
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                 placeholder={`Search ${def.title.toLowerCase()}`} />
        </label>
        {filterField && (
          <label>{filterField.label}
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All</option>
              {filterValues.map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
        )}
        <label>Status
          <select value={status} onChange={(e) => setStatus(e.target.value as Status)}>
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <button className="btn primary" onClick={() => setEditing("new")}>Add {def.singular}</button>
        <button className="btn" disabled={Boolean(busy)} onClick={() => filePicker.current?.click()}>Import Excel</button>
        <button className="btn" disabled={Boolean(busy) || !shown.length} onClick={() => void exportShown()}>Export to Excel</button>
        <input ref={filePicker} type="file" accept=".xlsx,.csv" hidden onChange={fileChosen}
               aria-label={`Sheet to import into ${def.title}`} />
      </div>
      {busy && <div className="note" role="status">{busy}</div>}

      <div className="bulk">
        <span className="muted">{shown.length} of {rows?.length ?? 0} shown
          {tickedShown.length > 0 && ` · ${tickedShown.length} ticked`}</span>
        <div className="spacer" />
        {asking === "delete" ? (
          <>
            <span>Delete {rowsWord(tickedShown.length)}? This cannot be undone.</span>
            <button className="btn danger" onClick={() => void bulk(async () =>
              `${rowsWord((await mastersApi.remove(tab, tickedShown)).deleted)} deleted.`)}>Yes, delete</button>
            <button className="btn" onClick={() => setAsking(null)}>No</button>
          </>
        ) : asking === "delete-all" ? (
          <form className="inline" onSubmit={(e) => {
            e.preventDefault();
            void bulk(async () => `${rowsWord((await mastersApi.removeAll(tab, word)).deleted)} deleted.`);
          }}>
            <label htmlFor="delete-word">Type DELETE to delete all {rows?.length ?? 0} {def.title.toLowerCase()}</label>
            <input id="delete-word" value={word} onChange={(e) => setWord(e.target.value)} autoFocus />
            <button className="btn danger" disabled={word !== "DELETE"}>Delete all</button>
            <button type="button" className="btn" onClick={() => { setAsking(null); setWord(""); }}>Cancel</button>
          </form>
        ) : (
          <>
            <button className="btn" disabled={!tickedShown.length} onClick={() => void bulk(async () =>
              `${rowsWord((await mastersApi.setActive(tab, tickedShown, true)).changed)} marked active.`)}>Mark active</button>
            <button className="btn" disabled={!tickedShown.length} onClick={() => void bulk(async () =>
              `${rowsWord((await mastersApi.setActive(tab, tickedShown, false)).changed)} marked inactive.`)}>Mark inactive</button>
            <button className="btn" disabled={!tickedShown.length} onClick={() => setAsking("delete")}>Delete</button>
            <button className="btn" disabled={!rows?.length} onClick={() => setAsking("delete-all")}>Delete all…</button>
          </>
        )}
      </div>

      {problem && <div className="error" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      <div className="card table-card">
        <div className="table-scroll tall">
          <table className="rows">
            <thead>
              <tr>
                <th><input type="checkbox" checked={allTicked} onChange={tickAll}
                           aria-label="Tick every row shown" /></th>
                {columns.map((f) => <th key={f.key} className={f.kind === "money" ? "num" : ""}>{f.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows === null && <tr><td colSpan={columns.length + 1} className="muted">Reading…</td></tr>}
              {rows?.length === 0 && <tr><td colSpan={columns.length + 1} className="muted">
                Nothing here yet. Use “Add {def.singular}”.</td></tr>}
              {shown.map((r) => (
                <tr key={r.id} className={r.active ? "" : "inactive"} onClick={() => setEditing(r)}>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={ticked.has(r.id)} onChange={() => tick(r.id)}
                           aria-label={`Tick row ${r.id}`} />
                  </td>
                  {columns.map((f, i) => (
                    <td key={f.key} className={f.kind === "money" ? "num" : ""}>
                      {i === columns.findIndex((c) => c.required)
                        ? <button className="link" onClick={(e) => { e.stopPropagation(); setEditing(r); }}>
                            {show(f, r[f.key]) || "(blank)"}</button>
                        : show(f, r[f.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {importing && (
        <ImportDialog def={def} start={importing} onExpired={onExpired}
                      onClose={(changed) => {
                        setImporting(null);
                        if (changed) void refresh(tab);
                      }} />
      )}

      {editing && (
        <EditDialog def={def} row={editing === "new" ? null : editing} lookups={lookups}
                    onClose={() => setEditing(null)} onExpired={onExpired}
                    onSaved={(what) => {
                      setEditing(null);
                      setProblem("");
                      setNotice(what);
                      void refresh(tab);
                    }} />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// The edit form for one row
// ---------------------------------------------------------------------------
interface DialogProps {
  def: MasterDef;
  row: Row | null;                     // null = a new row
  lookups: Record<string, string[]>;
  onClose: () => void;
  onSaved: (what: string) => void;
  onExpired: () => void;
}

function EditDialog({ def, row, lookups, onClose, onSaved, onExpired }: DialogProps) {
  const fields = def.fields.filter((f) => f.kind !== "date");
  const start = useMemo(() => {
    const values: Record<string, Value> = {};
    fields.forEach((f) => { values[f.key] = row ? row[f.key] : f.default; });
    return values;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row, def.key]);
  const [values, setValues] = useState(start);
  const [from, setFrom] = useState(today());
  const [rates, setRates] = useState<Rate[]>([]);
  const [askRate, setAskRate] = useState("");        // the date asking "Remove?"
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const dated = fields.filter((f) => f.dated);
  /** Was an amount with a history changed? Then the form asks from which date. */
  const amountsChanged = dated.some((f) => Number(values[f.key] || 0) !== Number(start[f.key] || 0));
  const askDate = def.has_rates && (row === null || amountsChanged);

  const fail = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  };

  useEffect(() => {
    if (row && def.has_rates) mastersApi.rates(def.key, row.id).then(setRates).catch(() => undefined);
  }, [row, def]);

  // Esc closes the form, as in any window.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = (key: string, value: Value) => setValues({ ...values, [key]: value });

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      if (row) await mastersApi.change(def.key, row.id, values, askDate ? from : null);
      else await mastersApi.add(def.key, values, askDate ? from : null);
      onSaved(row ? "Saved." : `${def.singular[0].toUpperCase()}${def.singular.slice(1)} added.`);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  const removeRate = async (day: string) => {
    if (!row) return;
    setProblem("");
    try {
      setRates(await mastersApi.removeRate(def.key, row.id, day));
      setAskRate("");
    } catch (error) {
      fail(error);
    }
  };

  const input = (f: Field) => {
    const id = `f-${f.key}`;
    const value = values[f.key];
    if (f.kind === "bool") {
      return (
        <label key={f.key} className="check" htmlFor={id}>
          <input id={id} type="checkbox" checked={Boolean(value)}
                 onChange={(e) => set(f.key, e.target.checked)} /> {f.label}
        </label>
      );
    }
    let box;
    if (f.kind === "money") {
      box = <input id={id} type="number" min="0" step="0.01" value={String(value ?? 0)}
                   onChange={(e) => set(f.key, e.target.value === "" ? 0 : Number(e.target.value))} />;
    } else if (f.kind === "lookup") {
      // The other master's names; a name no longer active stays selectable for this row.
      const names = [...new Set([...(lookups[f.lookup] ?? []), String(value || "")].filter(Boolean))];
      box = (
        <select id={id} value={String(value ?? "")} onChange={(e) => set(f.key, e.target.value)}>
          <option value="">(none)</option>
          {names.map((n) => <option key={n}>{n}</option>)}
        </select>
      );
    } else if (f.kind === "choice" && !f.open_choice) {
      box = (
        <select id={id} value={String(value ?? "")} onChange={(e) => set(f.key, e.target.value)}>
          {f.choices.map((c) => <option key={c}>{c}</option>)}
        </select>
      );
    } else {
      // Free text; a "choice" that also takes new values offers its list as suggestions.
      box = (
        <>
          <input id={id} value={String(value ?? "")} required={f.required}
                 list={f.choices.length ? `${id}-list` : undefined}
                 onChange={(e) => set(f.key, e.target.value)} />
          {f.choices.length > 0 && (
            <datalist id={`${id}-list`}>{f.choices.map((c) => <option key={c} value={c} />)}</datalist>
          )}
        </>
      );
    }
    return (
      <label key={f.key} htmlFor={id} className={f.kind === "text" && f.required ? "wide" : ""}>
        {f.label}{f.required && " *"}{box}
      </label>
    );
  };

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <form onSubmit={save}>
          <h2 id="dialog-title">{row ? `Change ${def.singular}` : `Add ${def.singular}`}</h2>
          <div className="dialog-body">
            <div className="form-grid">
              {fields.filter((f) => f.kind !== "bool").map(input)}
            </div>
            <div className="checks">{fields.filter((f) => f.kind === "bool").map(input)}</div>

            {askDate && (
              <div className="apply-from">
                <label htmlFor="apply-from">Amounts apply from
                  <input id="apply-from" type="date" required value={from}
                         onChange={(e) => setFrom(e.target.value)} />
                </label>
                <p className="muted">From {showDate(from)}. Reports for dates before this keep the earlier amounts.</p>
              </div>
            )}

            {row && def.has_rates && rates.length > 0 && (
              <>
                <h3>Rate history</h3>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr><th>From</th>{dated.map((f) => <th key={f.key} className="num">{f.label}</th>)}<th /></tr>
                    </thead>
                    <tbody>
                      {rates.map((r) => {
                        const day = String(r.effective_from);
                        return (
                          <tr key={day}>
                            <td>{showDate(day)}</td>
                            {dated.map((f) => <td key={f.key} className="num">{inr(Number(r[f.key] || 0))}</td>)}
                            <td className="row-actions">
                              {askRate === day ? (
                                <>
                                  <span>Remove?</span>
                                  <button type="button" className="btn danger" onClick={() => void removeRate(day)}>Yes</button>
                                  <button type="button" className="btn" onClick={() => setAskRate("")}>No</button>
                                </>
                              ) : rates.length > 1 && (
                                <button type="button" className="btn" onClick={() => setAskRate(day)}>Remove this date</button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {problem && <div className="error lines" role="alert">{problem}</div>}
          </div>
          <div className="dialog-buttons">
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button className="btn primary" disabled={busy}>{row ? "Save" : "Add"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

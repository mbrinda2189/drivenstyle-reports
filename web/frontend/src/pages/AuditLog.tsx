/*
 * AuditLog.tsx - Who changed what, and when (admin only)
 * ======================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * Shows the audit log: one line for every change to a master, a dated
 * amount, a Scan review fix, a monthly input or the users list - with the
 * date and time, the e-mail of the person who made it, the old value and
 * the new value.
 *
 * It can only be READ. No screen, and no person, can alter or remove a
 * line: the database itself refuses (app/data/database.py). Entries
 * brought across from the desktop tool show the Windows user name of the
 * time instead of an e-mail address.
 *
 * FILTERS: master, action, a date range, and free text (searched in the
 * record, field, old and new value, user and source). The screen shows the
 * newest 1,000 lines the filters give; "Export to Excel" writes ALL of them.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, AuditEntry, AuditFilters, mastersApi, showDateTime } from "../api";

const ACTIONS = ["Added", "Edited", "Activated", "Deactivated", "Deleted", "Imported"];
const NONE: AuditFilters = { master: "", action: "", date_from: "", date_to: "", text: "" };

export default function AuditLog({ onExpired }: { onExpired: () => void }) {
  const [filters, setFilters] = useState<AuditFilters>(NONE);
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [masters, setMasters] = useState<{ key: string; title: string }[]>([]);
  const [more, setMore] = useState(false);
  const [limit, setLimit] = useState(0);
  const [problem, setProblem] = useState("");

  const read = useCallback(async (wanted: AuditFilters) => {
    setProblem("");
    try {
      const reply = await mastersApi.audit(wanted);
      setEntries(reply.entries);
      setMasters(reply.masters);
      setMore(reply.more);
      setLimit(reply.limit);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    }
  }, [onExpired]);

  useEffect(() => {
    void read(NONE);
  }, [read]);

  const set = (key: keyof AuditFilters, value: string) => setFilters({ ...filters, [key]: value });
  const apply = (event: FormEvent) => {
    event.preventDefault();
    void read(filters);
  };
  const title = (key: string) => masters.find((m) => m.key === key)?.title ?? key;

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">Every change, with who made it and when. This log can only be read.</p>

      <form className="card filters" onSubmit={apply}>
        <label>Master
          <select value={filters.master} onChange={(e) => set("master", e.target.value)}>
            <option value="">All</option>
            {masters.map((m) => <option key={m.key} value={m.key}>{m.title}</option>)}
          </select>
        </label>
        <label>Action
          <select value={filters.action} onChange={(e) => set("action", e.target.value)}>
            <option value="">All</option>
            {ACTIONS.map((a) => <option key={a}>{a}</option>)}
          </select>
        </label>
        <label>From
          <input type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} />
        </label>
        <label>To
          <input type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} />
        </label>
        <label className="grow">Search
          <input type="search" value={filters.text} placeholder="Name, value, e-mail…"
                 onChange={(e) => set("text", e.target.value)} />
        </label>
        <button className="btn primary">Show</button>
        <a className="btn" href={mastersApi.auditExportUrl(filters)}>Export to Excel</a>
      </form>

      {problem && <div className="error" role="alert">{problem}</div>}
      {more && <div className="note">Showing the newest {limit.toLocaleString("en-IN")} entries.
        Narrow the filters, or use Export to Excel for all of them.</div>}

      <div className="card table-card">
        <div className="table-scroll">
          <table className="wrap">
            <thead>
              <tr><th>Date and time</th><th>By</th><th>Master</th><th>Record</th><th>Action</th>
                  <th>Field</th><th>Old value</th><th>New value</th><th>Source</th></tr>
            </thead>
            <tbody>
              {entries === null && <tr><td colSpan={9} className="muted">Reading…</td></tr>}
              {entries?.length === 0 && <tr><td colSpan={9} className="muted">No entries.</td></tr>}
              {entries?.map((e) => (
                <tr key={e.id}>
                  <td className="nowrap">{showDateTime(e.at)}</td>
                  <td>{e.user}</td>
                  <td>{title(e.master)}</td>
                  <td>{e.record}</td>
                  <td>{e.action}</td>
                  <td>{e.field}</td>
                  <td>{e.old_value}</td>
                  <td>{e.new_value}</td>
                  <td>{e.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

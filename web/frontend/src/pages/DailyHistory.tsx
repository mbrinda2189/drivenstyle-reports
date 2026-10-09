/*
 * DailyHistory.tsx - Everything that happened in the payout register
 * ==================================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * The log of the daily payouts, newest first: every invoice posted, every
 * line corrected or cancelled, every payment recorded, reopened, held or
 * released - with the date and time, WHO did it, and the old and the new
 * value. A reopened payment shows here what it held before.
 *
 * It can only be read. These entries are part of the tool's audit log,
 * which the database itself protects from change (admins see the whole
 * log, masters included, on Admin > Audit log).
 *
 * SET-UP (admins only, at the foot of the page)
 *   Start date       invoices dated before it are left alone by the scan
 *                    ("no back-posting").
 *   Clear register   empties the register for a fresh start, e.g. after a
 *                    trial. A copy of the whole database is made first and
 *                    the word CLEAR must be typed. The log is kept.
 *
 * (The payout slip, the summary and the month check come in step 6.)
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, AuditEntry, dailyApi, showDate, showDateTime } from "../api";

export default function DailyHistory({ admin, onExpired }: { admin: boolean; onExpired: () => void }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [more, setMore] = useState(false);
  const [text, setText] = useState("");
  const [start, setStart] = useState("");
  const [word, setWord] = useState("");
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  const load = useCallback(async (search: string) => {
    try {
      const [reply, view] = await Promise.all([dailyApi.log(search), dailyApi.overview()]);
      setEntries(reply.entries);
      setMore(reply.more);
      setStart(view.start_date);
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    void load("");
  }, [load]);

  const act = async (action: () => Promise<string>) => {
    setProblem("");
    setNotice("");
    try {
      setNotice(await action());
      setWord("");
      await load(text);
    } catch (error) {
      fail(error);
    }
  };

  return (
    <>
      <h1>History</h1>
      <p className="muted">Every change in the payout register, with who made it. This log can only be read.</p>

      <form className="card filters" onSubmit={(e: FormEvent) => { e.preventDefault(); void load(text); }}>
        <label className="grow">Search
          <input type="search" value={text} placeholder="Invoice, line, name, reference…"
                 onChange={(e) => setText(e.target.value)} />
        </label>
        <button className="btn primary">Show</button>
      </form>
      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}
      {more && <div className="note">Showing the newest 500 entries. Search to narrow them down.</div>}

      <div className="card table-card">
        <div className="table-scroll tall">
          <table className="wrap">
            <thead><tr><th>Date and time</th><th>By</th><th>What</th><th>Invoice / line</th>
                       <th>Before</th><th>After</th></tr></thead>
            <tbody>
              {entries === null && <tr><td colSpan={6} className="muted">Reading…</td></tr>}
              {entries?.length === 0 && <tr><td colSpan={6} className="muted">Nothing has happened yet.</td></tr>}
              {entries?.map((e) => (
                <tr key={e.id}>
                  <td className="nowrap">{showDateTime(e.at)}</td>
                  <td>{e.user}</td>
                  <td>{e.field}</td>
                  <td>{e.record}</td>
                  <td>{e.old_value}</td>
                  <td>{e.new_value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {admin && (
        <div className="two-col">
          <form className="card" onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void act(async () => `Start date set to ${showDate((await dailyApi.setStartDate(start)).start_date)}.`);
          }}>
            <h2>Start date <span className="badge grey">Admin</span></h2>
            <p className="muted">Invoices dated before this are left alone by the scan.</p>
            <div className="fix">
              <input type="date" required value={start} aria-label="Start date" onChange={(e) => setStart(e.target.value)} />
              <button className="btn primary">Save</button>
            </div>
          </form>
          <form className="card" onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void act(async () => {
              const done = await dailyApi.clear(word);
              return `Register cleared: ${done.lines} lines and ${done.invoices} invoices removed. Backup kept as ${done.backup}.`;
            });
          }}>
            <h2>Clear the register <span className="badge grey">Admin</span></h2>
            <p className="muted">Removes every payout line and scanned invoice, for a fresh start. A backup
              of the database is made first; this log is kept. Type CLEAR to confirm.</p>
            <div className="fix">
              <input value={word} aria-label="Type CLEAR to confirm" placeholder="CLEAR" onChange={(e) => setWord(e.target.value)} />
              <button className="btn danger" disabled={word !== "CLEAR"}>Clear register</button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}

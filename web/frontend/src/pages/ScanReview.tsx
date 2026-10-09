/*
 * ScanReview.tsx - "Scan review": what the reading could not settle
 * =================================================================
 *
 * WHAT THIS SCREEN DOES
 * ---------------------
 * After a month's invoices are read, everything the tool could not settle
 * on its own is listed here, to be fixed BEFORE the reports are made.
 * Nothing is guessed silently: an invoice with an open issue is left out
 * of every report until it is fixed.
 *
 *     [ Invoices read ]  [ Need attention ]  [ Skipped ]       <- tiles
 *     Issues | Saved matches | Invoices read                   <- tabs
 *
 * ISSUES (open ones first). Click a row to get its Fix controls:
 *   Item not in the Product master   choose the product -> Save. Remembered
 *                                    for every invoice printing that name.
 *   Salesperson / vehicle not found  choose the executive / car, or "Others
 *                                    (not in master)" -> Save. A name is
 *                                    listed ONCE with all its invoices; the
 *                                    choice applies to all of them and is
 *                                    remembered for later months.
 *   ... matches several / not printed  one row per invoice; "All invoices"
 *                                    can be ticked when a name is printed.
 *   Totals do not add up             Accept, after checking in Zoho.
 *   Skipped (void, draft ...)        shown for information.
 * Each fix is saved at once and written to the audit log. One fix can
 * settle several rows; the list is read again after each.
 *
 * SAVED MATCHES: every choice made on the Issues tab, with what it was
 * matched to and how many of the month's invoices it touches. A wrong one
 * keeps sending sales to the wrong person or product in later months, so
 * it can be changed or removed here (the invoices then come back as issues
 * if they still do not match).
 *
 * INVOICES READ: every invoice of the month as the tool understood it;
 * amber where the salesperson or vehicle is not matched yet.
 *
 * As on the desktop, the Fix controls exist only for the clicked row - the
 * other rows are plain text, so a long list stays quick.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, Choice, InvoiceRead, Issue, SavedMatch, ScanSummary, inr, monthlyApi,
         showDate, showDateTime } from "../api";
import { Chooser, MonthPicker, monthLabel, useMonth } from "../month";

type Tab = "issues" | "matches" | "invoices";
type Lists = Record<"product" | "salesperson" | "car", Choice[]>;
const KIND: Record<string, string> = { product: "Item", salesperson: "Salesperson", car: "Vehicle",
                                       labour: "Labour", totals: "Totals", file: "Skipped" };

export default function ScanReview({ onExpired }: { onExpired: () => void }) {
  const [month, setMonth] = useMonth();
  const [tab, setTab] = useState<Tab>("issues");
  const [scan, setScan] = useState<ScanSummary | null>(null);
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [lists, setLists] = useState<Lists | null>(null);
  const [matches, setMatches] = useState<SavedMatch[] | null>(null);
  const [invoices, setInvoices] = useState<InvoiceRead[] | null>(null);
  const [open, setOpen] = useState("");                 // the clicked issue: kind|key
  const [pick, setPick] = useState<number | null>(null);
  const [every, setEvery] = useState(true);
  const [editing, setEditing] = useState("");            // saved match being changed / removed
  const [mode, setMode] = useState<"change" | "remove">("change");
  const [matchChoices, setMatchChoices] = useState<Choice[]>([]);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onExpired();
    else setProblem(error instanceof Error ? error.message : "Something went wrong.");
  }, [onExpired]);

  const load = useCallback(async (m: string, which: Tab) => {
    setProblem("");
    try {
      if (which === "issues") {
        const [reply, choices] = await Promise.all([monthlyApi.issues(m), monthlyApi.choices()]);
        setScan(reply.scan);
        setIssues(reply.issues);
        setLists(choices);
      } else if (which === "matches") {
        setMatches(await monthlyApi.matches(m));
      } else {
        setInvoices(await monthlyApi.invoices(m));
      }
    } catch (error) {
      fail(error);
    }
  }, [fail]);

  useEffect(() => {
    setOpen("");
    setEditing("");
    setNotice("");
    void load(month, tab);
    if (tab !== "issues") void monthlyApi.issues(month).then((r) => setScan(r.scan)).catch(() => undefined);
  }, [month, tab, load]);

  const id = (i: { kind: string; key: string }) => `${i.kind}|${i.key}`;
  const openIssues = (issues ?? []).filter((i) => i.status === "open");
  const others = (issues ?? []).filter((i) => i.status !== "open");

  const clickIssue = (issue: Issue) => {
    if (issue.status !== "open" || open === id(issue)) return;
    setOpen(id(issue));
    setPick(issue.options.length === 1 ? issue.options[0] : null);
    // An ambiguous name must be decided invoice by invoice (desktop rule).
    setEvery(issue.options.length <= 1);
  };

  const save = async (issue: Issue) => {
    setProblem("");
    try {
      const reply = await monthlyApi.fix(month, issue.kind, issue.key, pick, every);
      setIssues(reply.issues);
      setScan(reply.scan);
      setNotice(reply.done);
      setOpen("");
    } catch (error) {
      fail(error);
    }
  };

  const fixControls = (issue: Issue) => {
    if (issue.kind === "labour" || issue.kind === "totals") {
      return <button className="btn primary" onClick={(e) => { e.stopPropagation(); void save(issue); }}>
        Accept as it is</button>;
    }
    if (!lists || issue.kind === "file") return null;
    const what = issue.kind === "product" ? "product" : issue.kind === "salesperson" ? "executive" : "car";
    return (
      <div className="fix" onClick={(e) => e.stopPropagation()}>
        <Chooser choices={lists[issue.kind]} placeholder={`Type to find the ${what}…`}
                 label={`${what} for ${issue.printed || issue.key}`}
                 start={issue.options.length === 1 ? issue.options[0] : undefined} onPick={setPick} />
        {issue.kind !== "product" && !issue.grouped && issue.printed && (
          <label className="check small" title={`Use this for every invoice showing “${issue.printed}”, now and in later months.`}>
            <input type="checkbox" checked={every} onChange={(e) => setEvery(e.target.checked)} /> All invoices
          </label>
        )}
        <button className="btn primary" disabled={pick === null} onClick={() => void save(issue)}>Save</button>
      </div>
    );
  };

  const hint = (issue: Issue) => {
    if (issue.kind === "file") return "For information";
    if (issue.kind === "labour" || issue.kind === "totals") return "Click to check or accept";
    const what = issue.kind === "product" ? "product" : issue.kind === "salesperson" ? "executive" : "car";
    return `Click to choose the ${what}` +
      (issue.grouped && issue.invoices.length > 1 ? ` (all ${issue.invoices.length} invoices)` : "");
  };

  const startMatch = async (m: SavedMatch, what: "change" | "remove") => {
    setEditing(`${m.store}|${id(m)}`);
    setMode(what);
    setPick(null);
    if (what === "change") {
      try {
        setMatchChoices(await monthlyApi.matchChoices(m.kind));
      } catch (error) {
        fail(error);
      }
    }
  };

  const applyMatch = async (m: SavedMatch) => {
    setProblem("");
    try {
      setMatches(mode === "remove" ? await monthlyApi.removeMatch(month, m)
        : await monthlyApi.changeMatch(month, m, pick as number));
      setNotice(mode === "remove" ? "Saved match removed. Its invoices are matched again from the masters."
        : "Saved match changed.");
      setEditing("");
    } catch (error) {
      fail(error);
    }
  };

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Scan review</h1>
          <p className="muted">Fix what the reading could not settle before generating {monthLabel(month)}.</p>
        </div>
        <MonthPicker month={month} onChange={setMonth} />
      </div>

      {scan ? (
        <div className="tiles">
          <div className="card tile"><div className="muted">Invoices read</div><div className="tile-no">{scan.read}</div></div>
          <div className={scan.open_issues ? "card tile amber" : "card tile"}>
            <div className="muted">Need attention</div><div className="tile-no">{scan.open_issues}</div></div>
          <div className="card tile"><div className="muted">Skipped</div><div className="tile-no">{scan.skipped}</div></div>
        </div>
      ) : issues !== null && (
        <div className="note">{monthLabel(month)} has not been read yet. <Link to="/monthly/generate">Go to Generate reports</Link></div>
      )}

      <div className="subtabs" role="tablist">
        {([["issues", "Issues"], ["matches", "Saved matches"], ["invoices", "Invoices read"]] as [Tab, string][])
          .map(([key, title]) => (
            <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                    className={tab === key ? "subtab on" : "subtab"}>{title}</button>))}
        <div className="spacer" />
        {tab === "issues" && openIssues.length > 0 &&
          <a className="btn" href={monthlyApi.issuesExportUrl(month)}>Export issues</a>}
        {tab === "matches" && (matches?.length ?? 0) > 0 &&
          <a className="btn" href={monthlyApi.matchesExportUrl(month)}>Export matches</a>}
        <Link className="btn" to="/monthly/generate">Continue to generate</Link>
      </div>

      {problem && <div className="error lines" role="alert">{problem}</div>}
      {notice && <div className="note" role="status">{notice}</div>}

      {tab === "issues" && (
        <div className="card table-card">
          <div className="table-scroll tall">
            <table className="rows wrap">
              <thead><tr><th>Type</th><th>Issue</th><th>Invoices</th><th>Fix</th></tr></thead>
              <tbody>
                {issues === null && <tr><td colSpan={4} className="muted">Reading…</td></tr>}
                {issues?.length === 0 && <tr><td colSpan={4} className="muted">Nothing to review.</td></tr>}
                {[...openIssues, ...others].map((issue) => (
                  <tr key={id(issue)} className={issue.status === "open" ? "" : "inactive"}
                      onClick={() => clickIssue(issue)}>
                    <td className="nowrap"><span className={issue.status === "open" ? "badge amber" : "badge grey"}>
                      {issue.status === "open" ? KIND[issue.kind] : "Skipped"}</span></td>
                    <td>{issue.message}</td>
                    <td title={issue.invoices.join(", ")}>
                      {issue.invoices.length > 3
                        ? `${issue.invoices.slice(0, 3).join(", ")} +${issue.invoices.length - 3} more`
                        : issue.invoices.join(", ")}</td>
                    <td className="fix-cell">{open === id(issue) ? fixControls(issue)
                      : <span className="muted">{hint(issue)}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "matches" && (
        <div className="card table-card">
          <div className="table-scroll tall">
            <table className="wrap">
              <thead><tr><th>Type</th><th>As printed</th><th>Matched to</th><th>Applies to</th>
                         <th className="num">Invoices this month</th><th>Saved on</th><th /></tr></thead>
              <tbody>
                {matches === null && <tr><td colSpan={7} className="muted">Reading…</td></tr>}
                {matches?.length === 0 && <tr><td colSpan={7} className="muted">No saved matches yet.</td></tr>}
                {matches?.map((m) => {
                  const mine = editing === `${m.store}|${id(m)}`;
                  return (
                    <tr key={`${m.store}|${id(m)}`}>
                      <td className="nowrap">{m.type_label}</td>
                      <td>{m.printed}</td>
                      <td>{m.target}</td>
                      <td>{m.scope}</td>
                      <td className="num">{m.invoices}</td>
                      <td className="nowrap">{showDateTime(m.saved_on)}</td>
                      <td className="fix-cell">
                        {!mine ? (
                          <div className="row-actions">
                            {m.store !== "ack" && <button className="btn" onClick={() => void startMatch(m, "change")}>Change</button>}
                            <button className="btn" onClick={() => void startMatch(m, "remove")}>Remove</button>
                          </div>
                        ) : mode === "remove" ? (
                          <div className="row-actions">
                            <span>Remove?</span>
                            <button className="btn danger" onClick={() => void applyMatch(m)}>Yes</button>
                            <button className="btn" onClick={() => setEditing("")}>No</button>
                          </div>
                        ) : (
                          <div className="fix">
                            <Chooser key={matchChoices.length} choices={matchChoices} placeholder="Type to find…"
                                     label={`New match for ${m.printed}`} onPick={setPick} />
                            <button className="btn primary" disabled={pick === null} onClick={() => void applyMatch(m)}>Save</button>
                            <button className="btn" onClick={() => setEditing("")}>Cancel</button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "invoices" && (
        <div className="card table-card">
          <div className="table-scroll tall">
            <table>
              <thead><tr><th>Invoice</th><th>Date</th><th>Customer</th><th>Salesperson</th><th>Vehicle</th>
                         <th className="num">Items</th><th className="num">Total (₹)</th><th>GST</th><th>Payment</th></tr></thead>
              <tbody>
                {invoices === null && <tr><td colSpan={9} className="muted">Reading…</td></tr>}
                {invoices?.length === 0 && <tr><td colSpan={9} className="muted">No invoices read for this month.</td></tr>}
                {invoices?.map((inv) => (
                  <tr key={inv.invoice_no} title={inv.lines.map((l) =>
                      `${l.no}. ${l.description}  ₹${inr(l.amount)}` + (l.product ? `  → ${l.product}`
                        : l.marker ? "  (labour marker)" : "  (not matched)")).join("\n")}>
                    <td>{inv.invoice_no}</td>
                    <td>{showDate(inv.date)}</td>
                    <td>{inv.customer}</td>
                    <td className={inv.executive ? "" : "amber-text"}
                        title={inv.executive ? "" : "Not matched to the master yet - see Issues."}>
                      {inv.executive || `— ${inv.printed_executive || "not printed"}`}</td>
                    <td className={inv.car ? "" : "amber-text"}
                        title={inv.car ? "" : "Not matched to the master yet - see Issues."}>
                      {inv.car || `— ${inv.printed_car || "not printed"}`}</td>
                    <td className="num">{inv.items}</td>
                    <td className="num">{inr(inv.total)}</td>
                    <td>{inv.gst}</td>
                    <td>{inv.payment_mode || "Not printed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

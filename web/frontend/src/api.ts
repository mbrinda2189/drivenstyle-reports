/*
 * api.ts - Every conversation between the screens and the server
 * ==============================================================
 *
 * WHAT THIS FILE DOES
 * -------------------
 * The screens never read the database. They ask the Python server
 * (web/backend/main.py) through addresses starting with /api, and this
 * file is the only place that does the asking. A screen calls, say,
 * `api.users()` and gets the list - it does not need to know addresses.
 *
 * TWO RULES KEPT HERE
 *   1. Every request carries the header "X-DNS-Request". The server
 *      refuses a change without it, which stops another website from
 *      making a signed-in person's browser change something.
 *   2. When the server refuses, it sends a plain sentence ("This is the
 *      only active admin ..."). That sentence is raised as an ApiError so
 *      the screen can show it as it is.
 */

export type Role = "admin" | "staff";

/** One person on the sign-in list, as the server sends it. */
export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  active: boolean;
  created_at: string;
  last_login: string;
}

/** What the sign-in page needs before anyone is signed in. */
export interface Config {
  version: string;
  google_client_id: string;
  dev_login: boolean;
}

/** A refusal from the server: `status` 401 = not signed in, 403 = not allowed. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function ask<T>(method: string, path: string, body?: unknown): Promise<T> {
  let reply: Response;
  try {
    reply = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: { "X-DNS-Request": "1", ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "The server could not be reached. Check the connection and try again.");
  }
  const data = await reply.json().catch(() => null);
  if (!reply.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : "Something went wrong.";
    throw new ApiError(reply.status, detail);
  }
  return data as T;
}

export const api = {
  config: () => ask<Config>("GET", "/config"),
  me: () => ask<User>("GET", "/me"),
  signInGoogle: (credential: string) => ask<User>("POST", "/auth/google", { credential }),
  signInTest: (email: string) => ask<User>("POST", "/auth/dev", { email }),
  signOut: () => ask<{ ok: boolean }>("POST", "/auth/logout"),
  users: () => ask<User[]>("GET", "/users"),
  addUser: (email: string, name: string, role: Role) =>
    ask<User>("POST", "/users", { email, name, role }),
  changeUser: (id: number, change: Partial<Pick<User, "name" | "role" | "active">>) =>
    ask<User>("PATCH", `/users/${id}`, change),
  removeUser: (id: number) => ask<{ ok: boolean }>("DELETE", `/users/${id}`),
};

// ---- masters (v0.24.0) ----------------------------------------------------
/** One field (column) of a master, as app/data/master_defs.py describes it. */
export interface Field {
  key: string;
  label: string;
  kind: "text" | "money" | "bool" | "choice" | "lookup" | "date";
  required: boolean;
  choices: string[];
  open_choice: boolean;
  lookup: string;
  dated: boolean;      // keeps a history with "effective from" dates
  default: string | number | boolean;
}

export interface MasterDef {
  key: string;
  title: string;
  singular: string;
  filter_field: string;
  has_rates: boolean;
  fields: Field[];
  rows: number;
  active_rows: number;
}

export type Value = string | number | boolean | null;
/** One row of a master: field key -> value, plus its number in the database. */
export type Row = Record<string, Value> & { id: number };
export type Rate = Record<string, string | number>;

export interface AuditEntry {
  id: number;
  at: string;
  user: string;
  master: string;
  record: string;
  action: string;
  field: string;
  old_value: string;
  new_value: string;
  source: string;
}

export interface AuditFilters {
  master: string;
  action: string;
  date_from: string;
  date_to: string;
  text: string;
}

function query(filters: AuditFilters): string {
  const q = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => value && q.set(key, value));
  return q.toString();
}

// ---- import from / export to Excel (v0.25.0) ---------------------------------
/** Everything the import window shows (web/backend/imports_api.py, `state`). */
export interface ImportState {
  token: string;                       // the uploaded file's name on the server
  file_name: string;
  sheet: string;
  sheet_names: string[];
  header_row: number;
  data_rows: number;
  headers: string[];
  mapping: Record<string, string | null>;      // field -> column heading
  fields: { key: string; label: string; required: boolean; kind: string; hint: string }[];
  missing: string[];                   // required fields with no column yet
  preview_fields: string[];
  preview: Record<string, Value>[];    // first rows, as they will be saved
  count: number;                       // rows that will be imported
  problems: string[];                  // rows that will be left out, and why
  is_zoho: boolean;
  zoho_note: string;
  has_rates: boolean;
  default_date: string | null;
  can_choose_add_new: boolean;
}

export interface ImportResult {
  file_name: string;
  added: number;
  updated: number;
  unchanged: number;
  rates_changed: number;
  effective_from: string | null;
  skipped: string[];
  warnings: string[];
  not_in_zoho: { id: number; name: string }[];
  may_remove: boolean;                 // only admins may remove those products
}

/** Send a file as it is (not as JSON) - used for the sheet to import. */
async function sendFile<T>(path: string, file: File): Promise<T> {
  let reply: Response;
  try {
    reply = await fetch(`/api${path}?filename=${encodeURIComponent(file.name)}`, {
      method: "POST", credentials: "same-origin",
      headers: { "X-DNS-Request": "1", "Content-Type": "application/octet-stream" },
      body: file,
    });
  } catch {
    throw new ApiError(0, "The server could not be reached. Check the connection and try again.");
  }
  const data = await reply.json().catch(() => null);
  if (!reply.ok) {
    throw new ApiError(reply.status, data && typeof data.detail === "string"
      ? data.detail : "The file could not be read.");
  }
  return data as T;
}

/** Ask for a file and hand it to the browser as a download. */
async function download(path: string, body: unknown): Promise<void> {
  const reply = await fetch(`/api${path}`, {
    method: "POST", credentials: "same-origin",
    headers: { "X-DNS-Request": "1", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!reply.ok) {
    const data = await reply.json().catch(() => null);
    throw new ApiError(reply.status, data?.detail ?? "The file could not be made.");
  }
  const url = URL.createObjectURL(await reply.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = reply.headers.get("X-File-Name") ?? "export.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const importApi = {
  upload: (master: string, file: File) =>
    sendFile<ImportState>(`/masters/${master}/import/upload`, file),
  preview: (master: string, token: string, sheet: string, mapping: Record<string, string | null> | null) =>
    ask<ImportState>("POST", `/masters/${master}/import/${token}/preview`, { sheet, mapping }),
  run: (master: string, token: string, sheet: string, mapping: Record<string, string | null>,
        effective_from: string | null, add_new: boolean) =>
    ask<ImportResult>("POST", `/masters/${master}/import/${token}/run`,
                      { sheet, mapping, effective_from, add_new }),
  removeMissing: (master: string, token: string) =>
    ask<{ removed: number; names: string[] }>("POST", `/masters/${master}/import/${token}/remove-missing`),
  cancel: (master: string, token: string) =>
    ask<{ ok: boolean }>("DELETE", `/masters/${master}/import/${token}`),
  /** The given rows of a master as an Excel file. */
  exportRows: (master: string, ids: number[]) => download(`/masters/${master}/export`, { ids }),
};

// ---- the monthly reports tool (v0.26.0, admins only) ---------------------------
/** One of the month's three uploaded files, or null when not uploaded. */
export type MonthFile = { name: string; at: string; by: string } | null;
export type FileKind = "invoices" | "payments" | "rto";

/** What the last reading of the month's invoices gave. */
export interface ScanSummary {
  scanned_at: string;
  source: string;
  read: number;
  skipped: number;
  open_issues: number;
  invoices_held_back: number;      // invoices left out of the reports while issues are open
}

/** One generated workbook (a line of History). */
export interface Run {
  id: number;
  month: string;
  label: string;
  file_name: string;
  generated_at: string;
  user: string;
  invoices: number;
  left_out: number;
  sales: number;
  gross_profit: number;
  reports: string[];
  available: boolean;              // the file is on this server
  pdf_available: boolean;
}

export interface Overview {
  month: string;
  label: string;
  reports: string[];
  files: Record<FileKind, MonthFile>;
  scan: ScanSummary | null;
  masters: Record<string, number>;
  has_inputs: boolean;
  last_run: Run | null;
  pdf_possible: boolean;
}

export interface LogLine { kind: "ok" | "skip" | "warn" | "error"; text: string }

/** One thing on Scan review (app/data/invoices_repo.py, class Issue). */
export interface Issue {
  kind: "product" | "salesperson" | "car" | "labour" | "totals" | "file";
  key: string;
  message: string;
  invoices: string[];
  file_name: string;
  status: "open" | "skipped";
  printed: string;
  options: number[];               // suggested ids, if any
  grouped: boolean;                // one row for every invoice showing this name
  reason: string;
}

export interface Choice { id: number; text: string }

export interface SavedMatch {
  store: "alias" | "override" | "ack";
  kind: string;
  key: string;
  printed: string;
  target: string;
  scope: string;
  invoices: number;
  saved_on: string;
  type_label: string;
}

export interface InvoiceRead {
  invoice_no: string;
  date: string;
  customer: string;
  executive: string;
  printed_executive: string;
  car: string;
  printed_car: string;
  items: number;
  total: number;
  gst: string;
  payment_mode: string;
  lines: { no: number; description: string; amount: number; product: string; marker: boolean }[];
}

export interface Inputs {
  label: string;
  saved: boolean;
  costs: [string, number][];
  default_heads: string[];
  previous: { label: string; costs: [string, number][] };
  threshold: number;
  auto_rates: { key: string; head: string; pct: number }[];
}

export interface GenerateResult { run: Run; payments_used: boolean; rto_used: boolean; pdf_error: string }
type FixReply = { done: string; scan: ScanSummary | null; issues: Issue[] };
type MatchRef = Pick<SavedMatch, "store" | "kind" | "key">;

export const monthlyApi = {
  overview: (month: string) => ask<Overview>("GET", `/monthly/${month}/overview`),
  upload: (month: string, kind: FileKind, file: File) =>
    sendFile<Record<FileKind, MonthFile>>(`/monthly/${month}/files/${kind}`, file),
  removeFile: (month: string, kind: FileKind) =>
    ask<Record<FileKind, MonthFile>>("DELETE", `/monthly/${month}/files/${kind}`),
  read: (month: string) => ask<{ log: LogLine[]; scan: ScanSummary }>("POST", `/monthly/${month}/read`),
  generate: (month: string, reports: string[], pdf: boolean) =>
    ask<GenerateResult>("POST", `/monthly/${month}/generate`, { reports, pdf }),
  history: () => ask<{ runs: Run[]; pdf_possible: boolean;
                       months: { month: string; label: string; invoices: number;
                                 scanned_at: string; folder: string }[] }>("GET", "/monthly/history"),
  downloadUrl: (id: number, pdf = false) => `/api/monthly/runs/${id}/download${pdf ? "?pdf=true" : ""}`,
  regenerate: (id: number) => ask<GenerateResult>("POST", `/monthly/runs/${id}/regenerate`),
  makePdf: (id: number) => ask<Run>("POST", `/monthly/runs/${id}/pdf`),
  removeRuns: (month: string) => ask<{ removed: number }>("DELETE", `/monthly/${month}/runs`),
  removeMonth: (month: string) => ask<{ removed: number }>("DELETE", `/monthly/${month}/invoices`),
  issues: (month: string) =>
    ask<{ label: string; scan: ScanSummary | null; issues: Issue[] }>("GET", `/monthly/${month}/issues`),
  choices: () => ask<Record<"product" | "salesperson" | "car", Choice[]>>("GET", "/monthly/choices"),
  fix: (month: string, kind: string, key: string, target_id: number | null, all_invoices: boolean) =>
    ask<FixReply>("POST", `/monthly/${month}/fix`, { kind, key, target_id, all_invoices }),
  invoices: (month: string) => ask<InvoiceRead[]>("GET", `/monthly/${month}/invoices`),
  matches: (month: string) => ask<SavedMatch[]>("GET", `/monthly/${month}/matches`),
  matchChoices: (kind: string) => ask<Choice[]>("GET", `/monthly/match-choices/${kind}`),
  changeMatch: (month: string, match: MatchRef, target_id: number) =>
    ask<SavedMatch[]>("POST", `/monthly/${month}/matches/change`,
                      { store: match.store, kind: match.kind, key: match.key, target_id }),
  removeMatch: (month: string, match: MatchRef) =>
    ask<SavedMatch[]>("POST", `/monthly/${month}/matches/remove`,
                      { store: match.store, kind: match.kind, key: match.key }),
  issuesExportUrl: (month: string) => `/api/monthly/${month}/issues/export`,
  matchesExportUrl: (month: string) => `/api/monthly/${month}/matches/export`,
  inputs: (month: string) => ask<Inputs>("GET", `/monthly/${month}/inputs`),
  saveInputs: (month: string, costs: [string, number][], threshold: number) =>
    ask<Inputs>("PUT", `/monthly/${month}/inputs`, { costs, threshold }),
  saveRates: (rates: Record<string, number>) =>
    ask<Inputs["auto_rates"]>("PUT", "/monthly/auto-rates", { rates }),
};

// ---- the daily payouts (v0.27.0, staff and admins) ------------------------------
/** One amount to pay for one invoice (payout_app/register.py, payout_lines). */
export interface PayoutLine {
  line_id: string;                 // e.g. DNS-226-2627-LABM
  invoice_no: string;
  invoice_date: string;
  customer: string;
  car: string;
  type: string;                    // Labour - Floor mat / Spot incentive / Internal team ...
  payee: string;                   // "" for labour
  amount: number;
  working: string;                 // how the amount was reached
  status: "Pending" | "Paid" | "Hold" | "Cancelled";
  paid_date: string;
  mode: string;
  reference: string;
  proof: string;                   // the proof's file name on the server
  remarks: string;
  entered_by: string;
  entered_at: string;
}

type Count = { lines: number; amount: number };
export interface DailyTotals { pending: Count; hold: Count; paid_today: Count }

export interface DailyOverview {
  start_date: string;
  inbox: { name: string; size: number }[];
  in_review: number;
  invoices: number;
  totals: DailyTotals;
  modes: string[];
  types: string[];
}

export interface ReviewIssue {
  kind: "Item" | "Salesperson" | "Car" | "Totals";
  printed: string;
  message: string;
  invoices: string[];
  suggestions: string[];
}

/** What one scan found and did. */
export interface ScanReport {
  tally: Record<string, number>;
  posted: PayoutLine[];
  posted_total: number;
  corrected: number;
  review: { file_name: string; invoice_no: string; reasons: string[] }[];
  not_used: { file_name: string; reasons: string[] }[];
  issues: ReviewIssue[];
  warnings: string[];
  notes: string[];
  files_read: number;
}

export interface PayoutInvoice {
  invoice_no: string;
  invoice_date: string;
  customer: string;
  total: number;
  salesperson: string;
  file_name: string;
  state: string;
  reason: string;
  scanned_by: string;
  scanned_at: string;
}

export const dailyApi = {
  overview: () => ask<DailyOverview>("GET", "/daily/overview"),
  upload: (file: File) => sendFile<{ name: string; size: number }>("/daily/files", file),
  removeUpload: (name: string) => ask<{ ok: boolean }>("DELETE", `/daily/files/${encodeURIComponent(name)}`),
  scan: () => ask<ScanReport>("POST", "/daily/scan"),
  review: () => ask<{ invoices: PayoutInvoice[]; issues: ReviewIssue[] }>("GET", "/daily/review"),
  choices: () => ask<Record<"Item" | "Salesperson" | "Car", Choice[]>>("GET", "/daily/choices"),
  match: (kind: string, printed: string, invoices: string[], target_id: number) =>
    ask<{ done: string; report: ScanReport | null }>("POST", "/daily/match",
                                                     { kind, printed, invoices, target_id }),
  acceptTotals: (invoice_no: string) =>
    ask<{ done: string; report: ScanReport | null }>("POST", "/daily/accept-totals", { invoice_no }),
  cancel: (invoice_no: string, reason: string) =>
    ask<{ paid_lines_left: string[] }>("POST", "/daily/cancel", { invoice_no, reason }),
  lines: () => ask<{ lines: PayoutLine[]; totals: DailyTotals; invoices: PayoutInvoice[] }>("GET", "/daily/lines"),
  uploadProof: (file: File) => sendFile<{ token: string }>("/daily/proofs", file),
  pay: (body: { line_ids: string[]; paid_date: string; mode: string; reference: string;
                remarks: string; proof_token: string }) =>
    ask<{ paid: number; amount: number; proof: string }>("POST", "/daily/pay", body),
  reopen: (line_ids: string[], reason: string) =>
    ask<{ reopened: number }>("POST", "/daily/reopen", { line_ids, reason }),
  hold: (line_ids: string[], hold: boolean, reason: string) =>
    ask<{ changed: number }>("POST", "/daily/hold", { line_ids, hold, reason }),
  proofUrl: (name: string) => `/api/daily/proofs/${encodeURIComponent(name)}`,
  log: (text: string) =>
    ask<{ entries: AuditEntry[]; more: boolean }>("GET", `/daily/log?text=${encodeURIComponent(text)}`),
  setStartDate: (date: string) => ask<{ start_date: string }>("PUT", "/daily/start-date", { date }),
  clear: (confirm: string) =>
    ask<{ lines: number; invoices: number; backup: string }>("POST", "/daily/clear", { confirm }),
};

export const mastersApi = {
  list: () => ask<MasterDef[]>("GET", "/masters"),
  rows: (master: string) =>
    ask<{ rows: Row[]; lookups: Record<string, string[]> }>("GET", `/masters/${master}/rows`),
  add: (master: string, values: Record<string, Value>, effective_from: string | null) =>
    ask<Row>("POST", `/masters/${master}/rows`, { values, effective_from }),
  change: (master: string, id: number, values: Record<string, Value>, effective_from: string | null) =>
    ask<Row>("PUT", `/masters/${master}/rows/${id}`, { values, effective_from }),
  setActive: (master: string, ids: number[], active: boolean) =>
    ask<{ changed: number }>("POST", `/masters/${master}/active`, { ids, active }),
  remove: (master: string, ids: number[]) =>
    ask<{ deleted: number }>("POST", `/masters/${master}/delete`, { ids }),
  removeAll: (master: string, confirm: string) =>
    ask<{ deleted: number }>("POST", `/masters/${master}/delete-all`, { confirm }),
  rates: (master: string, id: number) => ask<Rate[]>("GET", `/masters/${master}/rows/${id}/rates`),
  removeRate: (master: string, id: number, effective_from: string) =>
    ask<Rate[]>("POST", `/masters/${master}/rows/${id}/rates/delete`, { effective_from }),
  audit: (filters: AuditFilters) =>
    ask<{ entries: AuditEntry[]; more: boolean; limit: number;
          masters: { key: string; title: string }[] }>("GET", `/audit?${query(filters)}`),
  /** The address of the Excel download for the same filters. */
  auditExportUrl: (filters: AuditFilters) => `/api/audit/export?${query(filters)}`,
};

/** 1234567.5 -> "12,34,567.50" (Indian grouping, as everywhere in the tool). */
export function inr(amount: number): string {
  return amount.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** "2026-10-09" -> "09-10-2026". */
export function showDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
}

/** Today as "YYYY-MM-DD", for date boxes. */
export function today(): string {
  const d = new Date();
  const two = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
}

/** "2026-10-09T11:42:10" -> "09-10-2026 11:42" (dates are dd-mm-yyyy everywhere). */
export function showDateTime(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || "");
  return m ? `${m[3]}-${m[2]}-${m[1]} ${m[4]}:${m[5]}` : "";
}

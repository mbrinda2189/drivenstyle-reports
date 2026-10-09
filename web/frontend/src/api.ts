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

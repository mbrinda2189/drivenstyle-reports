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

/** "2026-10-09T11:42:10" -> "09-10-2026 11:42" (dates are dd-mm-yyyy everywhere). */
export function showDateTime(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || "");
  return m ? `${m[3]}-${m[2]}-${m[1]} ${m[4]}:${m[5]}` : "";
}

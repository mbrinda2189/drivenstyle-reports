"""
users_repo.py - Who may sign in to the web tool, and as what (v0.23.0)
======================================================================

WHAT THIS MODULE DOES
---------------------
The web tool is on the internet, so it must know who is allowed in. The
`users` table is that list: one row per person, found by e-mail address
(the address they sign in to Google with).

    role "admin"   sees everything: daily payouts, monthly reports,
                   masters, audit log and this list of users
    role "staff"   sees the daily payouts only (the monthly reports show
                   cost and profit - Brinda, 09-10-2026)

    active = No    the person stays in the list (so the audit log still
                   makes sense) but can no longer sign in

RULES
-----
* An e-mail address appears once. It is stored in lower case, so
  "Asha@Gmail.com" and "asha@gmail.com" are the same person.
* THERE IS ALWAYS AT LEAST ONE ACTIVE ADMIN. The last one cannot be
  removed, made inactive or changed to staff - otherwise nobody could let
  anyone in again.
* Every change (added, role changed, made inactive, removed) is written to
  the audit log in the same transaction, with the e-mail of the person who
  made it - the same read-only log the masters use (master = "users").
* `ensure_admins` is the way in on day one: when the list has no active
  admin, the addresses given in the server's settings are added as admins.

No Qt code and no web code here: the server (web/backend) calls this.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

ROLES = ("admin", "staff")
MASTER = "users"                 # the name used in the audit log
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserError(Exception):
    """A plain-language reason a user could not be saved."""


def email_key(email: str) -> str:
    """The e-mail address in the form it is stored and compared in."""
    return (email or "").strip().lower()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class UsersRepo:
    """Read and write the sign-in list in an open database connection."""

    def __init__(self, conn: sqlite3.Connection, user: str = ""):
        self.conn = conn
        self.user = user          # who is making the changes (for the audit log)

    # ---- reading ---------------------------------------------------------
    def list_users(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM users ORDER BY role, email")]

    def get(self, user_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def by_email(self, email: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE email = ?",
                                (email_key(email),)).fetchone()
        return dict(row) if row else None

    def active_admins(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' "
                                 "AND active = 1").fetchone()[0]

    # ---- writing ---------------------------------------------------------
    def _audit(self, row_id: int, email: str, action: str, field: str = "",
               old: str = "", new: str = "", source: str = "Users screen") -> None:
        self.conn.execute(
            "INSERT INTO audit_log(at, user, master, record_id, record, action, "
            "field, old_value, new_value, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_now(), self.user, MASTER, row_id, email, action, field, old, new, source))

    @staticmethod
    def _check(email: str, role: str) -> None:
        if not _EMAIL.match(email):
            raise UserError(f"“{email}” is not an e-mail address.")
        if role not in ROLES:
            raise UserError("The role must be admin or staff.")

    def add(self, email: str, name: str = "", role: str = "staff",
            source: str = "Users screen") -> dict:
        email, name = email_key(email), (name or "").strip()
        self._check(email, role)
        if self.by_email(email):
            raise UserError(f"{email} is already in the list.")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO users(email, name, role, active, created_at) "
                "VALUES (?, ?, ?, 1, ?)", (email, name, role, _now()))
            self._audit(cur.lastrowid, email, "Added", "Role", "", role, source)
        return self.get(cur.lastrowid)

    def update(self, user_id: int, name: str | None = None, role: str | None = None,
               active: bool | None = None) -> dict:
        """Change the name, role and / or active flag; only real changes are logged."""
        before = self.get(user_id)
        if before is None:
            raise UserError("This user is no longer in the list.")
        after = dict(before)
        if name is not None:
            after["name"] = name.strip()
        if role is not None:
            after["role"] = role
        if active is not None:
            after["active"] = 1 if active else 0
        self._check(after["email"], after["role"])
        was_admin = before["role"] == "admin" and before["active"]
        stays_admin = after["role"] == "admin" and after["active"]
        if was_admin and not stays_admin and self.active_admins() <= 1:
            raise UserError("This is the only active admin. Make another person "
                            "an admin first.")
        with self.conn:
            self.conn.execute("UPDATE users SET name = ?, role = ?, active = ? WHERE id = ?",
                              (after["name"], after["role"], after["active"], user_id))
            if after["name"] != before["name"]:
                self._audit(user_id, before["email"], "Edited", "Name",
                            before["name"], after["name"])
            if after["role"] != before["role"]:
                self._audit(user_id, before["email"], "Edited", "Role",
                            before["role"], after["role"])
            if after["active"] != before["active"]:
                self._audit(user_id, before["email"],
                            "Activated" if after["active"] else "Deactivated")
        return self.get(user_id)

    def remove(self, user_id: int) -> None:
        row = self.get(user_id)
        if row is None:
            return
        if row["role"] == "admin" and row["active"] and self.active_admins() <= 1:
            raise UserError("This is the only active admin. Make another person "
                            "an admin first.")
        with self.conn:
            self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self._audit(user_id, row["email"], "Deleted", "Role", row["role"], "")

    def touch_login(self, user_id: int, name: str = "") -> None:
        """Note the time of a sign-in (and the name Google gives, if none is kept).
        Not an audit entry: signing in changes nothing in the data."""
        with self.conn:
            self.conn.execute("UPDATE users SET last_login = ? WHERE id = ?",
                              (_now(), user_id))
            if name.strip():
                self.conn.execute("UPDATE users SET name = ? WHERE id = ? AND name = ''",
                                  (name.strip(), user_id))

    def ensure_admins(self, emails: list[str]) -> list[str]:
        """
        Day one: when nobody in the list is an active admin, add the given
        addresses as admins (or make them active admins again). Returns the
        addresses set up; an empty list when an admin already exists.
        """
        if self.active_admins():
            return []
        done = []
        for email in filter(None, map(email_key, emails)):
            row = self.by_email(email)
            if row is None:
                self.add(email, role="admin", source="Server settings")
            else:
                with self.conn:
                    self.conn.execute("UPDATE users SET role = 'admin', active = 1 "
                                      "WHERE id = ?", (row["id"],))
                    self._audit(row["id"], email, "Edited", "Role", row["role"],
                                "admin", "Server settings")
            done.append(email)
        return done

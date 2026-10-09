"""
main.py - The web tool's server (sign-in, roles, users; masters from v0.24.0)
============================================================================

WHAT THIS MODULE DOES
---------------------
This is the program that runs on the server. The screens in the browser
(web/frontend) never touch the database themselves: they ask this program,
through web addresses that all start with /api, and it answers with data.

    python -m uvicorn web.backend.main:app --port 8000      (from the project folder)

ADDRESSES IN THIS VERSION
    GET    /api/config          what the sign-in page needs: Google client
                                ID, whether the test sign-in is on, version
    POST   /api/auth/google     sign in with Google's signed note
    POST   /api/auth/dev        TEST sign-in (only when DNS_WEB_DEV_LOGIN=1)
    POST   /api/auth/logout     sign out
    GET    /api/me              who is signed in, and their role
    GET    /api/users           the users list                  (admin only)
    POST   /api/users           add a user                      (admin only)
    PATCH  /api/users/{id}      change name / role / active     (admin only)
    DELETE /api/users/{id}      remove a user                   (admin only)
    /api/masters..., /api/audit...   see masters_api.py (v0.24.0)
    /api/masters/.../import..., /export   see imports_api.py (v0.25.0)
    /api/monthly/...                 see monthly_api.py (v0.26.0, admin only)
    /api/daily/...                   see daily_api.py (v0.27.0)

    Everything else serves the built screens (web/frontend/dist), so the
    tool has ONE address in production.

WHO MAY DO WHAT
    * Not signed in: only /api/config and the sign-in addresses answer.
      Everything else says 401 ("sign in first").
    * Staff: /api/me, the daily payouts and the masters (Brinda, 09-10-2026: staff enter cost
      and rates too - the firm's partner will not). The admin addresses
      (users, audit log) say 403 ("not allowed").
    * Admin: everything.
    The check is made HERE, on the server, at every request - hiding a
    menu on the screen is not a control.

SAFETY NOTES
    * Requests that change something must carry the header "X-DNS-Request".
      A page on another website cannot add that header to a request it
      tricks a signed-in person's browser into sending, so it is refused.
    * One database connection per request, opened and closed inside it.
      SQLite is put in "WAL" mode, which lets several people read while one
      writes; a writer waits up to 5 seconds for another instead of failing.
    * The signed-in person's e-mail is what the audit log records.

The calculations (sales, cost, labour, incentive, the workbook) are NOT
here and never will be: later versions call app/data, app/reports and
payout_app/engine.py as they are.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app import __version__
from app.data.database import connect
from app.data.users_repo import UserError, UsersRepo
from web.backend import config, daily_api, imports_api, masters_api, monthly_api
from web.backend.security import COOKIE, Sessions, SignInError, verify_google

log = logging.getLogger("dns_web")

CSRF_HEADER = "x-dns-request"
NOT_ON_LIST = ("This e-mail address is not on the tool's list of users. "
               "Ask an admin to add it.")


# ---- what the screens send ------------------------------------------------
class GoogleSignIn(BaseModel):
    credential: str


class DevSignIn(BaseModel):
    email: str


class NewUser(BaseModel):
    email: str
    name: str = ""
    role: str = "staff"


class UserChange(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None


def _public(user: dict) -> dict:
    """A user row as the screens see it."""
    return {"id": user["id"], "email": user["email"], "name": user["name"],
            "role": user["role"], "active": bool(user["active"]),
            "created_at": user["created_at"], "last_login": user["last_login"]}


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sessions = Sessions(settings.session_secret(), settings.session_hours)

    api = FastAPI(title="Drive N Style", version=__version__,
                  docs_url=None, redoc_url=None, openapi_url=None)
    api.state.settings = settings
    api.state.verify_google = verify_google       # the tests put a stand-in here

    @contextmanager
    def connection():
        """The database for one request: opened, used and closed inside it."""
        conn = connect(settings.db_path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def database(user: str = ""):
        """The users list for one request; `user` goes into the audit log."""
        with connection() as conn:
            yield UsersRepo(conn, user=user)

    # Day one: the admins named in the settings, when the list has none.
    with database("Server settings") as users:
        for email in users.ensure_admins(settings.admins):
            log.warning("Users list had no admin: %s was made admin.", email)
    if settings.dev_login:
        log.warning("TEST SIGN-IN IS ON (DNS_WEB_DEV_LOGIN). Never on the real server.")

    # ---- the header check for requests that change something --------------
    @api.middleware("http")
    async def changes_need_the_header(request: Request, call_next):
        if (request.url.path.startswith("/api/")
                and request.method not in ("GET", "HEAD", "OPTIONS")
                and CSRF_HEADER not in request.headers):
            return JSONResponse({"detail": "This request did not come from the tool's "
                                           "own screens."}, status_code=403)
        return await call_next(request)

    # ---- who is asking -----------------------------------------------------
    def current_user(request: Request) -> dict:
        user_id = sessions.read(request.cookies.get(COOKIE))
        user = None
        if user_id is not None:
            with database() as users:
                user = users.get(user_id)
        if not user or not user["active"]:
            raise HTTPException(401, "Please sign in.")
        return user

    def admin(user: dict = Depends(current_user)) -> dict:
        if user["role"] != "admin":
            raise HTTPException(403, "Only an admin can open this.")
        return user

    def _sign_in(response: Response, email: str, name: str = "") -> dict:
        """Let a person in if their address is an active row of the users list."""
        with database() as users:
            user = users.by_email(email)
            if not user or not user["active"]:
                raise HTTPException(403, NOT_ON_LIST)
            users.touch_login(user["id"], name)
            user = users.get(user["id"])
        response.set_cookie(COOKIE, sessions.make(user["id"]), max_age=sessions.max_age,
                            httponly=True, samesite="lax", secure=settings.https, path="/")
        return _public(user)

    # ---- sign-in -----------------------------------------------------------
    @api.get("/api/config")
    def get_config() -> dict:
        return {"version": __version__, "google_client_id": settings.google_client_id,
                "dev_login": settings.dev_login}

    @api.post("/api/auth/google")
    def sign_in_google(body: GoogleSignIn, response: Response) -> dict:
        try:
            who = api.state.verify_google(body.credential, settings.google_client_id)
        except SignInError as exc:
            raise HTTPException(401, str(exc)) from exc
        return _sign_in(response, who["email"], who.get("name", ""))

    @api.post("/api/auth/dev")
    def sign_in_test(body: DevSignIn, response: Response) -> dict:
        if not settings.dev_login:
            raise HTTPException(404, "Not found.")
        return _sign_in(response, body.email)

    @api.post("/api/auth/logout")
    def sign_out(response: Response) -> dict:
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @api.get("/api/me")
    def me(user: dict = Depends(current_user)) -> dict:
        return _public(user)

    # ---- the users list (admin) ---------------------------------------------
    @api.get("/api/users")
    def list_users(who: dict = Depends(admin)) -> list[dict]:
        with database() as users:
            return [_public(u) for u in users.list_users()]

    @api.post("/api/users", status_code=201)
    def add_user(body: NewUser, who: dict = Depends(admin)) -> dict:
        with database(who["email"]) as users:
            try:
                return _public(users.add(body.email, body.name, body.role))
            except UserError as exc:
                raise HTTPException(400, str(exc)) from exc

    @api.patch("/api/users/{user_id}")
    def change_user(user_id: int, body: UserChange, who: dict = Depends(admin)) -> dict:
        with database(who["email"]) as users:
            try:
                return _public(users.update(user_id, body.name, body.role, body.active))
            except UserError as exc:
                raise HTTPException(400, str(exc)) from exc

    @api.delete("/api/users/{user_id}")
    def remove_user(user_id: int, who: dict = Depends(admin)) -> dict:
        with database(who["email"]) as users:
            try:
                users.remove(user_id)
            except UserError as exc:
                raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    # ---- masters and audit log (v0.24.0) ----------------------------------------
    masters_api.add_routes(api, connection, current_user, admin)
    # Import from / export to Excel (v0.25.0); uploaded sheets wait in data/web/uploads.
    imports_api.add_routes(api, connection, current_user, admin,
                           settings.data_dir / "uploads")
    # The monthly reports tool (v0.26.0) - admins only.
    monthly_api.add_routes(api, connection, admin, settings.data_dir)
    # The daily payouts (v0.27.0) - staff and admins.
    daily_api.add_routes(api, connection, current_user, admin, settings.data_dir)

    @api.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def no_such_address(rest: str):
        raise HTTPException(404, "Not found.")

    # ---- the screens ---------------------------------------------------------
    @api.get("/{path:path}")
    def screens(path: str):
        """
        The built React screens. A file that exists (script, style, icon) is
        sent as it is; any other address gets index.html, because the screens
        handle their own addresses (/monthly/generate ...) in the browser.
        """
        dist: Path = settings.frontend_dir
        index = dist / "index.html"
        if not index.is_file():
            return JSONResponse({"detail": "The screens have not been built yet: run "
                                 "`npm run build` in web/frontend (or use `npm run dev`)."},
                                status_code=503)
        target = (dist / path).resolve()
        if path and target.is_file() and dist.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return api


def __getattr__(name: str):
    """`web.backend.main:app` for uvicorn - made only when asked for, so
    importing this module (e.g. in the tests) does not open the database."""
    if name == "app":
        return create_app()
    raise AttributeError(name)

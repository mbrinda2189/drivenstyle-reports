"""
test_web_auth.py - The web server: sign-in, roles and the users list (v0.23.0)
==============================================================================

Run against the real server program with a stand-in for Google (no
internet) and a database in a temporary folder. Skipped on a PC where the
server's packages are not installed (pip install -r web/backend/requirements.txt).

What is proved here:
    * only people on the users list get in; an inactive person does not
    * nothing answers without a sign-in; staff cannot open admin addresses
    * the first admin comes from the settings
    * the last admin cannot be removed, made inactive or made staff
    * every change to the list is in the audit log with who made it
    * the test sign-in does not exist unless it is switched on
    * a request without the tool's own header changes nothing
    * the users table upgrade keeps an existing database's data
"""

import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("itsdangerous")

from fastapi.testclient import TestClient          # noqa: E402

from app.data.database import SCHEMA_VERSION, connect   # noqa: E402
from app.data.users_repo import UserError, UsersRepo    # noqa: E402
from web.backend import config                      # noqa: E402
from web.backend.main import create_app             # noqa: E402
from web.backend.security import COOKIE, Sessions, SignInError   # noqa: E402

ADMIN = "automation.drivenstyle@gmail.com"
H = {"X-DNS-Request": "1"}


def fake_google(credential: str, client_id: str) -> dict:
    """Stand-in for Google: the "credential" is simply the e-mail address."""
    if credential == "forged":
        raise SignInError("Google could not confirm this sign-in. Please try again.")
    return {"email": credential, "name": "From Google"}


def make(tmp_path, **changes):
    settings = config.Settings(data_dir=tmp_path / "web", admins=[ADMIN],
                               google_client_id="test-client", secret="test-secret",
                               frontend_dir=tmp_path / "dist")
    for key, value in changes.items():
        setattr(settings, key, value)
    app = create_app(settings)
    app.state.verify_google = fake_google
    return app, settings


def sign_in(app, email: str) -> TestClient:
    client = TestClient(app)
    reply = client.post("/api/auth/google", json={"credential": email}, headers=H)
    assert reply.status_code == 200, reply.text
    return client


@pytest.fixture
def app(tmp_path):
    return make(tmp_path)[0]


def test_first_admin_comes_from_the_settings(app):
    admin = sign_in(app, ADMIN.upper())            # capitals do not matter
    me = admin.get("/api/me").json()
    assert me["email"] == ADMIN and me["role"] == "admin" and me["name"] == "From Google"
    assert [u["email"] for u in admin.get("/api/users").json()] == [ADMIN]


def test_nothing_answers_without_a_sign_in(app):
    client = TestClient(app)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/users").status_code == 401
    assert client.post("/api/users", json={"email": "x@y.in"}, headers=H).status_code == 401
    assert client.get("/api/config").json()["google_client_id"] == "test-client"
    assert client.get("/api/nothing-here").status_code == 404


def test_people_not_on_the_list_are_refused(app):
    client = TestClient(app)
    reply = client.post("/api/auth/google", json={"credential": "stranger@gmail.com"}, headers=H)
    assert reply.status_code == 403 and "not on the tool's list" in reply.json()["detail"]
    assert COOKIE not in client.cookies
    assert client.post("/api/auth/google", json={"credential": "forged"},
                       headers=H).status_code == 401


def test_staff_cannot_open_admin_addresses(app):
    admin = sign_in(app, ADMIN)
    made = admin.post("/api/users", json={"email": "Asha@Gmail.com", "name": "Asha"}, headers=H)
    assert made.status_code == 201 and made.json()["role"] == "staff"
    assert made.json()["email"] == "asha@gmail.com"
    staff = sign_in(app, "asha@gmail.com")
    assert staff.get("/api/me").json()["role"] == "staff"
    assert staff.get("/api/users").status_code == 403
    assert staff.post("/api/users", json={"email": "friend@gmail.com", "role": "admin"},
                      headers=H).status_code == 403
    assert staff.patch(f"/api/users/{made.json()['id']}", json={"role": "admin"},
                       headers=H).status_code == 403


def test_inactive_person_is_out_at_once(app):
    admin = sign_in(app, ADMIN)
    asha = admin.post("/api/users", json={"email": "asha@gmail.com"}, headers=H).json()
    staff = sign_in(app, "asha@gmail.com")
    assert staff.get("/api/me").status_code == 200
    assert admin.patch(f"/api/users/{asha['id']}", json={"active": False},
                       headers=H).json()["active"] is False
    assert staff.get("/api/me").status_code == 401          # the old cookie is no use
    assert TestClient(app).post("/api/auth/google", json={"credential": "asha@gmail.com"},
                                headers=H).status_code == 403


def test_the_last_admin_is_protected(app):
    admin = sign_in(app, ADMIN)
    me = admin.get("/api/me").json()["id"]
    for change in ({"role": "staff"}, {"active": False}):
        reply = admin.patch(f"/api/users/{me}", json=change, headers=H)
        assert reply.status_code == 400 and "only active admin" in reply.json()["detail"]
    assert admin.delete(f"/api/users/{me}", headers=H).status_code == 400
    # With a second admin the first can step down.
    admin.post("/api/users", json={"email": "brinda@example.in", "role": "admin"}, headers=H)
    assert admin.patch(f"/api/users/{me}", json={"role": "staff"}, headers=H).status_code == 200
    assert admin.get("/api/users").status_code == 403       # no longer an admin


def test_bad_entries_are_refused_in_plain_words(app):
    admin = sign_in(app, ADMIN)
    assert "not an e-mail" in admin.post("/api/users", json={"email": "asha"},
                                         headers=H).json()["detail"]
    assert "admin or staff" in admin.post("/api/users", json={"email": "a@b.in", "role": "boss"},
                                          headers=H).json()["detail"]
    assert "already in the list" in admin.post("/api/users", json={"email": ADMIN},
                                               headers=H).json()["detail"]


def test_every_change_is_in_the_audit_log(tmp_path):
    app, settings = make(tmp_path)
    admin = sign_in(app, ADMIN)
    asha = admin.post("/api/users", json={"email": "asha@gmail.com"}, headers=H).json()
    admin.patch(f"/api/users/{asha['id']}", json={"role": "admin", "name": "Asha"}, headers=H)
    admin.patch(f"/api/users/{asha['id']}", json={"role": "admin"}, headers=H)   # no change
    admin.delete(f"/api/users/{asha['id']}", headers=H)
    conn = connect(settings.db_path)
    rows = [tuple(r) for r in conn.execute(
        "SELECT user, record, action, field, old_value, new_value FROM audit_log "
        "WHERE master = 'users' ORDER BY id")]
    assert rows == [
        ("Server settings", ADMIN, "Added", "Role", "", "admin"),
        (ADMIN, "asha@gmail.com", "Added", "Role", "", "staff"),
        (ADMIN, "asha@gmail.com", "Edited", "Name", "", "Asha"),
        (ADMIN, "asha@gmail.com", "Edited", "Role", "staff", "admin"),
        (ADMIN, "asha@gmail.com", "Deleted", "Role", "admin", ""),
    ]
    with pytest.raises(sqlite3.DatabaseError):               # the log stays read-only
        conn.execute("DELETE FROM audit_log")


def test_test_sign_in_exists_only_when_switched_on(tmp_path):
    off, _ = make(tmp_path / "a")
    assert TestClient(off).post("/api/auth/dev", json={"email": ADMIN},
                                headers=H).status_code == 404
    assert off.state.settings.dev_login is False
    on, _ = make(tmp_path / "b", dev_login=True)
    client = TestClient(on)
    assert client.get("/api/config").json()["dev_login"] is True
    assert client.post("/api/auth/dev", json={"email": "stranger@gmail.com"},
                       headers=H).status_code == 403          # still only the list
    assert client.post("/api/auth/dev", json={"email": ADMIN}, headers=H).status_code == 200
    assert client.get("/api/me").json()["role"] == "admin"


def test_changes_need_the_tools_own_header(app):
    admin = sign_in(app, ADMIN)
    assert admin.post("/api/users", json={"email": "asha@gmail.com"}).status_code == 403
    assert len(admin.get("/api/users").json()) == 1


def test_sign_out_and_altered_or_old_tickets(tmp_path):
    app, settings = make(tmp_path)
    admin = sign_in(app, ADMIN)
    assert admin.post("/api/auth/logout", headers=H).status_code == 200
    assert admin.get("/api/me").status_code == 401
    good = Sessions("test-secret", 12).make(1)
    for ticket, expected in ((good, 200), (good[:-2] + "xx", 401),
                             (Sessions("another-key", 12).make(1), 401),
                             (Sessions("test-secret", -1).make(1), 200)):
        client = TestClient(app)
        client.cookies.set(COOKIE, ticket)
        assert client.get("/api/me").status_code == expected
    # A ticket older than the allowed time is refused.
    short, _ = make(tmp_path / "short", session_hours=-1)
    client = sign_in(short, ADMIN)
    assert client.get("/api/me").status_code == 401


def test_screens_are_served_from_the_built_folder(tmp_path):
    app, settings = make(tmp_path)
    client = TestClient(app)
    assert client.get("/").status_code == 503                 # not built yet
    (settings.frontend_dir / "assets").mkdir(parents=True)
    (settings.frontend_dir / "index.html").write_text("<p>screens</p>")
    (settings.frontend_dir / "assets" / "app.js").write_text("// js")
    (tmp_path / "secret.txt").write_text("private")
    assert "screens" in client.get("/").text
    assert "screens" in client.get("/monthly/generate").text  # the screens' own addresses
    assert client.get("/assets/app.js").text == "// js"
    assert "private" not in client.get("/..%2Fsecret.txt").text


def test_users_table_upgrade_keeps_the_data(tmp_path):
    """A database of the desktop tool (schema 12) gains the users table only."""
    path = tmp_path / "old.db"
    conn = connect(path)
    conn.execute("DROP TABLE users")
    conn.execute("UPDATE meta SET value = '12' WHERE key = 'schema_version'")
    conn.execute("INSERT INTO cars(make, model, car_key, segment, active) "
                 "VALUES ('Hyundai', 'i20', 'hyundai|i20', 'Hatchback', 1)")
    conn.commit()
    conn.close()
    conn = connect(path)
    assert conn.execute("SELECT value FROM meta WHERE key='schema_version'"
                        ).fetchone()[0] == str(SCHEMA_VERSION)
    assert conn.execute("SELECT model FROM cars").fetchone()[0] == "i20"
    assert (tmp_path / "old.schema12.bak.db").is_file()       # copy made before upgrading
    users = UsersRepo(conn, user="test")
    assert users.ensure_admins([ADMIN]) == [ADMIN] and users.ensure_admins(["x@y.in"]) == []
    with pytest.raises(UserError):
        users.add(ADMIN)

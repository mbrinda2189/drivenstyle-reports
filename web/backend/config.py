"""
config.py - The server's settings (v0.23.0)
===========================================

WHAT THIS MODULE DOES
---------------------
Everything that differs between Brinda's PC and the client's AWS server is
a SETTING, read once when the server starts. Settings are "environment
variables": named values given to the program from outside, so no password
or key is ever written in the code or committed to Git.

    DNS_WEB_DATA_DIR         folder of the web tool's database and its
                             secret key. Default: data/web/ in the project
                             (data/ is never committed). NOT the desktop
                             tool's folder - the two do not share a file
                             unless you point this at it on purpose.
    DNS_WEB_ADMINS           e-mail addresses (comma separated) made admin
                             when the list of users has no active admin.
                             Default: automation.drivenstyle@gmail.com
    DNS_WEB_GOOGLE_CLIENT_ID the "Web application" client ID from Google
                             Cloud. Without it the Google button is not
                             shown (see web/README.md for the steps).
    DNS_WEB_DEV_LOGIN        1 = also allow the TEST SIGN-IN (type an e-mail
                             of the users list, no Google). For Brinda's PC
                             only. NEVER switch it on on the real server:
                             anyone who knows an admin's e-mail could enter.
    DNS_WEB_HTTPS            1 on the real server: the sign-in cookie is
                             then sent over HTTPS only.
    DNS_WEB_SESSION_HOURS    hours a sign-in lasts (default 12).
    DNS_WEB_SECRET           the key that signs the sign-in cookie. When
                             not given, a random key is created once and
                             kept in <data dir>/web_secret.key.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent      # the project folder
DEFAULT_ADMINS = "automation.drivenstyle@gmail.com"
DB_FILE_NAME = "drivenstyle.db"


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    data_dir: Path
    admins: list[str] = field(default_factory=list)
    google_client_id: str = ""
    dev_login: bool = False
    https: bool = False
    session_hours: float = 12.0
    secret: str = ""
    frontend_dir: Path = ROOT / "web" / "frontend" / "dist"

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILE_NAME

    def session_secret(self) -> str:
        """The cookie-signing key: the setting, else a key file made once."""
        if self.secret:
            return self.secret
        key_file = self.data_dir / "web_secret.key"
        if not key_file.is_file():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            key_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        self.secret = key_file.read_text(encoding="utf-8").strip()
        return self.secret


def load() -> Settings:
    """The settings from the environment (see the module notes)."""
    env = os.environ.get
    return Settings(
        data_dir=Path(env("DNS_WEB_DATA_DIR") or ROOT / "data" / "web"),
        admins=[a.strip() for a in env("DNS_WEB_ADMINS", DEFAULT_ADMINS).split(",")
                if a.strip()],
        google_client_id=env("DNS_WEB_GOOGLE_CLIENT_ID", "").strip(),
        dev_login=_flag("DNS_WEB_DEV_LOGIN"),
        https=_flag("DNS_WEB_HTTPS"),
        session_hours=float(env("DNS_WEB_SESSION_HOURS") or 12),
        secret=env("DNS_WEB_SECRET", "").strip(),
    )

"""
test_deploy.py - Checks on the files that put the tool on the server (v0.29.0)
==============================================================================

WHAT THESE TESTS GUARD
----------------------
The files in deploy/ run on the client's Linux server, where a mistake is
costly (the server is shared with other sites). They cannot be run here,
so these tests check the things that can be checked on any PC:

    * Unix line ends - a script with Windows line ends does not run there
    * the settings file has every name install.sh reads, and nothing that
      looks like a secret
    * the TEST SIGN-IN is never switched on by the server files
    * the tool listens inside the server only (127.0.0.1)
    * the two templates still carry the words install.sh fills in
    * nginx is only reloaded, and checked before and after our file
"""

from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
SERVER_FILES = ["install.sh", "backup.sh", "server.conf", "nginx-site.conf",
                "drivenstyle.service"]


def text(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def settings() -> dict:
    lines = [line.strip() for line in text("server.conf").splitlines()]
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_server_files_are_plain_ascii_and_marked_for_unix_line_ends():
    marks = (DEPLOY.parent / ".gitattributes").read_text(encoding="utf-8")
    for pattern in ("deploy/*.sh", "deploy/*.conf", "deploy/*.service"):
        assert pattern in marks and "eol=lf" in marks
    for name in SERVER_FILES + ["deploy.ps1"]:
        (DEPLOY / name).read_bytes().decode("ascii")       # raises if not ASCII


def test_settings_file_is_complete_and_holds_no_secret():
    values = settings()
    assert set(values) == {"DOMAIN", "PORT", "GOOGLE_CLIENT_ID", "ADMINS",
                           "CERT_EMAIL", "BACKUP_DAYS"}
    assert values["PORT"].isdigit() and values["BACKUP_DAYS"].isdigit()
    assert "." in values["DOMAIN"] and "/" not in values["DOMAIN"]
    assert values["GOOGLE_CLIENT_ID"].endswith(".apps.googleusercontent.com")
    for name in values:                                    # no secret among the names
        assert not any(word in name for word in ("SECRET", "PASSWORD", "TOKEN", "KEY"))


def test_test_sign_in_is_never_switched_on_on_the_server():
    for name in ("install.sh", "drivenstyle.service", "server.conf"):
        lines = [line for line in text(name).splitlines() if not line.lstrip().startswith("#")]
        assert not any("DNS_WEB_DEV_LOGIN" in line for line in lines), name
    assert "DNS_WEB_HTTPS=1" in text("install.sh")


def test_tool_listens_inside_the_server_only():
    assert "--host 127.0.0.1" in text("drivenstyle.service")
    assert "0.0.0.0" not in text("drivenstyle.service")
    assert "proxy_pass http://127.0.0.1:__PORT__;" in text("nginx-site.conf")
    assert "User=drivenstyle" in text("drivenstyle.service")


def test_templates_carry_the_words_install_fills_in():
    assert "__DOMAIN__" in text("nginx-site.conf") and "__PORT__" in text("nginx-site.conf")
    assert "__PORT__" in text("drivenstyle.service")
    script = text("install.sh")
    assert "s/__DOMAIN__/$DOMAIN/g" in script and "s/__PORT__/$PORT/g" in script


def test_nginx_is_checked_and_only_reloaded():
    script = text("install.sh")
    assert script.count("nginx -t") >= 2                   # before and after our file
    assert "systemctl reload nginx" in script
    for never in ("restart nginx", "stop nginx", "restart mysql", "apt-get upgrade",
                  "apt-get dist-upgrade", "apache2"):
        lines = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
        assert not any(never in line for line in lines), never

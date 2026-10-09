#!/usr/bin/env bash
# install.sh - Puts the tool on the server, or brings it up to date (v0.29.0)
# ===========================================================================
#
# WHAT THIS DOES
# --------------
# It runs ON THE SERVER, started for you by  deploy\deploy.ps1  on the PC
# (you never type it yourself). The same script does the first install and
# every later update - it only does what is not there yet:
#
#   1. checks: room on the disk, the port is free
#   2. installs what is missing (first time only): Python's "venv",
#      LibreOffice Calc (for the PDF reports), the Carlito font (same
#      widths as Calibri), Indian number formats
#   3. creates the tool's own user "drivenstyle" and its folders
#   4. copies the new version of the code next to the running one
#   5. installs the Python libraries into the tool's own folder
#   6. writes the settings (/etc/drivenstyle.env) from deploy/server.conf
#   7. swaps the new version in, restarts the tool and CHECKS that it
#      answers. If it does not, the previous version is put back.
#   8. first time only: adds the tool's one site to nginx and gets the
#      HTTPS certificate
#   9. sets up the nightly backup
#
# WHERE EVERYTHING GOES
#     /opt/drivenstyle/app           the code (this version)
#     /opt/drivenstyle/app.previous  the version before it (to go back)
#     /opt/drivenstyle/venv          the Python libraries
#     /opt/drivenstyle/data          THE DATA: database, uploads, reports,
#                                    proofs. Never touched by an update.
#     /opt/drivenstyle/backups       nightly copies of the database
#     /etc/drivenstyle.env           the settings
#     /etc/systemd/system/drivenstyle.service   keeps the tool running
#     /etc/nginx/sites-available/<address>      the tool's site in nginx
#     /etc/cron.d/drivenstyle-backup            the nightly backup
#
# WHAT IT NEVER DOES (the server is shared with other sites)
#     * It does not upgrade or restart any other program. Only the named
#       packages are installed; "needrestart" is told not to restart
#       anything.
#     * It does not edit any other site's nginx file. nginx is checked
#       BEFORE and AFTER our one file is added; if the check fails our file
#       is taken out again, and nginx is only ever reloaded (never stopped).
#     * It does not touch MySQL, PHP or Apache.
#     * The test sign-in (DNS_WEB_DEV_LOGIN) is never switched on here.
#
# OTHER USES (also started by deploy.ps1)
#     install.sh --bring-across FILE [--replace]
#         copy a desktop database into the web tool (web/backend/bring_across.py)
#     install.sh --make-backup
#         make a fresh backup and put it in /tmp for the PC to fetch
#     install.sh --status
#         say whether the tool runs, its version, disk and backups

set -euo pipefail

HOME_DIR=/opt/drivenstyle
APP="$HOME_DIR/app"
VENV="$HOME_DIR/venv"
DATA="$HOME_DIR/data"
BACKUPS="$HOME_DIR/backups"
ENV_FILE=/etc/drivenstyle.env
UNIT=/etc/systemd/system/drivenstyle.service
RUN_USER=drivenstyle
NEEDED_MB=2500          # free disk needed for a first install

say()  { echo; echo "== $*"; }
warn() { echo "   NOTE: $*"; }
die()  { echo; echo "STOPPED: $*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "this must be run with sudo."

read_settings() {       # the NAME=value lines of deploy/server.conf
    [ -f "$1" ] || die "settings file not found: $1"
    # shellcheck disable=SC1090
    . <(tr -d '\r' < "$1")
    : "${DOMAIN:?DOMAIN is empty in deploy/server.conf}"
    : "${PORT:=8010}" "${ADMINS:=automation.drivenstyle@gmail.com}"
    : "${GOOGLE_CLIENT_ID:=}" "${CERT_EMAIL:=$ADMINS}" "${BACKUP_DAYS:=14}"
}

answers() {             # does the tool answer inside the server? prints its version
    "$VENV/bin/python" - "$PORT" <<'PY'
import json, sys, time, urllib.request
for _ in range(30):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/config", timeout=3) as reply:
            print(json.load(reply)["version"]); sys.exit(0)
    except Exception:
        time.sleep(1)
sys.exit(1)
PY
}

as_tool() {             # run a command as the tool's user, in the code folder
    ( cd "$APP" && runuser -u "$RUN_USER" -- env HOME="$HOME_DIR" DNS_WEB_DATA_DIR="$DATA" "$@" )
}

# ---------------------------------------------------------------------------
# Other uses
# ---------------------------------------------------------------------------
case "${1:-}" in
--status)
    read_settings "$APP/deploy/server.conf"
    echo "Service : $(systemctl is-active drivenstyle 2>/dev/null || true)"
    echo "Version : $(answers 2>/dev/null || echo 'no answer')"
    echo "Address : https://$DOMAIN"
    echo "Disk    : $(df -h / | awk 'NR==2 {print $4 " free of " $2 " (" $5 " used)"}')"
    echo "Data    : $(du -sh "$DATA" 2>/dev/null | cut -f1)"
    echo "Backups : $(ls -1 "$BACKUPS"/drivenstyle-*.db.gz 2>/dev/null | wc -l) kept, newest: $(ls -1t "$BACKUPS"/drivenstyle-*.db.gz 2>/dev/null | head -1 | xargs -r basename)"
    exit 0 ;;

--make-backup)
    say "Making a fresh backup"
    runuser -u "$RUN_USER" -- /bin/bash "$APP/deploy/backup.sh"
    OWNER="${SUDO_USER:-root}"
    cp "$(ls -1t "$BACKUPS"/drivenstyle-*.db.gz | head -1)" /tmp/dns-backup.db.gz
    if [ -d "$DATA/daily/proofs" ]; then
        tar -czf /tmp/dns-proofs.tgz -C "$DATA/daily" proofs
    else
        tar -czf /tmp/dns-proofs.tgz -T /dev/null
    fi
    chown "$OWNER" /tmp/dns-backup.db.gz /tmp/dns-proofs.tgz
    chmod 600 /tmp/dns-backup.db.gz /tmp/dns-proofs.tgz
    echo "Ready to fetch."
    exit 0 ;;

--bring-across)
    SOURCE="${2:-}"; REPLACE="${3:-}"
    [ -f "$SOURCE" ] || die "database file not found: $SOURCE"
    say "Bringing the desktop database across"
    chown "$RUN_USER" "$SOURCE"
    systemctl stop drivenstyle
    OK=0
    as_tool "$VENV/bin/python" -m web.backend.bring_across --from "$SOURCE" $REPLACE || OK=$?
    rm -f "$SOURCE"
    systemctl start drivenstyle
    [ "$OK" = "0" ] || die "the copy was refused (see the message above). The tool runs as before."
    read_settings "$APP/deploy/server.conf"
    answers >/dev/null || die "the tool does not answer after the copy: sudo journalctl -u drivenstyle -n 50"
    echo "Done - the web tool now has the desktop data."
    exit 0 ;;
esac

# ---------------------------------------------------------------------------
# Install / update
# ---------------------------------------------------------------------------
RELEASE="${1:-}"
[ -d "$RELEASE/web/backend" ] || die "the new version's folder was not given (deploy.ps1 does this)."
[ -f "$RELEASE/web/frontend/dist/index.html" ] || die "the screens were not built (web/frontend/dist is missing)."
read_settings "$RELEASE/deploy/server.conf"

FIRST=0; [ -x "$VENV/bin/python" ] || FIRST=1

say "1. Checks"
FREE_MB=$(df --output=avail -m / | tail -1 | tr -d ' ')
echo "   Free disk: ${FREE_MB} MB"
if [ "$FIRST" = "1" ]; then
    [ "$FREE_MB" -ge "$NEEDED_MB" ] || die "only ${FREE_MB} MB free; a first install needs ${NEEDED_MB} MB."
    if ss -tln 2>/dev/null | grep -q "[:.]$PORT "; then
        die "port $PORT is already used by another program. Change PORT in deploy/server.conf."
    fi
else
    [ "$FREE_MB" -ge 300 ] || die "only ${FREE_MB} MB free on the server - too little to update safely."
fi

say "2. Programs the tool needs"
MISSING=""
for package in python3-venv libreoffice-calc fonts-crosextra-carlito locales; do
    dpkg -s "$package" >/dev/null 2>&1 || MISSING="$MISSING $package"
done
if [ -n "$MISSING" ]; then
    echo "   Installing:$MISSING"
    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1
    apt-get update -qq || warn "the package list could not be refreshed; trying with the present one."
    # shellcheck disable=SC2086
    apt-get install -y -qq --no-install-recommends $MISSING
else
    echo "   All there."
fi
if ! locale -a 2>/dev/null | grep -qi '^en_IN\.utf-\?8$'; then
    locale-gen en_IN.UTF-8 >/dev/null
fi

say "3. The tool's own user and folders"
id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$HOME_DIR" --shell /usr/sbin/nologin "$RUN_USER"
mkdir -p "$HOME_DIR" "$DATA" "$BACKUPS"
chown root:"$RUN_USER" "$HOME_DIR"; chmod 750 "$HOME_DIR"
chown "$RUN_USER":"$RUN_USER" "$DATA" "$BACKUPS"; chmod 750 "$DATA" "$BACKUPS"

say "4. The new version of the code"
rm -rf "$HOME_DIR/app.new" "$HOME_DIR"/app.failed.*     # leftovers of an earlier try
mkdir "$HOME_DIR/app.new"
cp -a "$RELEASE/." "$HOME_DIR/app.new/"
find "$HOME_DIR/app.new/deploy" -type f -exec sed -i 's/\r$//' {} +
chown -R root:"$RUN_USER" "$HOME_DIR/app.new"
chmod -R u=rwX,g=rX,o= "$HOME_DIR/app.new"

say "5. Python libraries"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check \
    -r "$HOME_DIR/app.new/web/backend/requirements.txt"
"$VENV/bin/python" -m compileall -q "$HOME_DIR/app.new/app" "$HOME_DIR/app.new/web" \
    "$HOME_DIR/app.new/payout_app" >/dev/null 2>&1 || true
chown -R root:"$RUN_USER" "$VENV" "$HOME_DIR/app.new"; chmod -R g+rX,o= "$VENV"

say "6. Settings and service"
umask 027
cat > "$ENV_FILE" <<SETTINGS
# Written by deploy/install.sh from deploy/server.conf - change it THERE.
DNS_WEB_DATA_DIR=$DATA
DNS_WEB_ADMINS=$ADMINS
DNS_WEB_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
DNS_WEB_HTTPS=1
HOME=$HOME_DIR
SETTINGS
chown root:"$RUN_USER" "$ENV_FILE"; chmod 640 "$ENV_FILE"
umask 022
sed "s/__PORT__/$PORT/g" "$HOME_DIR/app.new/deploy/drivenstyle.service" > "$UNIT"
systemctl daemon-reload
systemctl enable drivenstyle >/dev/null 2>&1

say "7. Swapping the new version in"
systemctl stop drivenstyle 2>/dev/null || true
rm -rf "$HOME_DIR/app.previous"
[ -d "$APP" ] && mv "$APP" "$HOME_DIR/app.previous"
mv "$HOME_DIR/app.new" "$APP"
systemctl start drivenstyle
if VERSION=$(answers); then
    echo "   The tool answers: version $VERSION"
else
    echo "   The new version does not answer. Its last messages:"
    journalctl -u drivenstyle -n 25 --no-pager 2>/dev/null || true
    if [ -d "$HOME_DIR/app.previous" ]; then
        systemctl stop drivenstyle 2>/dev/null || true
        mv "$APP" "$HOME_DIR/app.failed.$(date +%s)"
        mv "$HOME_DIR/app.previous" "$APP"
        systemctl start drivenstyle
        die "the previous version was put back and is running. Nothing else was changed."
    fi
    die "the tool did not start. nginx was not touched."
fi

say "8. The tool's site in nginx"
SITE="/etc/nginx/sites-available/$DOMAIN"
LINK="/etc/nginx/sites-enabled/$DOMAIN"
if [ -e "$SITE" ] || [ -e "$LINK" ]; then
    echo "   Already there - left as it is."
else
    nginx -t >/dev/null 2>&1 || die "nginx reports an error in the server's EXISTING sites (sudo nginx -t). Our site was not added; the tool itself runs."
    sed -e "s/__DOMAIN__/$DOMAIN/g" -e "s/__PORT__/$PORT/g" "$APP/deploy/nginx-site.conf" > "$SITE"
    ln -s "$SITE" "$LINK"
    if ! nginx -t >/dev/null 2>&1; then
        rm -f "$LINK" "$SITE"
        die "nginx did not accept our site file, so it was taken out again. The other sites are untouched."
    fi
    systemctl reload nginx
    echo "   Added and nginx reloaded."
fi

if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "   HTTPS certificate: already there."
else
    HERE=$(curl -s --max-time 8 https://checkip.amazonaws.com || true)
    POINTS=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}' || true)
    if [ -n "$HERE" ] && [ "$HERE" = "$POINTS" ]; then
        echo "   Getting the HTTPS certificate..."
        certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --no-eff-email \
            -m "$CERT_EMAIL" --redirect \
            || warn "the certificate was NOT issued (message above). Run deploy.ps1 again later; sign-in needs HTTPS."
    else
        warn "$DOMAIN points to '${POINTS:-nowhere}', but this server is '${HERE:-unknown}'."
        warn "Set the address to this server (DuckDNS), then run deploy.ps1 again for the HTTPS certificate."
    fi
fi

say "9. Nightly backup (02:00 Indian time)"
cat > /etc/cron.d/drivenstyle-backup <<CRON
# Drive N Style web tool: nightly copy of the database (deploy/backup.sh).
# 20:30 UTC = 02:00 in India.
30 20 * * * $RUN_USER /bin/bash $APP/deploy/backup.sh >> $BACKUPS/backup.log 2>&1
CRON
chmod 644 /etc/cron.d/drivenstyle-backup

say "DONE - version $VERSION is running"
echo "   Open: https://$DOMAIN"
[ "$FIRST" = "1" ] && echo "   First install: sign in as $ADMINS, then add the other people on the Users screen."
exit 0

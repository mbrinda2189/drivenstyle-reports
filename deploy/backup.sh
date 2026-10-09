#!/usr/bin/env bash
# backup.sh - The nightly copy of the tool's database (v0.29.0)
# =============================================================
#
# WHAT THIS DOES
# --------------
# Every night (02:00 Indian time) the server runs this by itself. It makes
# a safe copy of the database - masters, months read, the payout register,
# users, the audit log - while the tool keeps running, squeezes it (gzip)
# and keeps it in /opt/drivenstyle/backups/ as
#
#     drivenstyle-2026-10-09.db.gz
#
# Copies older than BACKUP_DAYS (deploy/server.conf, 14) are removed, so
# the folder cannot fill the server's disk.
#
# WHAT IT DOES NOT DO
#     * The copies stay on the SAME server. If the server itself is lost,
#       so are they - fetch a copy to the PC from time to time with
#       deploy\deploy.ps1 -Backup  (docs/deployment.md).
#     * Payment proofs and uploaded files are not copied nightly (they
#       never change once saved); "-Backup" fetches the proofs too.
#
# It runs as the tool's own user (drivenstyle), never as root.

set -euo pipefail

HOME_DIR=/opt/drivenstyle
DATA="$HOME_DIR/data"
BACKUPS="$HOME_DIR/backups"
KEEP=14
if [ -f "$HOME_DIR/app/deploy/server.conf" ]; then
    # shellcheck disable=SC1090
    . <(tr -d '\r' < "$HOME_DIR/app/deploy/server.conf")
    KEEP="${BACKUP_DAYS:-14}"
fi

DB="$DATA/drivenstyle.db"
[ -f "$DB" ] || { echo "$(date '+%F %T') no database yet - nothing to copy"; exit 0; }

mkdir -p "$BACKUPS"
TARGET="$BACKUPS/drivenstyle-$(date +%F).db"

# sqlite's own "backup" gives a complete, consistent copy even while
# someone is saving in the tool at the same moment (a plain file copy
# might not).
"$HOME_DIR/venv/bin/python" - "$DB" "$TARGET" <<'PY'
import sqlite3, sys
source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
check = target.execute("PRAGMA integrity_check").fetchone()[0]
target.close(); source.close()
if check != "ok":
    sys.exit(f"the copy did not pass its check: {check}")
PY
gzip -f "$TARGET"

# Keep the newest KEEP copies, remove the rest.
ls -1t "$BACKUPS"/drivenstyle-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

echo "$(date '+%F %T') backup made: $(basename "$TARGET").gz ($(du -h "$TARGET.gz" | cut -f1))"

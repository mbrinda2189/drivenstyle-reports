# Drive N Style web tool - on the server

How the web tool is put on the client's server, kept up to date, backed up
and, if ever needed, taken off again. Written for Brinda; every command is
typed on **her PC**, in PowerShell, from the project folder
(`C:\Official\Coding\Personal Coding Projects\drivenstyle-reports`).

## The facts

| | |
|---|---|
| Web address | `https://drivenstyle.duckdns.org` (free DuckDNS name, account `automation.drivenstyle@gmail.com`) |
| Server | `ubuntu@35.154.161.180` - Ubuntu 22.04, the client's AWS, **shared with other sites** (theprintapp.com and others) |
| Key file | `C:\Official\Coding\Personal Coding Projects\key\Printapp_KEY.pem` - outside the project, never committed |
| Web server | nginx (already there); the tool adds ONE site file |
| Sign-in | Google, client ID in `deploy/server.conf`; test sign-in is off |
| Settings | `deploy/server.conf` (address, port, client ID, admins, backup days) |

## What is where on the server

| Folder / file | What |
|---|---|
| `/opt/drivenstyle/app` | the code of the running version |
| `/opt/drivenstyle/app.previous` | the version before it |
| `/opt/drivenstyle/venv` | the Python libraries |
| `/opt/drivenstyle/data` | **the data**: database, uploaded files, reports, payment proofs. An update never touches it. |
| `/opt/drivenstyle/backups` | nightly copies of the database (14 kept) |
| `/etc/drivenstyle.env` | the settings, written from `deploy/server.conf` |
| `/etc/systemd/system/drivenstyle.service` | keeps the tool running, as its own user `drivenstyle` |
| `/etc/nginx/sites-available/drivenstyle.duckdns.org` | the tool's site in nginx |
| `/etc/cron.d/drivenstyle-backup` | the nightly backup, 02:00 Indian time |

The tool listens inside the server only (port 8010). The outside world
reaches it through nginx, over HTTPS.

## Before the first install

1. **The address points to the server.** On duckdns.org (signed in as
   `automation.drivenstyle@gmail.com`) the `drivenstyle` row shows
   `35.154.161.180`. Without this the HTTPS certificate cannot be issued.
2. **The server's address is fixed** (an "Elastic IP" in AWS) - ask the
   client's IT. If it is not, it changes when the server restarts.
3. **Ports 80 and 443 are open** in the AWS firewall (they are: the
   server's other sites use them).
4. **The client's IT knows the day and time.** Their live sites are on the
   same server.
5. Everything is committed (`git status` shows nothing to commit): only
   committed work is sent.

## Install, and every later update - the same command

```
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1
```

It builds the screens, packs the last commit, copies it to the server and
runs `deploy/install.sh` there. That script prints nine numbered steps and
ends with `DONE - version X is running`. The first run takes about five
minutes (it installs LibreOffice, about 700 MB); later runs under a minute,
during which the tool is off for a few seconds.

What it will not do, because the server is shared:

- upgrade or restart any other program, or touch MySQL, PHP or Apache;
- edit another site's nginx file. nginx is checked before and after the
  tool's one file is added; if the check fails the file is taken out
  again. nginx is only reloaded, never stopped.

If a new version does not start, the script **puts the previous version
back by itself** and says so. The data is not affected either way.

If it says the HTTPS certificate was not issued (usually: the address did
not point to the server yet), fix that and run the same command again.

## After the first install

1. Open `https://drivenstyle.duckdns.org` and sign in as
   `automation.drivenstyle@gmail.com` (the first admin).
2. Bring the desktop tool's data across, once:
   ```
   powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -Database desktop
   ```
   ("desktop" = the desktop tool's database on this PC; or give a file's
   path.) If the web tool already has masters it refuses - add `-Replace`
   to allow it; the web tool's present database is kept as a backup file
   first, and its users stay.
3. On the **Users** screen add the staff. While Google's sign-in is in
   "Testing", each person must ALSO be a "test user" in Google Cloud
   (Google Auth Platform -> Audience).
4. Check a month: Monthly reports -> Generate for September 2026 should
   give the baseline figures (sales 13,80,298.18; gross profit 7,27,469.55).
5. Open it from an **office PC**. If the office's IT filter blocks
   `duckdns.org`, the tool needs a bought domain (below).

## Publishing the Google sign-in (so no "test users" are needed)

Google Cloud -> Google Auth Platform -> **Branding**:

- Application home page: `https://drivenstyle.duckdns.org`
- Privacy policy: `https://drivenstyle.duckdns.org/privacy`
- Authorised domain: `duckdns.org`

Save, then **Audience -> Publish app**. The tool asks Google for the name
and e-mail only, so no review by Google is expected. The text of the
privacy page is in `web/backend/privacy.py`.

## Looking and backing up

```
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -Status
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -Backup
```

- **-Status**: running or not, version, free disk, how many backups.
- **-Backup**: makes a fresh backup and fetches it to
  `data\server-backups\` on this PC: the database
  (`drivenstyle-<date>.db.gz`) and the payment proofs (`proofs-<date>.tgz`).

The nightly backups stay on the **same server** as the data: they protect
against a mistake or a damaged database, not against losing the server.
**Run -Backup once a week** (and before anything risky) so a copy exists
elsewhere. `data\` is never committed to Git.

**To put a backup back** (only with the client's agreement - it replaces
what is on the server): unpack the `.db.gz` (7-Zip) and run

```
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -Database "C:\path\drivenstyle-2026-10-09.db" -Replace
```

Note that this keeps the server's present list of users.

## When something is wrong

| What you see | What to do |
|---|---|
| The page does not open at all | `-Status`. If "Service : inactive": `ssh -i <key> ubuntu@35.154.161.180 "sudo systemctl restart drivenstyle"` |
| "502 Bad Gateway" | the tool is stopped or starting; as above |
| Browser warns about the certificate | run `deploy.ps1` again (it retries the certificate); it renews by itself every 60-90 days |
| Google: "Access blocked" / "not verified" | the person is not a test user, or the address is not among the client ID's "Authorised JavaScript origins" |
| "Your address is not on the list" | add the person on the Users screen |
| PDF of the monthly report fails | LibreOffice: `ssh ... "which soffice"`; run `deploy.ps1` again |
| The tool's messages | `ssh -i <key> ubuntu@35.154.161.180 "sudo journalctl -u drivenstyle -n 50 --no-pager"` |
| Go back to the version before | `ssh ... "cd /opt/drivenstyle && sudo systemctl stop drivenstyle && sudo mv app app.bad && sudo mv app.previous app && sudo systemctl start drivenstyle"` |

## Changing the web address later (e.g. to reports.drivenstyle.in)

1. Point the new name to the server (an "A" record: `35.154.161.180`).
2. Change `DOMAIN=` in `deploy/server.conf`, commit.
3. In Google Cloud add `https://<new name>` to the client ID's
   "Authorised JavaScript origins" (and to Branding).
4. Run `deploy.ps1`. It adds a site and a certificate for the new name;
   the old name keeps working until its site file is removed.

No data is touched.

## Taking the tool off the server

Fetch a backup first (`-Backup`). Then, on the server:

```
sudo systemctl disable --now drivenstyle
sudo rm /etc/nginx/sites-enabled/drivenstyle.duckdns.org /etc/nginx/sites-available/drivenstyle.duckdns.org
sudo nginx -t && sudo systemctl reload nginx
sudo certbot delete --cert-name drivenstyle.duckdns.org
sudo rm /etc/systemd/system/drivenstyle.service /etc/cron.d/drivenstyle-backup /etc/drivenstyle.env
sudo rm -rf /opt/drivenstyle          # THE DATA GOES WITH THIS
sudo userdel drivenstyle
```

LibreOffice may stay, or: `sudo apt-get remove libreoffice-calc libreoffice-core`.

## Told to the client's IT (not the tool's to fix)

- Both servers seen have their disk about 80% full.
- MySQL listens to the outside (port 3306); the AWS firewall should block it.
- The server is shared with other firms' sites: whoever holds its key can
  read Drive N Style's data. A small server of its own would keep it apart.

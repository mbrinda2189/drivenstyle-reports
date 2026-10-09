# Drive N Style - web tool (`web/`)

**Status: v0.23.0 - step 2 done: the server starts, people sign in with
roles, and the frame with the two tabs is there. Masters, reports and
payouts are not built yet (their screens say "Comes in step N").**

## Why

The client's IT does not allow the Windows programs (the monthly reports
tool and the daily payout app) to run on the office PCs. Both therefore
move into ONE web tool, opened in the browser and hosted on the client's
own AWS account (Brinda, 09-10-2026). The desktop programs in `app/` and
`payout_app/` stay in the repository as they are, as the reference.

## The one rule: the figures do not change

The calculations are NOT rewritten. The web tool imports the same Python
code the desktop tool uses:

| Used as it is | What it does |
|---|---|
| `app/data/` | database, masters with dated rates, Zoho export reader, invoice PDF reader, matching, Scan review fixes, monthly inputs, audit log |
| `app/reports/` | the month's figures, the Excel workbook, the PDF version, the delivery (RTO) reports, the trend |
| `payout_app/engine.py` | invoice PDFs -> labour / spot incentive / internal team payout lines |
| `payout_app/slip.py` | the payout slip |

There is no `core/` folder: `app/data` and `app/reports` ARE the shared
rules (agreed 05-10-2026, confirmed again 09-10-2026). September 2026 is
saved as the "before" picture (`python scripts/snapshot_month.py 2026 9`)
and `tests/test_baseline.py` fails if any figure moves.

## Folders

```
web/
├── backend/    FastAPI (Python): sign-in, uploads, the database, and the
│               calls into app/data, app/reports and payout_app/engine
└── frontend/   React: the screens, in the same blue theme
```

## Running it on your PC

Once:

```powershell
pip install -r web/backend/requirements.txt
cd web\frontend
npm install
cd ..\..
```

Every time, in TWO PowerShell windows, both in the project folder:

```powershell
# window 1 - the server
$env:DNS_WEB_DEV_LOGIN = "1"
python -m uvicorn web.backend.main:app --port 8000

# window 2 - the screens
cd web\frontend
npm run dev
```

Open http://localhost:5173 and use the amber **Test sign-in** box with
`automation.drivenstyle@gmail.com` (the first admin). Add your own address
on the Users screen.

The web tool keeps its own database in `data\web\drivenstyle.db` (not in
Git). It starts EMPTY and does not touch the desktop tool's database.

`DNS_WEB_DEV_LOGIN` lets anyone who knows an admin's e-mail address in
without a password. It is for your PC only - **never set it on the AWS
server.**

## Google sign-in (to do once, about five minutes)

1. https://console.cloud.google.com - the same project as the payout app.
2. APIs & Services > Credentials > Create credentials > OAuth client ID.
3. Application type: **Web application**. Name: Drive N Style web tool.
4. Authorised JavaScript origins: add `http://localhost:5173` and
   `http://localhost` (later also the tool's real https address).
   Leave "Authorised redirect URIs" empty.
5. Create, and copy the **Client ID** (ends with
   `.apps.googleusercontent.com`). It is not a secret; there is no file to
   download and nothing to commit.
6. In window 1, before starting the server:
   `$env:DNS_WEB_GOOGLE_CLIENT_ID = "<the client ID>"`

The "Sign in with Google" button then appears. While the Google project is
in **Testing**, only the accounts listed under OAuth consent screen > Test
users can sign in - add them there, or publish the app.

## Settings (environment variables)

| Setting | Meaning | Default |
|---|---|---|
| `DNS_WEB_DATA_DIR` | Folder of the web tool's database and secret key | `data/web/` |
| `DNS_WEB_ADMINS` | Addresses made admin when the list has no active admin (comma separated) | `automation.drivenstyle@gmail.com` |
| `DNS_WEB_GOOGLE_CLIENT_ID` | Google "Web application" client ID | none - no Google button |
| `DNS_WEB_DEV_LOGIN` | `1` = test sign-in without Google (your PC only) | off |
| `DNS_WEB_HTTPS` | `1` on the real server: cookie over HTTPS only | off |
| `DNS_WEB_SESSION_HOURS` | Hours a sign-in lasts | 12 |
| `DNS_WEB_SECRET` | Key that signs the sign-in cookie | made once, kept in the data folder |

## Roles

| | Daily payouts | Monthly reports | Masters, Audit log, Users |
|---|---|---|---|
| Admin | yes | yes | yes |
| Staff | yes | no | no |

The server checks the role at every request; the screens only hide what
the server would refuse anyway. The last active admin cannot be removed,
made inactive or made staff. Every change to the users list is in the
audit log with the e-mail of the admin who made it.

## Decisions (Brinda, 09-10-2026)

| Subject | Decision |
|---|---|
| Hosting | One small server on the client's AWS, Mumbai region (ap-south-1), HTTPS on a web address of theirs. Brinda deploys; credentials awaited from the client. |
| Screens | React + TypeScript instead of PySide6. One screen with two tabs, Daily payouts and Monthly reports, and a Shared (admin) section under both - layout approved on the mockup. |
| Database | SQLite on the server (the data code and its tests are written for it), nightly backup to S3. Not PostgreSQL. |
| Masters | In the database, edited on the Masters screen, Excel import / export, dated rates. No masters Google Sheet. |
| Payout register | Database tables with Excel export. No register Google Sheet; the same rules (post once, In review, Re-issued, Cancelled, payment and proof). |
| Payment proofs | S3 bucket on the client's AWS. No Google Drive folder. |
| Sign-in | Google sign-in with roles: admin and staff (staff see the daily payouts only). First admin: automation.drivenstyle@gmail.com. Built so that user name + password can replace it if IT blocks Google. |
| Invoices | Uploaded in the browser. Monthly tool: Zoho invoice export, payments export, delivery (RTO) list. Daily payouts: invoice PDFs; an invoice already posted is skipped. |
| PDF of the reports | LibreOffice on the server (Excel cannot run there). Its pages must be compared with the present PDF before it is accepted. |
| Audit log | Records the signed-in person's e-mail instead of the Windows user name. |

Unchanged from the payout plan: no technician, the spot incentive rule, no
back-posting, no daily rounding of incentive, and every control.

## Build order

| Step | Version | What |
|---|---|---|
| 1 | v0.22.0 | **Done.** Tests as the baseline, September figures saved, these folders, the plan written down |
| 2 | v0.23.0 | **Done.** Server (FastAPI), users list with roles in the database, Google sign-in + test sign-in, React frame with the two tabs, Users screen |
| 3 | | Masters: screens, Excel import, dated rates, checks, audit log |
| 4 | | Monthly tool: upload and read, Scan review, Monthly inputs, generate workbook and PDF, History |
| 5 | | Daily payouts: scan and review, posting to the register, mark paid with proof, audit log |
| 6 | | Payout slip, summary, and the month check against the monthly Labour and Spot incentive reports |
| 7 | | Deployment on the client's AWS: HTTPS, backups, deployment guide |

Each step is confirmed with Brinda before it is coded, and is one version.

## Still open

- AWS credentials from the client: an IAM user for Brinda (not the root
  login) allowed to create one small server and one S3 bucket.
- A web address for the tool (a sub-domain of the client's site).
- The Google "Web application" client ID (steps above) - Brinda.
- Whether the client's IT limits the websites staff can open, and whether
  Google sign-in is allowed there.

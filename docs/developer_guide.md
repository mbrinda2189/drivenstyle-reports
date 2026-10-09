# Drive N Style tool - developer guide

This guide is for a developer who takes over the project and has **never
seen it before**. It assumes little: every tool is named, every command is
written out, and every folder and file is explained. Read parts 1 to 4
once, in order. After that, use the rest as a reference.

Other documents, and what each is for:

| Document | Read it when |
|---|---|
| `docs/developer_guide.md` (this one) | you are new, or you forgot how something is done |
| `CLAUDE.md` | before changing any calculation: it holds **every business rule the client agreed**, with dates |
| `docs/deployment.md` | you put a version on the server, take a backup, or the site is down |
| `web/README.md` | you want the history of how the web tool was planned and built |
| `CHANGELOG.md` | you want to know what changed in which version |
| `README.md` | the short description of the whole project |
| `docs/payout_app_staff_guide.md` | the old desktop payout app (no longer in use) |

---

## Part 1 - What this project is

### 1.1 The people

| Who | Role |
|---|---|
| **Drive N Style / Carkrafts** | the client: a car accessories and detailing business in Coimbatore. Their invoices are made in **Zoho Books**. |
| **Brinda** (Brinda & Associates, Chartered Accountants) | owns this project. She prepares the client's monthly management reports. Every change is agreed with her first. |
| The client's staff | use the tool every day in a browser to work out and record labour and incentive payouts. |
| The client's IT vendor | owns the AWS server the tool runs on. That server also runs **their other live websites**. |

### 1.2 What the tool does

It does two jobs, shown as two tabs on one screen:

1. **Daily payouts.** Staff upload the day's invoice PDFs. The tool works
   out, for each invoice, how much **labour** is owed to the people who
   fitted the items and how much **incentive** is owed to the sales
   executive. Staff then mark each amount as paid, with a reference and a
   photo of the proof.
2. **Monthly reports.** Once a month an administrator uploads three files
   exported from Zoho (invoices, payments, and the dealership's delivery
   list). The tool checks every line against the **masters** (price lists),
   lets unclear lines be fixed, and writes one Excel workbook of management
   reports plus a PDF.

Both jobs use the **same masters and the same calculation rules**, so the
daily figures and the monthly figures agree.

### 1.3 Three programs live in this one repository

This matters, because two of them are old and must be left alone.

| Program | Folder | Status |
|---|---|---|
| Desktop monthly reports tool (Windows, PySide6) | `app/pages`, `app/widgets`, `main.py` | **Frozen.** Kept for reference. The client's IT blocked it, which is why the web tool exists. |
| Desktop daily payout app (Windows, Google Sheets) | `payout_app/` screens, `payout_main.py` | **Frozen.** Same reason. |
| **Web tool** (browser) | `web/` | **Live.** This is what you work on. |

The important twist: the web tool **does not have its own copy of the
calculations**. It imports them from the desktop code:

- `app/data/` - reading files, the database, the masters
- `app/reports/` - every figure and the Excel / PDF output
- `payout_app/engine.py`, `register.py`, `slip.py`, `service.py` - the daily payout rules

So "frozen" means: do not change the desktop **screens**. The folders
`app/data`, `app/reports` and the four `payout_app` files above are very
much alive - the web tool runs on them.

### 1.4 The technology, in one table

| Part | Technology | Why |
|---|---|---|
| Server program ("backend") | Python 3.10, **FastAPI**, run by **uvicorn** | answers the browser's requests |
| Screens ("frontend") | **React 18** with **TypeScript**, built by **Vite** | what the user sees |
| Database | **SQLite** - one file, `drivenstyle.db` | small, no separate database server to look after |
| Sign-in | Google ("Sign in with Google") | no passwords to store |
| Excel files | `openpyxl` | reading and writing .xlsx |
| Invoice PDFs | `pdfplumber` | reading the words on a PDF |
| PDF of the reports | **LibreOffice** on the server (Excel on Windows) | converts the workbook to PDF |
| Web server in front | **nginx** (already on the server) | HTTPS, passes requests to the tool |
| Tests | `pytest` | about 290 automatic checks |

---

## Part 2 - Words you will meet

### 2.1 Technical words

| Word | Meaning here |
|---|---|
| **Repository (repo)** | the project folder, with its whole history, kept by Git |
| **Commit** | one saved step in that history, with a message |
| **Tag** | a name given to a commit, e.g. `v0.29.0`. Every version has one. |
| **Push** | send your commits from your PC to GitHub |
| **Virtual environment (`.venv`)** | a private folder of Python libraries for this project, so they do not mix with other projects |
| **Backend / server** | the Python program that holds the data and does the work |
| **Frontend / screens** | the React program that runs in the user's browser |
| **API** | the list of addresses (`/api/...`) the screens call on the server |
| **Endpoint / route** | one such address |
| **Build** | turning the TypeScript source into the plain files a browser can run (`web/frontend/dist`) |
| **Deploy** | putting a version on the real server |
| **Migration** | a step that changes the shape of the database (a new table or column) |
| **Environment variable** | a named setting given to a program from outside, e.g. `DNS_WEB_DATA_DIR` |
| **Service** | a program Linux keeps running in the background (here: `drivenstyle`) |

### 2.2 Business words

| Word | Meaning here |
|---|---|
| **Masters** | the reference lists: Products, Sales executives, Cars, Incentives, Packages |
| **Dated rate** | a price / cost / labour charge with an "effective from" date. Old invoices keep using the rate of their own date. |
| **Labour** | what Drive N Style pays a fitter for fitting an item. Only products marked "Labour involved" have it. |
| **Spot incentive** | what a sales executive earns on a sale |
| **Internal team incentive** | a fixed amount per car PPF job, paid to the internal team as well |
| **Scan review** | the screen where invoice lines the tool could not match to a master are fixed by a person |
| **Saved match** | a fix remembered for next time (e.g. "this spelling means that product") |
| **Payout line** | one amount owed to one person for one invoice |
| **Payout register** | the list of all payout lines and whether each is paid |
| **Payout slip** | a printable list of who is to be paid how much |
| **RTO list / delivery list** | the car dealership's monthly list of cars delivered; used for the new-car reports |
| **Baseline** | the September 2026 figures, saved as the "correct answer". A test fails if any of them moves. |
| **Audit log** | a record of every change, who made it and when. It can never be edited or deleted. |

---

## Part 3 - Where everything is

Nothing in this table is a password. **Passwords and key files are never
written in this repository** - ask Brinda for access.

| Thing | Where |
|---|---|
| Code | GitHub: `mbrinda2189/drivenstyle-reports`, branch `main` |
| Live tool | `https://drivenstyle.duckdns.org` |
| Server | `ubuntu@35.154.161.180` (AWS Mumbai, Ubuntu 22.04, fixed "Elastic" IP). Shared with the IT vendor's other sites. |
| Server key file | on Brinda's PC, **outside** the project: `C:\Official\Coding\Personal Coding Projects\key\Printapp_KEY.pem` |
| Web address (DNS) | duckdns.org, account `automation.drivenstyle@gmail.com`, name `drivenstyle` |
| Google sign-in set-up | Google Cloud Console, same account, "Google Auth Platform" |
| Google client ID | `deploy/server.conf` (public by design) |
| First administrator of the tool | `automation.drivenstyle@gmail.com` |
| Tool's data on the server | `/opt/drivenstyle/data` |
| Project folder on Brinda's PC | `C:\Official\Coding\Personal Coding Projects\drivenstyle-reports` |
| Client's sample files | `data\Samples\` inside the project - **never committed** |

---

## Part 4 - Setting up your PC, step by step

These steps are for Windows 10 or 11. Do them once.

### 4.1 Install four programs

1. **Git** - https://git-scm.com/download/win. Accept every default.
2. **Python 3.10, 3.11 or 3.12** - https://www.python.org/downloads/.
   On the first screen of the installer **tick "Add python.exe to PATH"**.
   (The server runs 3.10. Any of the three works on your PC, but see the
   rule in 12.6 about not using newer Python features.)
3. **Node.js LTS** - https://nodejs.org. Accept every default. It is only
   needed to build the screens.
4. **Visual Studio Code** - https://code.visualstudio.com. Any editor will do.

Check them. Open **PowerShell** (Start menu, type "PowerShell") and type
each line, pressing Enter after each. Each should print a version number:

```powershell
git --version
python --version
node --version
npm --version
```

If one says "not recognized", close PowerShell, open it again, and retry.
If it still fails, reinstall that program.

### 4.2 Get the code

Brinda must first add your GitHub account to the repository.

```powershell
cd "C:\Official\Coding\Personal Coding Projects"
git clone https://github.com/mbrinda2189/drivenstyle-reports.git
cd drivenstyle-reports
```

From now on, **every command in this guide is typed in this folder**
unless it says otherwise.

### 4.3 Make the Python environment

```powershell
python -m venv .venv
.venv\Scripts\activate
```

After the second line your prompt starts with `(.venv)`. That means the
project's own Python is in use. **You must run `.venv\Scripts\activate`
every time you open a new PowerShell window.**

If PowerShell refuses to run the script ("running scripts is disabled"),
run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Now install the libraries:

```powershell
pip install -r requirements-dev.txt
pip install -r web/backend/requirements.txt
```

The first file is for the desktop programs and the tests; the second is
for the web tool's server.

### 4.4 Install the screens' libraries

```powershell
cd web\frontend
npm install
cd ..\..
```

This creates `web\frontend\node_modules` (large; never committed).

### 4.5 Run the tests

```powershell
python -m pytest
```

It takes about half a minute and should end with something like
`285 passed, 5 skipped`. **Zero failed** is the only acceptable result.
If a test fails on a fresh copy, stop and ask - do not start work on top
of a failing copy.

### 4.6 Run the web tool on your PC

You need **two** PowerShell windows, both in the project folder, both
with `.venv` activated.

**Window 1 - the server:**

```powershell
.venv\Scripts\activate
$env:DNS_WEB_DEV_LOGIN = "1"
python -m uvicorn web.backend.main:app --port 8000 --reload
```

- `DNS_WEB_DEV_LOGIN = "1"` switches on the **test sign-in**, so you do
  not need Google on your PC.
- `--reload` restarts the server by itself when you save a Python file.
- Leave this window open. To stop the server press `Ctrl+C`.

**Window 2 - the screens:**

```powershell
cd web\frontend
npm run dev
```

It prints an address, `http://localhost:5173`. Open it in a browser. In
the amber **Test sign-in** box type `automation.drivenstyle@gmail.com`
and sign in. You are the administrator of an **empty** tool.

How the two windows work together: the browser talks to window 2 (port
5173). Window 2 passes every address starting with `/api` on to window 1
(port 8000). This is set in `web/frontend/vite.config.ts`.

### 4.7 Put some data in your local copy

Your local tool keeps its data in `data\web\` inside the project (never
committed). To start with real-looking data, ask Brinda for a copy of a
database file, stop the server (`Ctrl+C` in window 1) and run:

```powershell
python -m web.backend.bring_across --from "C:\path\to\drivenstyle.db"
```

Start the server again. You now have the masters and the months of that
copy. **This is client data: keep it on your PC, never commit it, never
send it anywhere.**

---

## Part 5 - The folder map

Every file that matters, with one line each. Numbers in brackets are
rough line counts, to show you where the weight is.

### 5.1 Top level

| Path | What |
|---|---|
| `app/` | the desktop monthly tool; **its `data` and `reports` folders are the shared engine** |
| `payout_app/` | the desktop daily payout app; four of its files are shared engine |
| `web/` | **the web tool** |
| `deploy/` | the files that put the web tool on the server |
| `tests/` | the automatic tests |
| `scripts/` | three helper commands |
| `docs/` | the guides |
| `data/` | local data. **Ignored by Git.** Holds client files - never commit. |
| `output/`, `build/`, `dist/` | things programs produce. Ignored by Git. |
| `main.py`, `payout_main.py` | start the two desktop programs |
| `requirements.txt`, `requirements-dev.txt` | Python libraries of the desktop programs / plus test tools |
| `.gitignore` | what Git must never store |
| `.gitattributes` | keeps the server files in Unix line ends |
| `README.md`, `CHANGELOG.md`, `CLAUDE.md` | see the table at the top |

### 5.2 `app/data/` - storing and reading (no screens)

| File | What it does |
|---|---|
| `database.py` (645) | creates the SQLite database and upgrades it step by step (`SCHEMA_VERSION`, `_MIGRATIONS`) |
| `paths.py` | where the desktop tool keeps its database |
| `master_defs.py` (359) | **the single description of every master**: its fields, types and labels. Screens, import and export are all driven from here. |
| `masters_repo.py` (956) | read and save the masters, with dated rates and the audit log |
| `users_repo.py` (186) | who may sign in to the web tool, and as what role |
| `excel_io.py` (456) | read the client's master sheets; export masters to Excel |
| `invoice_export.py` (347) | read Zoho's invoice export (`Invoice.csv` / `.xlsx`) |
| `invoice_reader.py` (498) | read **one invoice PDF** (used by the daily payouts) |
| `invoices_repo.py` (1052) | store invoices, match them to the masters, everything behind Scan review |
| `inputs_repo.py` (251) | the monthly inputs and the history of generated reports |
| `payments_io.py` | read Zoho's "Payments Received" export |
| `rto_list.py` (206) | read the dealership's delivery (RTO) list |

### 5.3 `app/reports/` - the figures and the output (no screens)

| File | What it does |
|---|---|
| `data.py` (534) | **every figure the reports need for one month** (`build_month`). The heart of the calculations. |
| `packages.py` | recognises a package sale on an invoice |
| `workbook.py` (1065) | writes the monthly Excel workbook |
| `rto_reports.py` (588) | the new-car reports and the executive summary |
| `trend.py` (250) | month-on-month trend |
| `pdf_book.py` (767) | lays out the PDF version of the reports |
| `pdf_export.py` (193) | turns a workbook into a PDF (LibreOffice on Linux, Excel on Windows) |
| `generate.py` (173) | builds a month's workbook in one call |
| `issues_export.py` | Scan review issues as an Excel file |
| `snapshot.py` (166) | a month's figures as plain numbers - used by the baseline test |

### 5.4 `payout_app/` - the shared daily-payout rules

| File | Used by the web tool? | What it does |
|---|---|---|
| `engine.py` (455) | **yes** | from invoice PDFs to labour and incentive payout lines |
| `register.py` (601) | **yes** | the layout of the payout register and the plan of what to post |
| `slip.py` (124) | **yes** | builds the payout slip |
| `service.py` (706) | partly (small helpers such as `proof_name`) | the desktop app's step-by-step actions |
| `google_api.py`, `masters_sheet.py`, `settings.py`, `masters_cli.py`, `payout_cli.py`, `__main__.py` | no | the Google Sheets side of the old desktop app |

### 5.5 `web/backend/` - the server

| File | What it does |
|---|---|
| `main.py` (295) | **start here.** Builds the application: sign-in, roles, users, and plugs in every other file. Also serves the built screens. |
| `config.py` (90) | reads the settings (environment variables) |
| `security.py` (84) | checks Google's answer; makes and reads the sign-in cookie |
| `masters_api.py` (263) | addresses for the Masters screen and the Audit log |
| `imports_api.py` (344) | masters from and to Excel |
| `monthly_api.py` (593) | the whole monthly reports tool (administrators only) |
| `payout_store.py` (431) | the payout register, kept in the database |
| `daily_api.py` (394) | addresses for the daily payouts |
| `daily_reports.py` (279) | payout slip, summary, month check, Excel export |
| `privacy.py` (90) | the public privacy page at `/privacy` |
| `bring_across.py` (133) | command that copies a desktop database into the web tool |
| `requirements.txt` | the server's Python libraries |

### 5.6 `web/frontend/` - the screens

| File | What it does |
|---|---|
| `index.html` | the one HTML page; React fills it |
| `package.json` | the libraries and the commands (`npm run dev`, `npm run build`) |
| `vite.config.ts` | build settings; passes `/api` to the server during development |
| `src/main.tsx` | starts React |
| `src/App.tsx` (105) | the list of pages and their addresses; sends you to Sign-in if you are not signed in |
| `src/Shell.tsx` (130) | the frame: the two top tabs and the side menu |
| `src/api.ts` (552) | **every call to the server is a function here**, with its types. No page calls `fetch` itself. |
| `src/month.tsx` | the month chooser shared by the monthly pages |
| `src/theme.css` (271) | all colours and styles |
| `src/pages/SignIn.tsx` | sign-in |
| `src/pages/Users.tsx` | who may sign in (admin) |
| `src/pages/Masters.tsx` (512) | the five masters |
| `src/pages/ImportDialog.tsx` | import masters from Excel |
| `src/pages/AuditLog.tsx` | the audit log (admin) |
| `src/pages/Generate.tsx` | monthly: upload files, read invoices, generate |
| `src/pages/ScanReview.tsx` | monthly: fix unclear lines |
| `src/pages/MonthlyInputs.tsx` | monthly: costs typed by hand |
| `src/pages/History.tsx` | monthly: reports made so far |
| `src/pages/DailyScan.tsx` | daily: upload PDFs and scan |
| `src/pages/DailyReview.tsx` | daily: fix unclear invoices |
| `src/pages/Payouts.tsx` | daily: mark paid, hold, reopen |
| `src/pages/DailySummary.tsx` | daily: slip, summary, month check |
| `src/pages/DailyHistory.tsx` | daily: the log |

### 5.7 `deploy/`

| File | Runs where | What it does |
|---|---|---|
| `deploy.ps1` | your PC | the one command: build, pack, copy, install. Also `-Status`, `-Backup`, `-Database`. |
| `install.sh` | the server | installs or updates the tool; puts the old version back if the new one does not start |
| `backup.sh` | the server, nightly | copies the database |
| `server.conf` | read by both | the address, port, Google client ID, admins |
| `nginx-site.conf` | template | the tool's site in nginx |
| `drivenstyle.service` | template | keeps the tool running |

### 5.8 `tests/`

One file per area. The names say what they cover, for example
`test_web_daily.py` = the daily payouts in the web tool,
`test_baseline.py` = September's figures must not move,
`test_deploy.py` = the server files stay safe. `fakes.py` holds stand-ins
for Google; `conftest.py` is shared set-up.

---

## Part 6 - How the web tool works

### 6.1 What happens when someone clicks a button

```
 Browser (React screens)
        |   1. the page calls a function in src/api.ts
        |   2. api.ts sends e.g.  POST /api/daily/pay   with the sign-in cookie
        v
 nginx on the server (HTTPS, port 443)
        |   3. passes it to the tool, inside the server only
        v
 uvicorn + FastAPI (127.0.0.1:8010)        web/backend/main.py
        |   4. is the request allowed?  (cookie -> user -> role, special header)
        |   5. the matching function runs, e.g. in daily_api.py
        v
 the shared engine                         app/data, app/reports, payout_app
        |   6. reads / writes
        v
 SQLite file                               /opt/drivenstyle/data/drivenstyle.db
        |
        v   7. the answer goes back as JSON; the page shows it
```

### 6.2 Sign-in

1. The Sign-in page shows Google's button. Google gives the browser a
   signed note saying "this person is name@gmail.com".
2. The page sends that note to `POST /api/auth/google`.
3. `security.verify_google` checks the note really came from Google and
   was meant for **our** client ID.
4. The server looks the e-mail up in the `users` table. Not there, or
   switched off: refused ("not on the list").
5. If accepted, the server sets a **cookie** - a signed ticket holding the
   user's number, valid for 12 hours. The browser sends it with every
   later request. JavaScript cannot read it (`HttpOnly`).

There is no password anywhere. Being on Google's side proves who you are;
being in the `users` table decides whether you may enter.

**Test sign-in** (`POST /api/auth/dev`) lets you type an e-mail without
Google. It exists only when `DNS_WEB_DEV_LOGIN=1`. It is for developers'
PCs. **It must never be switched on on the server** - anyone who knew an
administrator's e-mail could get in. `tests/test_deploy.py` fails if a
server file ever sets it.

### 6.3 Roles

| | Staff | Admin |
|---|---|---|
| Daily payouts (scan, review, pay, hold, reopen, summary, history) | yes | yes |
| Masters (see, add, change, import, export) | yes | yes |
| Remove products that are not in Zoho's list (during import) | no | yes |
| Monthly reports (all of it) | no | yes |
| Audit log | no | yes |
| Users | no | yes |
| Change the payout start date, clear the payout register | no | yes |

In the code this is two small functions in `main.py`: `current_user`
(any signed-in person) and `admin` (administrators only). Every address
names one of them, like this:

```python
@api.get("/api/users")
def list_users(user: dict = Depends(admin)):      # admin only
    ...
```

**The screens hiding a menu item is not security.** The check that counts
is always the one on the server.

### 6.4 The special header

Every request that changes something (anything except `GET`) must carry
the header `X-DNS-Request`. `api.ts` adds it automatically. Another
website cannot add it, which stops a class of attack called CSRF. If you
ever call the server from somewhere other than `api.ts` and get
"This request did not come from the tool's own screens", this is why.

### 6.5 The database connection

Each request opens the database, uses it, and closes it
(`connection()` in `main.py`). Nothing is kept open between requests.
Always open it **inside** the endpoint function with
`with connection() as conn:` - copy the pattern from any existing address.

### 6.6 How the screens reach the browser

On the server there is no separate program for the screens. `npm run build`
writes plain files to `web/frontend/dist`; the last address in `main.py`
(`/{path:path}`) sends those files. Any address that is not a file gets
`index.html`, and React then shows the right page.

### 6.7 Settings

All read in `config.py`. On the server they are written to
`/etc/drivenstyle.env` by `install.sh`.

| Name | Meaning | On your PC | On the server |
|---|---|---|---|
| `DNS_WEB_DATA_DIR` | folder of the database and uploaded files | not set (`data\web\`) | `/opt/drivenstyle/data` |
| `DNS_WEB_ADMINS` | made admin when no active admin exists | not set | `automation.drivenstyle@gmail.com` |
| `DNS_WEB_GOOGLE_CLIENT_ID` | Google sign-in | optional | set |
| `DNS_WEB_DEV_LOGIN` | test sign-in | `1` | **never** |
| `DNS_WEB_HTTPS` | cookie only over HTTPS | not set | `1` |
| `DNS_WEB_SESSION_HOURS` | how long a sign-in lasts | 12 | 12 |
| `DNS_WEB_SECRET` | key that signs the cookie | made by itself | made by itself (`data/web_secret.key`) |
| `DNS_SOFFICE` | path to LibreOffice, if not found by itself | - | not needed |

---

## Part 7 - The database

### 7.1 Where it is and how to look at it

| | File |
|---|---|
| Your PC (web tool) | `data\web\drivenstyle.db` |
| The server | `/opt/drivenstyle/data/drivenstyle.db` |
| Desktop tool | `%LOCALAPPDATA%\Drive N Style Reports\drivenstyle.db` |

To look inside, install **DB Browser for SQLite** (https://sqlitebrowser.org),
choose "Open Database" and pick the file. **Look, do not edit**: a change
made here skips the audit log and the checks. To study the server's data,
fetch a backup (`deploy.ps1 -Backup`) and open the copy.

### 7.2 The tables

| Table | Holds |
|---|---|
| `meta` | small settings, including the schema version and `payout_start_date` |
| `products`, `product_rates` | the Product master and its dated prices / costs / labour charges |
| `executives` | the Sales executive master (branch, "gets incentive") |
| `cars` | the Car master |
| `incentives`, `incentive_rates` | the Incentive master and its dated amounts |
| `package_items` | the Packages master |
| `import_mappings` | column matching remembered from earlier Excel imports |
| `invoices`, `invoice_lines` | invoices read, and their lines |
| `invoice_checks` | problems found on an invoice (what Scan review lists) |
| `scan_files`, `scan_runs` | which files were read, and each reading |
| `match_aliases`, `invoice_overrides`, `issue_acks` | the saved matches and fixes made on Scan review |
| `monthly_costs`, `monthly_settings` | the monthly inputs typed by hand |
| `report_runs` | every report generated (the History screen) |
| `rto_months` | totals from each month's delivery list |
| `users` | who may sign in, and as what |
| `payout_lines`, `payout_invoices` | the daily payout register |
| `audit_log` | every change. **Read-only**: the database itself refuses to change or delete a row. |

The exact columns are in `app/data/database.py`, each with a comment.

### 7.3 Changing the database's shape (a "migration")

You will need this when a feature needs a new table or column.

**The rule: steps are only ever added at the end. An old step is never
edited**, because databases in use have already run it.

1. Open `app/data/database.py`. Find `SCHEMA_VERSION = 14` and the list
   `_MIGRATIONS`.
2. Add a new step at the **end** of the list, written like the last one.
3. Raise `SCHEMA_VERSION` by one (to 15).
4. Add a test, copying `tests/test_database_upgrade.py`: it builds a
   database at the old version, upgrades it, and checks the data survived.
5. Run all the tests.

When the tool next starts, it sees an older version number in the file,
**makes a backup copy of the file**, and runs the new step. This happens
by itself on your PC and on the server.

### 7.4 The audit log

Every change to a master, every Scan review fix, every monthly input and
every payout action writes a row to `audit_log` **in the same transaction
as the change**. The repo classes do this for you (`MastersRepo`,
`UsersRepo`, `PayoutStore` ...). So: always change data **through the
repo classes**, never with your own `UPDATE` statement.

---

## Part 8 - The business rules

**`CLAUDE.md` is the authority.** Its section "Business rules already
agreed (do not change without asking)" lists every rule with the date the
client or Brinda agreed it. Read it fully before touching `app/reports`
or `payout_app/engine.py`. The main ones, so you know what to expect:

| Rule | In short |
|---|---|
| Sales | each line after its share of the invoice discount, **without GST** |
| Product cost, labour | master cost and labour charge x quantity, at the rate in force **on the invoice date** |
| Gross profit | sales - product cost - labour |
| Matching | **never fuzzy.** Exact name, then a saved match, then SKU. Unknown goes to a person. |
| Open issues | an invoice with any open issue is **left out of every report** and listed as not included |
| Rs. 1 labour lines | Zoho's marker lines are ignored |
| Incentive rounding | each executive's **monthly** total is rounded up to the next Rs. 10. The daily payouts do **not** round. |
| Internal team | a fixed amount per car PPF, on top of the executive's incentive; none for two-wheelers |
| "Gets incentive" | executives with this off earn no spot incentive |
| Packages | a package sale only when **every** item of the package is on the invoice |
| Automatic indirect costs | 4% and 3% of product cost, editable on Monthly inputs |
| Labour kinds | Floor mat / Sunfilm / Other, decided by words in the item name (`labour_group`) |
| Daily payouts start | invoices before the start date (01-10-2026) are not posted |
| Money format | Indian grouping on screen (12,34,567.00); dates dd-mm-yyyy |

If a request seems to contradict one of these, **do not decide yourself.**
Ask Brinda; she asks the client.

---

## Part 9 - The server's addresses (API)

All start with `/api`. "Who" = who may call it.

### 9.1 Sign-in and users (`main.py`)

| Address | Who | What |
|---|---|---|
| `GET /api/config` | anyone | version, Google client ID, whether test sign-in is on |
| `POST /api/auth/google` | anyone | sign in with Google's note |
| `POST /api/auth/dev` | anyone, only if test sign-in is on | sign in by e-mail |
| `POST /api/auth/logout` | signed in | sign out |
| `GET /api/me` | signed in | who am I |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}`, `DELETE /api/users/{id}` | admin | the list of people |

### 9.2 Masters and audit log (`masters_api.py`, `imports_api.py`)

`{master}` is one of the masters named in `master_defs.py`.

| Address | Who | What |
|---|---|---|
| `GET /api/masters` | signed in | the masters and their fields |
| `GET /api/masters/{master}/rows` | signed in | the rows |
| `POST /api/masters/{master}/rows`, `PUT .../rows/{id}` | signed in | add / change a row |
| `POST .../active`, `.../delete`, `.../delete-all` | signed in | bulk actions |
| `GET .../rows/{id}/rates`, `POST .../rates/delete` | signed in | dated amounts of a row |
| `POST .../import/upload`, `.../import/{token}/preview`, `.../import/{token}/run`, `DELETE .../import/{token}` | signed in | import from Excel, in steps |
| `POST .../import/{token}/remove-missing` | **admin** | remove products not in Zoho's list |
| `POST .../export` | signed in | the rows shown, as Excel |
| `GET /api/audit`, `GET /api/audit/export` | admin | the audit log |

### 9.3 Monthly reports (`monthly_api.py`) - admin only

`{month}` is written `2026-09`.

| Address | What |
|---|---|
| `GET /api/monthly/choices`, `/history` | months available; reports made |
| `GET /api/monthly/{month}/overview` | what is uploaded and read for the month |
| `POST` / `DELETE /api/monthly/{month}/files/{kind}` | upload / remove one of the three files |
| `POST /api/monthly/{month}/read` | read the invoices |
| `GET /api/monthly/{month}/invoices`, `/issues`, `/issues/export` | invoices read; open issues |
| `POST /api/monthly/{month}/fix` | fix an issue on Scan review |
| `GET .../matches`, `/matches/export`, `POST .../matches/change`, `/matches/remove`, `GET /api/monthly/match-choices/{kind}` | saved matches |
| `GET` / `PUT /api/monthly/{month}/inputs`, `PUT /api/monthly/auto-rates` | monthly inputs |
| `POST /api/monthly/{month}/generate` | make the workbook and the PDF |
| `GET /api/monthly/runs/{id}/download`, `POST .../pdf`, `.../regenerate` | a report made earlier |
| `DELETE /api/monthly/{month}/runs`, `/invoices` | remove a month's reports / its invoices |

### 9.4 Daily payouts (`daily_api.py`, `daily_reports.py`)

| Address | Who | What |
|---|---|---|
| `GET /api/daily/overview` | signed in | counts for the top of the screens |
| `POST /api/daily/files`, `DELETE /api/daily/files/{name}` | signed in | upload / remove an invoice PDF |
| `POST /api/daily/scan` | signed in | read the uploaded PDFs and post payout lines |
| `GET /api/daily/review`, `/choices`, `POST /api/daily/match`, `/accept-totals`, `/cancel` | signed in | fix invoices in review |
| `GET /api/daily/lines` | signed in | the register |
| `POST /api/daily/proofs`, `GET /api/daily/proofs/{name}` | signed in | upload / see a payment proof |
| `POST /api/daily/pay`, `/reopen`, `/hold` | signed in | record a payment, undo it, hold a line |
| `GET /api/daily/log` | signed in | history |
| `GET /api/daily/slip`, `/summary`, `/month-check`, `/export` | signed in | the reports |
| `PUT /api/daily/start-date`, `POST /api/daily/clear` | **admin** | start date; empty the register |

---

## Part 10 - Working on the screens

### 10.1 The pattern every page follows

1. The page is a function in `src/pages/`.
2. It gets data by calling a function from `src/api.ts` - never `fetch`
   directly.
3. It keeps what it got in React state (`useState`) and loads it when the
   page opens (`useEffect`).
4. It uses the style names from `src/theme.css`. **No colours written in
   a page.**

Open `src/pages/Users.tsx` first: it is the smallest complete example
(list, add, change, remove).

### 10.2 Adding a new page, step by step

Say you add "Daily payouts > Holidays".

1. **Server.** In the right file under `web/backend/` add the address,
   copying an existing one. Decide who may call it (`current_user` or
   `admin`).
2. **Server test.** In the matching `tests/test_web_*.py` add a test:
   signed-in call works, call without sign-in gets 401, and (if admin
   only) a staff call gets 403.
3. **`src/api.ts`.** Add the TypeScript type of the answer and one
   function per address.
4. **`src/pages/Holidays.tsx`.** Write the page.
5. **`src/App.tsx`.** Add the page's address (route).
6. **`src/Shell.tsx`.** Add the menu line under the right tab.
7. Run `npm run check` in `web\frontend` (finds type mistakes) and
   `python -m pytest` in the project folder.
8. Try it in the browser, as an admin **and** as a staff user.

### 10.3 Commands in `web\frontend`

| Command | What |
|---|---|
| `npm run dev` | the screens for development, reloading as you save |
| `npm run check` | type-check only |
| `npm run build` | type-check and write `dist/` (what the server uses) |

---

## Part 11 - The tests

```powershell
python -m pytest                          # everything
python -m pytest tests/test_web_daily.py  # one file
python -m pytest -k "privacy"             # tests whose name contains a word
python -m pytest -x                       # stop at the first failure
```

- **All tests must pass before any commit.** No exceptions.
- A few tests are **skipped** on purpose: they need real client files
  (given through environment variables) or PySide6 with a screen.
  "skipped" is fine; "failed" is not.
- Tests build their own data in code. They never touch your real
  database and never need client files.
- **`tests/test_baseline.py` is the most important test.** It compares
  September 2026's figures with the saved "correct answer"
  (`data/baseline/`, present on Brinda's PC). If your change moves a
  figure, this test fails. That is either a bug in your change, or an
  intended change that **Brinda must approve** before the baseline is
  saved again with `python scripts/snapshot_month.py 2026 9`.
- When you fix a bug, first write a test that fails because of the bug,
  then fix it. When you add a feature, add its tests in the same version.

---

## Part 12 - Making a change: the routine

This project has fixed working rules, set by Brinda. Follow them every
time, even for one line.

### 12.1 Before you write any code

1. **Do not code immediately.** Write down, in plain language: what you
   understood, what you will change, what you are assuming, and any open
   question with your suggested answer.
2. Send that to Brinda and **wait for her "yes"**.

### 12.2 While coding

3. Make sure you start from the latest code:
   ```powershell
   git pull origin main
   ```
4. Make the change. Every new file starts with a header comment in the
   house style - open any file and copy the shape: title, a
   `WHAT THIS MODULE DOES` section, and the rules in words an accountant
   can follow. **Explain why, not only what.**
5. Add or update tests. Run `python -m pytest` until nothing fails.
6. If you changed the screens: `npm run check` in `web\frontend`.

### 12.3 One version per piece of work

7. Choose the new version number. The current one is in
   `app/__init__.py`.
   - a fix or documentation only: raise the last number (0.29.0 -> 0.29.1)
   - a new feature: raise the middle number (0.29.1 -> 0.30.0)
8. Put the new number in **three** places:
   - `app/__init__.py` - `__version__ = "..."`
   - `web/frontend/package.json` - `"version": "..."`
   - `web/frontend/package-lock.json` - the two `"version"` lines near the top
9. Update the documents, **every version**:
   - `CHANGELOG.md` - a new section at the top, under `## [Unreleased]`,
     with `### Added` / `### Changed` / `### Fixed` / `### Pending`
   - `README.md` - the "Current status" line
   - `CLAUDE.md` - the "Current version" line, and any new rule or lesson
   - `web/README.md` and `docs/` if what they describe changed

### 12.4 Commit, tag, push

10. See what changed:
    ```powershell
    git status
    git diff
    ```
    Read the list. **No client file may be in it** (see Part 16).
11. Stage the files **by name** (not `git add -A`, so nothing slips in):
    ```powershell
    git add app/__init__.py CHANGELOG.md README.md CLAUDE.md web/backend/daily_api.py tests/test_web_daily.py
    ```
12. Commit with a message that has a title line and a description:
    ```powershell
    git commit
    ```
    An editor opens. First line: `v0.30.0 - Short title`. Then an empty
    line, then what changed and why. Save and close.
13. Tag and push:
    ```powershell
    git tag -a v0.30.0 -m "v0.30.0 - Short title"
    git push origin main
    git push origin --tags
    ```

### 12.5 Put it on the server

14. Take a backup first, then deploy (details in `docs/deployment.md`):
    ```powershell
    powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -Backup
    powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1
    ```
    It must end with `DONE - version 0.30.0 is running`.
15. Open the live tool and try the thing you changed.
16. Tell Brinda in plain language: what changed, what she must do, and
    anything you could not test.

### 12.6 Rules of the code

- **The server runs Python 3.10.** Do not use features added in 3.11 or
  later (for example `tomllib`, `ExceptionGroup`, `typing.Self`). If
  unsure, look the feature up before using it.
- `app/data` and `app/reports` contain **no screen code** (no PySide6, no
  FastAPI). They must stay importable on their own.
- The fields of a master are described **only** in `master_defs.py`.
- The web tool has **no copy** of a calculation. If a figure is needed,
  call the function in `app/reports` or `payout_app`.
- Change data only through the repo classes, so the audit log is written.
- Database changes are new migration steps at the end (7.3).
- Messages shown to the user are in plain words, with no technical terms.
- Do not rewrite or "tidy" the frozen desktop screens.

---

## Part 13 - The server

Full instructions are in **`docs/deployment.md`**. The essentials:

| Task | Command (on your PC, project folder) |
|---|---|
| Install or update | `powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1` |
| Is it running? | `... deploy\deploy.ps1 -Status` |
| Fetch a backup to the PC | `... deploy\deploy.ps1 -Backup` |
| Copy a database to the server | `... deploy\deploy.ps1 -Database "path\file.db" -Replace` |

What `deploy.ps1` sends is **the last commit**, not your unsaved work. It
warns you if you have uncommitted changes.

On the server everything of ours is under `/opt/drivenstyle`:

```
/opt/drivenstyle/app            the running version's code
/opt/drivenstyle/app.previous   the version before it
/opt/drivenstyle/venv           Python libraries
/opt/drivenstyle/data           THE DATA - never touched by an update
/opt/drivenstyle/backups        nightly database copies (14 kept)
```

To log in to the server yourself (rarely needed):

```powershell
ssh -i "C:\Official\Coding\Personal Coding Projects\key\Printapp_KEY.pem" ubuntu@35.154.161.180
```

Useful commands once there (type `exit` to leave):

```bash
sudo systemctl status drivenstyle            # running?
sudo systemctl restart drivenstyle           # stop and start the tool
sudo journalctl -u drivenstyle -n 50 --no-pager   # its last 50 messages
df -h /                                      # free disk space
```

**This server is shared with other companies' live websites.** On it you
may touch only: `/opt/drivenstyle`, the service `drivenstyle`, the nginx
file `drivenstyle.duckdns.org`, `/etc/drivenstyle.env` and
`/etc/cron.d/drivenstyle-backup`. Never restart nginx (reload only, and
only after `sudo nginx -t` says OK), never restart MySQL or PHP, never
run `apt upgrade`, never edit another site's file.

---

## Part 14 - Routine jobs

| When | What | How |
|---|---|---|
| Weekly | fetch a backup to the PC | `deploy.ps1 -Backup` (files land in `data\server-backups\`) |
| Monthly | check the server's disk | `deploy.ps1 -Status`; warn the IT vendor above 90% used |
| A person joins | let them sign in | Users screen: add their Gmail. While Google's sign-in is in "Testing", also add them as a test user in Google Cloud > Google Auth Platform > Audience. |
| A person leaves | stop their sign-in | Users screen: switch them off. They are out at once. |
| A rate changes | new dated amount | Masters screen: change the row and give the "effective from" date. Never overwrite history. |
| Every month | the monthly reports | Monthly reports tab: upload the three Zoho files, Read invoices, clear Scan review, Monthly inputs, Generate |
| Every 60-90 days | HTTPS certificate | renews by itself (certbot). If the browser ever warns, run `deploy.ps1` again. |

---

## Part 15 - When something goes wrong

### 15.1 On your PC

| What you see | Cause and fix |
|---|---|
| `python` or `npm` "is not recognized" | not installed, or PowerShell was open during the install. Reopen PowerShell. |
| `ModuleNotFoundError: No module named 'fastapi'` | `.venv` is not active (`.venv\Scripts\activate`), or the libraries were not installed (4.3) |
| "running scripts is disabled on this system" | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| The page loads but every action says "Please sign in" | the server (window 1) is not running |
| "The screens have not been built yet" at `localhost:8000` | you opened the server's port. Open `localhost:5173`, or run `npm run build`. |
| No Test sign-in box | `$env:DNS_WEB_DEV_LOGIN = "1"` was not set in window 1 **before** starting the server |
| "Your address is not on the list" | sign in as `automation.drivenstyle@gmail.com` and add yourself on the Users screen |
| `address already in use` | an old server is still running. Close the old window, or use `--port 8001` and change the port in `vite.config.ts` to match. |
| `database is locked` | DB Browser has the file open with unsaved changes. Close it. |
| A test fails only for you | `git status` - you may have a half-finished change. Also `pip install -r ...` again in case libraries changed. |
| PDF making fails on your PC | needs Excel (Windows) or LibreOffice. Not needed for most work. |

### 15.2 On the live tool

See the table "When something is wrong" in `docs/deployment.md`. The
first three things to do are always:

1. `deploy.ps1 -Status` - is the service active, is the disk full?
2. Read the tool's messages (`journalctl`, Part 13).
3. If a new version caused it, go back to the previous version (the
   command is in `docs/deployment.md`) and **then** find the cause calmly.

### 15.3 A figure looks wrong

1. Do not change code yet. Find one invoice that shows the problem.
2. Check the masters **on the invoice's date** (dated rates).
3. Check Scan review: an invoice with an open issue is left out on purpose.
4. Read the rule in `CLAUDE.md`. The tool may be right and the
   expectation wrong - this has happened (the incentive discount rule).
5. If it really is a bug: write a test that shows it, fix it, and tell
   Brinda which past figures change.

---

## Part 16 - Rules that must never be broken

1. **Client data never goes into Git.** No invoices, price lists, exports,
   reports, databases. `.gitignore` blocks `/data/`, `*.pdf`, `*.xlsx`,
   `*.csv`, `output/` - do not weaken it, and do not rename a client file
   to get around it. Read `git status` before every commit.
2. **No secrets in Git.** No key files (`.pem`), no passwords, no
   `client_secret*.json`, no tokens. The server's key file stays outside
   the project folder.
3. **Test sign-in never on the server.**
4. **The audit log is never edited or deleted**, and data is never
   changed behind its back.
5. **Never edit the live database by hand.** Fix data through the tool,
   or with a reviewed script that goes through the repo classes, after a
   backup.
6. **Backup before every deploy** and before anything risky.
7. **Leave the server's other sites alone** (Part 13).
8. **No calculation changes without Brinda's written yes.**
9. **Never deploy uncommitted or untested code.**
10. **Client data stays on the PCs and the server it is meant for.** Not
    in e-mail, chat, cloud drives or screenshots sent to others.

---

## Part 17 - Known limits and open items

| Item | State |
|---|---|
| Web address | a free DuckDNS name. Some office filters block such names. A bought domain (e.g. `reports.drivenstyle.in`) is the proper fix; steps in `docs/deployment.md`. |
| Google sign-in | in "Testing": every user must also be a Google "test user". Publishing needs the Branding page filled (home page and `/privacy`). |
| Backups | nightly, but on the **same server**. They leave it only when someone runs `-Backup`. An S3 bucket from the client would make this automatic. |
| Shared server | whoever holds the server's key can read the data. A small server of the tool's own would separate it. |
| One process | the tool runs as a single process with SQLite. Fine for this client's handful of users; not built for hundreds. |
| Privacy page wording | drafted by the developer; Brinda should confirm it on the client's behalf. |
| Desktop programs | frozen. Their screens are not maintained. |
| Uploaded files | invoice PDFs, exports and reports accumulate under `data/`. Watch the disk. |

---

## Part 18 - Handover checklist

Tick these off with Brinda on your first day.

- [ ] Your GitHub account can read and push to `mbrinda2189/drivenstyle-reports`
- [ ] The four programs are installed and print their versions (4.1)
- [ ] `python -m pytest` ends with 0 failed on your PC (4.5)
- [ ] The web tool runs on your PC and you can sign in with test sign-in (4.6)
- [ ] You have read `CLAUDE.md` from "Working rules" to the end of "Business rules"
- [ ] You have read `docs/deployment.md`
- [ ] You have the server key file, stored **outside** the project folder, and `deploy.ps1 -Status` works
- [ ] You have been added on the tool's Users screen and as a Google test user, and can sign in to the live tool
- [ ] You know who to tell at the client's IT vendor before a deploy
- [ ] You have fetched one backup with `-Backup` and opened it in DB Browser
- [ ] You have made one tiny change (for example a wording fix) through the **whole** routine of Part 12, with Brinda watching

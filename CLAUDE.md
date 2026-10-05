# CLAUDE.md – Drive N Style Reports

Read this first in every session. It records how Brinda wants work done,
the decisions already made, and what is next. README.md (features, usage,
project structure) and CHANGELOG.md (history) are the other two sources of
truth. Keep all three up to date.

## What this is

A Windows desktop tool (Python 3.10+, PySide6) for the client **Drive N
Style / Carkrafts** (car accessories and detailing, Coimbatore; GSTIN
`33AAOFD7793F1Z2`). Each month it reads the month's invoices from Zoho's
invoice export (Invoice.csv / .xlsx; PDFs until v0.5.0), matches
every line, salesperson and car to the masters, lets anything unclear be
fixed on a Scan review screen, and writes one Excel workbook with 12
management reports. The user is Brinda, a Chartered Accountant, preparing
the reports for her client before the 7th of each month.

Current version: **v0.19.1** (tags v0.1.0 … v0.19.1 on GitHub
`mbrinda2189/drivenstyle-reports`, branch `main`).

## Working rules (from Brinda – always follow)

1. **Never code immediately.** Propose the plan, list assumptions and open
   questions with a suggested default for each, and wait for her
   confirmation. Only then code.
2. **Version control for every change.** One version per confirmed piece of
   work: bump `app/__init__.py` `__version__`, commit with a descriptive
   multi-line message, annotated tag `vX.Y.Z`, and push:
   ```
   git push origin main
   git push origin --tags
   ```
3. **Detailed comments.** Every module starts with a docstring in the
   project's house style (title, `WHAT THIS MODULE DOES` section, layout
   sketches where useful, plain-language rules). Explain *why*, for a reader
   who is an accountant, not only a programmer.
4. **Update README.md and CHANGELOG.md with every version** (Keep a
   Changelog format: Added / Changed / Fixed / Pending).
5. Summaries to Brinda: plain language, what changed, what she must do
   (e.g. `pip install -r requirements.txt` when dependencies change), and
   the git commands.

## Commands

```powershell
.venv\Scripts\activate
pip install -r requirements-dev.txt     # runtime deps + pytest
python main.py                          # run the app
python -m pytest                        # all tests (must pass before any commit)
$env:DNS_SAMPLE_INVOICES = "path\to\sample pdfs"; python -m pytest tests/test_invoice_pdfs.py
python scripts/make_sample_masters.py   # sample master sheets in data/samples/
```

Git from the Cowork Linux VM (the folder is mounted from Windows): files
are CRLF on disk and LF in the repo, and file modes differ, so always run
`git -c core.autocrlf=input -c core.filemode=false …` there, stage files by
name (never `git add -A`; `.git.zip` is Brinda's own backup), and remove a
stale `.git/index.lock` if one is left. Qt cannot start in that VM (no
libEGL); run screen tests in the cloud workspace instead.

When testing Qt code headless, wait with `app.processEvents()` in a loop,
**not** `QTest.qWait` – `qWait` starves the background scan thread (a scan
of 7 PDFs took 14 s instead of 0.9 s).

## Client data – never commit

`.gitignore` excludes `/data/`, `*.pdf`, `*.xlsx`, `*.csv`, `output/`.
Real client files (invoices, Items.xlsx, Invoice.csv, payments export,
executive list) stay out of Git. Keep samples in `data/samples/`
(ignored). Tests build their data in code; real-file tests are opt-in via
environment variables. The app's database lives in
`%LOCALAPPDATA%\Drive N Style Reports\drivenstyle.db` (override with
`DNS_REPORTS_DATA_DIR`; tests always do). The client's current files are
in `data/Samples/` (ignored): Invoice.csv (Sep 2026 export),
Customer_Payment.csv (payments export), "Chandra Hyundai - Retail Counter -
Pricelist (1).xlsx" (sheets: Master Data - Items, Executive ph.no,
Incentive, Incentive Details = incentives actually paid per invoice,
Labour Payment = labour paid per car model, Sheet3 = Zoho items export).

## Architecture rules

- `app/data/` and `app/reports/` contain **no Qt code** (testable alone).
  Screens live in `app/pages/` and `app/widgets/`.
- **Every change to a master, a Scan review fix and every monthly input is
  written to `audit_log`** in the same transaction as the change. The audit
  log is read-only (database triggers refuse UPDATE/DELETE).
- **Schema changes are append-only migration steps** in
  `app/data/database.py` (`SCHEMA_VERSION`, `_MIGRATIONS`); an existing
  database is backed up before upgrading. Never edit an old step.
- Field lists of the masters live only in `app/data/master_defs.py`; the
  screen, edit form, import and export are driven from them.
- Colours only from `app/theme.py` (`Colors`). Arial in Excel output;
  Segoe UI in the app. Amounts shown with Indian grouping on screen
  (`app/utils.format_inr`), `#,##0.00` in Excel. Dates dd-mm-yyyy.
- Performance (v0.6.1): never put a widget in every row of a long table
  (Scan review had ~95 rows × drop-down of 170 products – scrolling and
  refresh lagged). Use plain items and build controls only for the clicked
  row. Pages hidden behind others are marked stale and rebuilt on show,
  not rebuilt on every master save.
- Pop-up windows: Brinda's laptop is ~1333×830 logical px (Windows zoom
  150 %). Build dialogs with `common.scroll_body` (scrolling body, fixed
  buttons) and size them with `common.fit_to_screen`; use NoWheelComboBox /
  NoWheelDateEdit inside scrolling areas (v0.6.4: the Import button was
  unreachable).
- Qt combo boxes: store item data as strings/ints, never Python tuples
  (`findData` cannot match tuples – this caused a bug in v0.5.0).
- On Windows `glob("*.pdf")` is case-insensitive; never add a second
  `"*.PDF"` search (counted every file twice until v0.4.0).

## Business rules already agreed (do not change without asking)

- **Daily payout app** (Brinda, 05-10-2026; plan approved, see project doc
  `daily-payout-app-plan.md`): a SEPARATE small app in this repo that reads
  the invoice PDFs staff save in a folder, calculates labour and incentive
  with this tool's masters and rules (shared core), and posts to a Google
  Sheet register where staff record payment + proof. Masters move to a
  Google Sheet the client edits directly (dated rows); owner account
  automation.drivenstyle@gmail.com; OAuth client JSON is in `data/`
  (ignored - never commit). No approval step, no technician, labour one
  line per invoice, NO daily rounding of incentive (month-end only).
  Step 1 done in v0.13.0: PDF reader updated (`InvoiceLine.note`, Branch,
  mixed-GST totals check, `invoices_repo.billed_lines`).
  Step 2 done in v0.14.0: `payout_app/` (no `core/` folder - `app/data`
  and `app/reports` ARE the shared rules and are imported from there;
  agreed 05-10-2026). `masters_sheet.py` = sheet layout, `to_tabs`,
  `load_tabs` (loads the rows into an in-memory database through
  MastersRepo.save, so the monthly tool's checks apply), `refresh` with
  last good copy; `google_api.py` = OAuth sign-in + Sheets calls;
  `masters_cli.py` = create / check / use / preview. Dated rows: a new row
  per rate change with "Effective from". The monthly tool still uses its
  own database masters (switch later). Google calls NOT yet run with a
  real sign-in - first real run is Brinda's `create`. Google project is in
  Testing (7-day sign-in); publish vs service account still open.
  Step 3 done in v0.15.0 (commands only): `engine.py` stores the PDFs in
  the in-memory database (InvoicesRepo.store_scan, lines given net + GST =
  billed) and values them with reports/data.build_month -> PayoutLine
  (IDs `<invoice>-LAB / -INC / -INT`, adjustments `-ADJn`); `register.py`
  plans the writes (post once by invoice "Print" fingerprint, In review,
  Re-issued, Cancelled, tally) and `verify` restores calculated cells
  from the hidden sealed "Check" cell (option A: staff sign in as
  themselves, so cells cannot be locked - agreed 05-10-2026);
  `payout_cli.py` = create-register / use-register / scan [--dry-run]
  [--from] / status. Saved matches live in the register's Matches tab.
  First real `create` of the masters sheet worked on Brinda's PC
  (sheet id in payout_settings.json); register calls not yet run for real.
  Step 4a done in v0.16.0: window `python -m payout_app` (payout_app/ui:
  main_window, setup_page, scan_page, review_page, tables, workers) on top
  of `service.py` (scan / save_match / cancel_invoice /
  monthly_tool_matches). Pages never call Google directly: they ask
  `window.run(what, function, on_done)`, ONE background task at a time.
  IMPORTANT (bug found while testing): a Qt signal connected to a plain
  Python function runs in the EMITTING thread - callbacks from the
  worker go through `workers._Relay` (a QObject on the screen's thread).
  Sign-in opens in Edge; Google scope is now full `drive` (proofs in one
  shared folder, Brinda's choice A) - older tokens are re-asked.
  Screen tests: tests/test_payout_ui.py (offscreen, fake Google; skipped
  without PySide6 - run them in the cloud workspace).
  Step 4b done in v0.17.0: Payouts + History screens; service
  record_payment / reopen_payment / set_hold / create_proofs_folder /
  read_register; `slip.py`; google_api.DriveClient (create_folder,
  upload) and SheetsClient.update_ranges / add_tab; register "Setup" tab
  (Proofs folder id). Payments write ONLY columns K-R of a line
  (register.payment_range). workers.py was rewritten as Task(QThread)
  after an intermittent segfault - read its notes before touching it,
  and run tests/test_payout_ui.py MANY times after any change there.
  Stand-ins for Google: tests/fakes.py.
  v0.17.1: housekeeping on Set-up (Brinda wanted the sheets clean before
  the installer): service.clear_register (backup copy first, type CLEAR,
  owner only; clears Payouts / Invoices / Log, keeps Matches + Setup),
  find_duplicates / trash_duplicates (Drive trash, never a sheet in use).
  v0.18.0: `scripts/build_payout_app.py` (PyInstaller one-folder build
  from `payout_main.py`; bundles Google key + sheet-link defaults into
  `payout_bundle`, prunes Google's unused discovery documents, excludes
  pandas / numpy / scipy ..., writes "Staff guide.pdf" from
  docs/payout_app_staff_guide.md, runs the built exe with `--check`,
  zips). settings.load() = bundled defaults under the PC's own settings;
  google_api.find_client_secret also looks in the bundle. Unexpected
  errors -> payout_app_errors.log. Built and self-checked on Linux only;
  the first Windows build is Brinda's. Staff PCs: Windows 10. Weekly
  Google sign-in accepted for now (Brinda, 05-10-2026).
  Masters changes (new executive, new amount) are made by the client in
  the masters Google Sheet - no rebuild.
  Next: installer (PyInstaller) for the staff PCs; first real runs on
  Brinda's PC of register / Drive calls; publish Google app vs service
  account. Cowork note: Qt tests run only in the cloud workspace - stage
  app/ + payout_app/ + tests there (pip install PySide6 pdfplumber
  openpyxl pytest; QT_QPA_PLATFORM=offscreen).
  In the Cowork VM git cannot delete files: set GIT_OPTIONAL_LOCKS=0 and
  rename a leftover `.git/*.lock` out of the way (`*.stale`).

- **Sales** = each line after its share of the invoice-level discount,
  **excluding GST**. Invoices showing no GST count in full as sales.
- **Product cost** and **labour** = Product master cost price and labour
  charge (both GST-exclusive) × qty, at the rate effective on the invoice
  date. Labour = what Drive N Style pays; only for products with
  "Labour involved". Gross profit = sales − product cost − labour.
- **Dated values**: selling price, cost price, labour charge, incentive
  amount and bill value keep an effective-from history; a date before the
  first rate uses the first rate.
- **Invoices come from Zoho's invoice export** (v0.6.0). Sales per line =
  `Item Total`, GST = `Item Tax Amount`, used as they are. Check: lines +
  GST + Round Off = Total. Month by `Invoice Date`; other months ignored;
  Void/Draft skipped. Payment made = Total − Balance.
- **Delivery (RTO) list + executive summary** (Brinda, 03-10-2026, v0.9.0):
  third file on Generate (same layout every month). Linked to invoices by
  the last six VIN digits (invoice VIN field / end of customer name).
  Sheets 13-17 + always-written "Summary" (`app/reports/rto_reports.py`,
  `app/data/rto_list.py`). List figures and invoiced figures are shown side
  by side, never forced to agree. Models are grouped by a simple rule
  (`model_key`), not the Car master; consultants are as named in the list.
- **Remove a month / History entry** (v0.10.1): History page;
  `InvoicesRepo.months_read` / `remove_month`, `InputsRepo.remove_runs`.
  Brinda wants add / view / change / delete available wherever data is
  kept; the audit log stays read-only by design.
- **Incentive rounding** (Brinda, 04-10-2026, v0.12.1): "our tool is
  correct" - the discount rule stays (Zoho / staff pay full amounts, that
  difference is accepted). Each executive's monthly total is rounded UP to
  the next Rs. 10 (`reports/data.round_up_10`), once per executive.
- **Internal team incentive** (client via Brinda, 04-10-2026, v0.12.0):
  Rs. 3,000 per car PPF to the internal team, IN ADDITION to the sales
  executive's incentive; no incentive of any kind for two-wheeler PPF; one
  line "Internal team", not split by person. `products.internal_incentive`
  (per unit, paid in full). Zoho booked 15,000 for September (5 PPF incl.
  the two-wheeler); the tool gives 12,000 (4 car PPF).
- **Gets incentive flag** (client via Brinda, 04-10-2026, v0.11.0):
  executives.gets_incentive; Mano Vikram and Nandha Kumar do not get spot
  incentive. `Invoice.incentive_allowed`, `MonthData.no_incentive`.
- **PDF: every % column runs highest first** (Brinda, 04-10-2026): incl.
  margin % - from v0.11.1 the client wants the PDF's top lists RANKED by
  profit margin % (Excel still by gross profit).
- **Monthly PDF order** (client's handwritten note via Brinda, 05-10-2026,
  v0.19.0): P&L first; New-car business 5 lines; top 10 products / services
  by GROSS PROFIT (not margin %); Penetration by location; OE accessories by
  location and model; Branches by gross profit; Packages vs sales; Labour;
  Vehicle-wise; Spot incentive; Payment modes. No descriptions under
  headings, no "Prepared on". Everything else is out of the PDF (still in
  Excel). `pdf_book._append` drops title() note rows (font size 9).
- **PDF layout** (Brinda, 04-10-2026, v0.10.3): NO graphs in the PDF, no
  empty white space, page numbers in the footer, print must be readable.
  `pdf_book.py` writes each section, then copies them onto ONE "Report"
  sheet (formulas translated), A4 landscape fit-to-width, max 8 columns.
  This supersedes the "one portrait page per section + charts" layout below.
- **PDF version** (Brinda, 04-10-2026, v0.10.0): the PDF is NOT the whole
  workbook any more. `app/reports/pdf_book.py` writes a temporary workbook
  with only the summary tables she listed + Excel charts (chart figures at
  column AA, outside the print area; one section = one portrait page) and
  Excel exports that. Excel workbook must stay unchanged unless she asks.
  Excel export itself is confirmed working on her PC (v0.9.1 PDF, 42 pages).
  Charts were checked with LibreOffice only - not yet seen in real Excel.
- **Trend** (v0.10.0, `app/reports/trend.py`): business started August
  2026; Brinda will give August data. RTO totals per month are saved in
  `rto_months` when generating with the list.
- **PDF** (Brinda, 03-10-2026, v0.9.1): all sheets in one PDF, made by
  Excel via PowerShell COM (`app/reports/pdf_export.py`); client's PC has
  Excel. NOT yet run against real Excel - written and tested from Linux
  with the Windows call mocked; first real run is Brinda's.
- **Saved matches** (v0.8.3): Scan review tab listing match_aliases,
  invoice_overrides and issue_acks; `InvoicesRepo.saved_matches` /
  `remove_match` (audit logged). Brinda mapped some names wrongly during
  trials (Pravin - CMP -> HO, Karthick, Nappa Seat Cover - Creta).
- **Automatic indirect costs** (Brinda, 03-10-2026, v0.8.1): Breakage /
  returns / transport = 4% of COGS, Compliance GST = 3% of COGS, COGS =
  product cost + labour; every month incl. earlier ones
  (`reports/data.py` AUTO_INDIRECT). From v0.8.2 the percentages are
  editable on Monthly inputs: one setting for all months
  (`inputs_repo.auto_rates`, monthly_settings month "all"), audit logged.
- **Packages** (Brinda, 03-10-2026, v0.8.0): an invoice is a package sale
  only when EVERY item of the package is on it (`app/reports/packages.py`,
  Packages master = `package_items`: package / coupon item / Zoho item).
  Higher coupon value wins if two fit; one package per invoice. Package
  incentive (Incentive master row with the package's name; bill value =
  coupon final value) replaces the items' own incentives, same discount
  rule. Report file names carry date and time. Draft links:
  `data\Samples\Package_items_draft.xlsx` (yellow rows awaiting client).
- **"Others" for salesperson / car** (Brinda, 03-10-2026, v0.7.1): Scan
  review offers "Others (not in master)" (stored as target id 0,
  `invoices_repo.OTHERS_ID`). Reports show "Others", branch from the
  invoice, incentive still calculated. No "Others" for items.
- **Zoho item import is dated 1 April and replaces later dated amounts**
  (v0.7.1, `import_records(replace_later=True)`).
- **Zoho's item list is the Product master** (Brinda, 03-10-2026, v0.7.0):
  "Zoho's item names and price are the final". Item.csv gives name, SKU,
  HSN, selling price (Rate, GST-inclusive), cost price (Purchase Rate) and
  **category always from Zoho's Product Type** (goods → Product, service →
  Service). Products not in Zoho's list are removed (with confirmation).
  Labour charge, incentive group and Vehicle needed come from the staff
  sheet / Masters screen, imported with "Add items…" unticked. Zoho's ₹1
  labour items are not products. (Earlier: the staff sheet's SALES/SERVICE
  column decided the category – superseded.)
- **CODE is not reliable in the client's sheet** (HSN codes typed as CODE,
  shared by several items). A CODE shared by different names in one import
  is dropped for those rows (v0.6.5); items match invoices by name.
- **Counter sales** (v0.6.7): products have "Vehicle needed" (default Yes;
  No for counter items – master_defs.COUNTER_ITEM_WORDS). An invoice with no
  vehicle is fine when every item is No → "Counter sale (no vehicle)" in
  the reports; otherwise Scan review asks for the car.
- **Branch** in reports = the executive's branch from the master; the
  invoice's CF.Branch is stored only.
- **₹1 labour marker lines are IGNORED** (client confirmed, v0.6.3): not in
  any report, their value left out of sales (count and value on the cover
  sheet), no Scan review check. Labour = product's labour charge × qty for
  "Labour involved" products only.
- **Invoices with any open Scan review issue are left out of every
  report** and listed on the workbook's "Not included" sheet (included +
  left out = every invoice read).
- **Masters are never matched fuzzily.** Items by exact name (ignoring
  case/spaces/dash style), then a remembered mapping, then SKU. Unknown →
  Scan review, mapped once, remembered for all invoices.
- **Sales executives are unique by contact number** (10-digit mobile;
  +91 / 91 / leading 0 allowed). Printed salesperson "Name - Branch" is
  matched on name AND branch (letters/digits only; "Head Office" = "HO",
  "KTG" = "Kothagiri"); none or several matches → Scan review.
  Products unique by name (and SKU), cars by make+model, incentive groups
  by name. No duplicates anywhere.
- **Nothing is deleted silently.** Rows can be marked inactive or deleted
  (with confirmation; "Delete all" requires typing DELETE); the audit log
  keeps what was deleted.
- **Spot incentive (report 7) – rule CONFIRMED by the client (30-09-2026)**:
  incentive × qty × min(1, amount billed incl. GST ÷ (bill value × qty)).
  Needs products linked to incentive groups (the items sheet has no such
  column; draft links in data/Samples/Incentive_group_links_draft.xlsx,
  83 of 191 items, awaiting the client).
- **Packages (report 5)** = products whose incentive group name contains
  "Package".
- **Payment modes (report 11)** come from Zoho's "Payments Received"
  export (`Mode`, `Amount Applied to Invoice`, `Invoice Number`, `Deposit
  To`): every payment applied to the month's invoices, whatever the payment
  date; otherwise the export's CF.Invoice Type (UPI / Cash / CHY); the
  rest is "Not received".
- Workbook: Cover, 12 report sheets, "Not included". Totals, profits,
  margins, averages and summaries are **live Excel formulas** (verify with
  LibreOffice recalculation: zero errors).

## Done: v0.6.0 – Zoho invoice export (2026-09-28)

Brinda confirmed points 1–5 and decisions A (category default from Zoho
Item Type), B (CF.Invoice Type only as payment-mode fallback) and C (keep
the executive's branch). See CHANGELOG.md for the full list.

Result on the real September files (127 invoices, 371 lines): every invoice
reconciles to the paisa (no totals issues). With the pricelist's masters
imported: 172 of 179 items import (7 priced in words – "mrp less 10%"), 61
of 62 executives (NAVEENDRAN's 9-digit number). Open on Scan review: 24
item names not in the master, 67 salesperson issues (13 people not in the
list – Mano Vikram alone 29 invoices, Nandha Kumar 14 – and branch
conflicts Karthick - HO ×3, Pravin - CMP), 4 invoices without a vehicle.
Zoho's Item Type changed 12 categories from the HSN guess, e.g. Teflon /
Underbody / Silencer / Glass Coating and Interior Foam Wash → Product
(Zoho marks them goods) and the Blaupunkt sunfilm roll → Service. Brinda
should confirm these with the client or correct them on the Masters screen.

## Done: v0.6.1 – faster Scan review / Masters (2026-09-28)
Unknown salesperson / vehicle grouped by printed name (fix applies to all
its invoices – Brinda's choice); Fix controls only on the clicked row;
Scan review rebuilt on show instead of after every master save; close-app
error fixed. Brinda reported lag in Scan review scrolling, Masters editing
/ saving and Masters scrolling – ask her whether Masters scrolling is still
slow (no separate cause found; the Masters table itself is plain items).

## Done: v0.6.2 – Export issues (2026-09-29)
"Export issues" on Scan review (open issues only, with "What we need" and
"Client's reply" columns – Brinda's choice); quantity format fix.

## Done: v0.6.3 – ₹1 labour lines ignored (2026-09-29)
Client: ignore the ₹1 lines; labour only from the product master.

## Next – ideas, NOT confirmed (ask before coding)
- "Incentive Details" sheet in the pricelist lists incentives actually
  paid per invoice – could be used to derive / test the spot incentive rule
  (report 7).
- "Labour Payment" sheet gives labour paid by car model (e.g. VERNA PVC
  500, ALCAZAR PVC 600) – labour may depend on the car, not only the item.
- Items master open points: Water Wash cost ₹1; Sunfilm Budget Nano
  Ceramic min price > sale price.

## Still awaited from the client (not blocking)
- Confirmation of the product → incentive group links (draft sent).
- Package contents, if they want a package's items analysed.
- Monthly indirect costs (entered on the Monthly inputs screen).
- Any report layout they already use.

## Later
- Packaging as a Windows `.exe` with PyInstaller (include `app/assets/`;
  see `theme.asset()` for `sys._MEIPASS`).

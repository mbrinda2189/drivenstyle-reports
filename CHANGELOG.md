# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.22.0] – 2026-10-09 – Moving to a web tool: step 1 (baseline, September figures, folders)

The client's IT does not allow the Windows programs to run on the office
PCs. The monthly reports tool and the daily payout app will therefore
become ONE web tool, hosted on the client's own AWS (Brinda, 09-10-2026).
This version prepares the move and changes nothing in either program:
no screen, report or figure is different.

### Added
- **`web/` folder** with `web/backend` (FastAPI server) and `web/frontend`
  (React screens) - empty for now. `web/README.md` holds the plan, the
  decisions and the build order.
- **September's figures saved as the "before" picture.**
  `python scripts/snapshot_month.py 2026 9` copies the tool's database to
  `data/baseline/` (the real database is only read) and writes the month's
  figures to `data/baseline/figures_2026-09.json`: totals, automatic
  indirect costs, labour by kind of work, incentive per executive, and
  sales / product cost / labour / gross profit / incentive of every
  invoice. `data/` is not in Git - these are the client's figures.
- **`tests/test_baseline.py`**: `python -m pytest` now works every saved
  month out again and fails, naming the figure, if anything is no longer
  the same to the paisa. On a PC without `data/baseline/` this one test is
  skipped.
- `app/reports/snapshot.py`: `snapshot`, `differences`, `save`, `load`
  (no Qt, writes nothing to the database).

### Decided (09-10-2026)
- The calculations are not rewritten and not moved: the web tool imports
  `app/data`, `app/reports` and `payout_app/engine.py` as they are (no
  `core/` folder, as agreed on 05-10-2026).
- Database: SQLite on the server with a nightly backup, not PostgreSQL.
- Masters, payout register and proofs move from Google Sheets / Drive to
  the server's database and an S3 bucket.
- Google sign-in with roles (admin, staff); the reports PDF is made with
  LibreOffice on the server.

### Pending
- Step 2: the server's base (FastAPI, database, sign-in and roles).
- AWS credentials and a web address from the client; whether their IT
  allows the site and Google sign-in on the staff PCs.
- The Windows installer of the payout app is no longer planned.

## [0.21.0] – 2026-10-07 – Payout app: labour posted separately for floor mat and sunfilm

The client wants the labour for floor mats and for sunfilm as separate
tables. The monthly reports have had them since v0.20.0; this version does
the same in the daily payout app. The monthly tool is unchanged.

### Changed
- **Labour is posted as separate lines by kind of work**, so each can be
  listed, paid, held and proved on its own:
  `Labour - Floor mat` (ID ending `-LABM`), `Labour - Sunfilm` (`-LABS`)
  and `Labour - Other` (`-LABO`) for any other item with labour. An
  invoice with a mat and a sunfilm gets two labour lines. Spot incentive
  and internal team lines are as before.
- The kind is picked from the item name by **the same rule as the monthly
  "Labour calculation" tables** ("floor mat" / "sunfilm"; Brinda,
  07-10-2026: keep it to "floor mat" in both), so daily lines and monthly
  tables agree - a test checks each kind against the monthly figures.
- **Payout slip**: one table per kind of labour, each with its total, then
  the executives and the internal team.
- **Payouts screen**: the type filter lists the three kinds of labour and
  "Labour (all)".
- The register's Summary tab splits the totals by the new types by itself.

### Pending
- A labour line posted before this version stays one line "Labour"
  (`-LAB`); it is not split. If such an invoice is re-issued, its old line
  is cancelled (or adjusted if paid) and the new lines are added.
- An item such as "7D Mat" without the words "floor mat" counts as Other.
- The staff PCs need the rebuilt program
  (`python scripts\build_payout_app.py`).

## [0.20.0] – 2026-10-05 – Monthly reports: client's changes to P&L, labour and vehicle tables

All of these are in both the Excel workbook and the PDF.

### Changed
- **Incentives are a direct cost.** The "Incentives" head typed on Monthly
  inputs is now shown under Direct costs in Profit & loss and Indirect vs
  direct, so Gross profit there is after incentives. Net profit is not
  affected by this move. The other reports (branches, products, vehicles,
  summary, trend) keep gross profit = sales − product cost − labour,
  because the incentive is one figure for the month and cannot be split.
- **Breakage / returns / transport (4%) and Compliance GST (3%) are now
  worked out on the product cost only**, not on product cost + labour.
  This applies to every month when it is generated again, and raises net
  profit by 7% of the month's labour.
- The words "(4% of COGS)" and "(3% of COGS)" are no longer printed beside
  those two heads.
- New-car business: "Cars that took DNS accessories" is now "Cars fitted
  with DNS accessories".
- **Labour calculation** is shown as separate tables – Floor mat and
  Sunfilm, each with its total – followed by the total labour. The table
  is picked from the item name; an item with labour that is neither goes
  to a table "Other", so the total always agrees.
- **Vehicle-wise, By segment:** "Counter sale (no vehicle)" and
  "(no segment)" are counted in the one line "Others".

## [0.19.2] – 2026-10-05 – Monthly reports PDF: pages are filled properly

### Fixed (monthly reports PDF only; the Excel workbook is unchanged)
- Pages ended too early, so a small table could sit alone on a page while
  the page before it was half empty (for example "By account deposited to"
  on a page of its own after "Payment mode analysis – By mode"). The tool
  guessed about 32 lines to a page; a page really holds about 40. The PDF
  is now printed at a fixed size worked out from the column widths, so the
  tool knows exactly how much fits and starts a new page only when the next
  heading-and-table truly does not fit. The PDF has fewer pages.
- The rule from v0.19.1 still holds: a heading is never separated from its
  table.

## [0.19.1] – 2026-10-05 – Monthly reports PDF: a heading stays with its table

### Fixed (monthly reports PDF only)
- A section heading could be left at the foot of a page with its table on
  the next page. A heading and the table under it now always stay together:
  when they do not fit in what is left of a page, both start the next page.
  This can leave blank space at the foot of a page; only a table longer
  than a whole page continues across pages.

## [0.19.0] – 2026-10-05 – Monthly reports PDF: the client's order, no descriptions

### Changed (monthly reports PDF only; the Excel workbook is unchanged)
- **New order, from the client's note** – Profit & loss is now the first
  page, followed by: New-car business (five lines: cars delivered, cars
  that took DNS, penetration %, DNS value as per list, DNS value per car
  delivered) · Top 10 products and top 10 services by gross profit ·
  Penetration by location · OE accessories by location and by model ·
  Branches by gross profit · Packages vs sales · Labour calculation ·
  Vehicle-wise average per car · Spot incentive · Payment modes.
- **No descriptions under the headings** (e.g. "Labour cost = labour charge
  in the Product master × quantity…") and no "Prepared on … by …" line:
  each section shows its heading, the month and the table.
- **Removed from the PDF**: headline figures and the rest of the executive
  summary, Service vs product, Indirect vs direct, New-car vs other, DNS
  penetration by model, Trend.
- The top 10 products / services are ranked by **gross profit** again (in
  v0.11.1 they were ranked by margin %); branches likewise.

### Added
- "Packages vs sales" in the PDF: each package's count and sales against
  the month's total sales.

## [0.18.1] – 2026-10-05 – Payout app build: fix for the first Windows build

### Fixed
- **The build failed its own PDF check on Windows, and "Staff guide.pdf"
  had no readable text.** One cause: the build script switched Qt to its
  "offscreen" mode to write the guide, and on Windows that mode has no
  fonts; the built program was then started with the same setting, so the
  test PDF it writes for its self-check had no text either. The invoice
  PDF reader itself was not at fault. On Windows the script now uses Qt's
  normal mode for the guide and starts the built program without the
  setting. The guide is read back after writing and reported if it has
  no text.

## [0.18.0] – 2026-10-05 – Payout app: the program for the staff PCs

### Added
- **Build script** `python scripts\build_payout_app.py` (on Brinda's
  Windows PC): makes `dist\Drive N Style Payouts\` with
  `Drive N Style Payouts.exe`, and the same folder zipped. A staff PC
  (Windows 10) needs nothing else installed. A folder, not one big .exe:
  it starts in a second or two and raises fewer antivirus false alarms.
- **Travels inside the program**: the app's Google key file and the links
  of the masters sheet and the payout register (taken from the build PC's
  settings), so staff only sign in and choose the invoice folder. The
  links are defaults - a PC's own setting wins. The key is still never
  committed to Git.
- **The built program checks itself** (`--check`): opens the app unseen,
  finds the theme pictures and the Google key, loads Google's libraries
  for Sheets and Drive, writes and reads back a test PDF, and confirms
  the sheet links are built in. The build script runs it and refuses to
  zip a build that fails.
- **Staff guide** (`docs/payout_app_staff_guide.md`), put into the program
  folder as "Staff guide.pdf": first time on a PC, every day, rules,
  weekly sign-in, what to do when something goes wrong.
- **Error log**: an unexpected error is saved to
  `payout_app_errors.log` in the PC's data folder and a message box says
  where - the installed program has no command window to show it.
- App icon (window and .exe); `payout_main.py` as the build's entry point.

### Changed
- `requirements-dev.txt`: `pyinstaller`.

### Pending
- The build was tried on Linux only (it built, and the built program
  passed its self-check). **The first Windows build is Brinda's.**
- The program is not signed, so Windows shows "Windows protected your PC"
  once per PC (More info → Run anyway).
- Google sign-in is asked again every 7 days (Brinda, 05-10-2026: accepted
  for now; publishing the Google project later removes it without a new
  build).

## [0.17.1] – 2026-10-05 – Payout app: a clean start for the Google Sheets

Brinda asked for the trial data and extra sheets to be cleaned up before
the installer is made. Both are on Set-up, under "Housekeeping (owner only)".

### Added
- **Clear the register…** empties the Payouts, Invoices and Log tabs
  (headings stay): every trial line, test payment and invoice read.
  Matches, Setup (proofs folder) and Summary are kept. A **backup copy** of
  the register is made first in the owner's Drive
  ("… - backup dd-mm-yyyy hh.mm"); the word CLEAR must be typed; only the
  register's owner can do it. The fresh Log starts with one line saying
  who cleared it and where the backup is.
- **Find duplicate sheets…** lists the owner's files named like the masters
  sheet, the register or the proofs folder, with the ones this PC uses
  marked "in use". Ticked extras are moved to Google Drive's **trash** (kept
  30 days); a file in use can never be ticked. Logged.

### Pending
- After clearing, every PDF counts as new: set the start date on Set-up to
  the go-live date before the next scan.
- Test proof files already uploaded stay in the proofs folder (delete them
  in Google Drive if wanted).

## [0.17.0] – 2026-10-05 – Payout app, step 4b: Payouts, proofs, payout slip, History

### Added
- **Payouts screen**: the register's lines with filters (status, type,
  payee, search) and three tiles (waiting to be paid, on hold, paid
  today). Tick the lines paid together and **Record payment…**: paid
  date, mode, reference, proof file, remarks. One reference and one proof
  can cover many lines.
- **Rules**: a payment needs a **reference or a proof**; the paid date
  cannot be in the future; only Pending / Hold lines can be paid, and if
  one ticked line has meanwhile been paid or cancelled nothing at all is
  recorded. Only the payment columns are written - never a calculated one.
- **Proofs in one shared Google Drive folder** ("Drive N Style Payout
  Proofs", Brinda's choice A). The owner creates it once from Set-up; it is
  noted in the register's new **Setup** tab, so the other PCs find it by
  themselves. A proof (picture or PDF, up to 10 MB) is uploaded under a
  telling name, e.g. `2026-10-05_GPay_UTR123_Kumaran.jpg`, and its link is
  written on every line it covers. "Open proof" shows it.
- **Hold… / Release** (reason required to hold) and **Reopen…** (reason
  required): a recorded payment is corrected by reopening it - the line is
  Pending again and what it held stays in the Log.
- **Payout slip…**: one block per payee with its invoices and total -
  either everything waiting to be paid, or what was paid on a chosen day.
  Shown on screen; "Save as PDF…" writes an A4 PDF.
- **History screen**: the register's Log, newest first, with search.
- Set-up: "Create the proofs folder"; "Save and check" also checks that
  the proofs folder can be opened.

### Fixed
- **Crash now and then when a background step finished** (v0.16.0): the
  worker object could be destroyed from two threads. The background
  thread is now one object that lives, and is deleted, on the screen's
  thread only. Found by running the screen tests repeatedly (3 crashes
  in 6 runs before, none in 25 after).

### Changed
- The register has a new tab **Setup**. A register created with v0.15.0 /
  v0.16.0 gets it automatically when the proofs folder is created.
- Tests: the stand-ins for Google moved to `tests/fakes.py`.

### Pending
- The Drive calls (create folder, upload) have not yet been run with a
  real sign-in - the first real upload is Brinda's.
- Installer for the staff PCs; publish the Google app vs service account.

## [0.16.0] – 2026-10-05 – Payout app, step 4a: the app window (Scan, Review, Set-up)

The daily payout app now has its own window: `python -m payout_app`.
Same blue theme as the monthly tool, which is **unchanged**.

### Added
- **Set-up screen** (once per PC): Google sign-in / sign-out, the links of
  the masters sheet and the payout register with "Save and check" (really
  opens both and reports the result), "Create a new register", the invoice
  folder and an optional start date.
- **Scan screen**: "Scan now" with progress, tiles (Posted now / Already
  posted / In review / Re-issued / Not used) that add up to the PDF files,
  messages (anything that stopped the run, hand edits put back, payments
  without reference or proof, files not used) and the lines just posted
  with their workings. **Trial run** writes nothing.
- **Review screen**: each unknown name ONCE with the invoices it holds up.
  For the selected row: choose the master record (likely ones first) or
  "Others" and "Save match and scan again"; or **cancel an invoice** with a
  reason (unpaid lines are cancelled, paid lines left alone and named).
  **Copy matches from the monthly tool** lists that tool's saved matches
  on the same PC; only the ticked ones are copied.
- `payout_app/service.py`: the scan, save-match and cancel actions in one
  place, used by the screens and the commands alike.
- **Two PCs scanning at once**: the register is read again just before
  writing and the plan remade if another PC has posted meanwhile.
- PDFs unchanged since the last scan in the same session are not read
  again (a scan after fixing a match is immediate).

### Changed
- **Google sign-in opens in Microsoft Edge** when installed (other Google
  accounts usually live in Chrome). Ctrl+C during a sign-in from the
  command window now ends with a plain message.
- **Google permission widened to Drive** (was: only files made by the
  app). Needed for payment proofs in ONE shared folder (Brinda's choice
  A). **Everyone signs in once more**; the older sign-in is noticed and
  asked for again automatically.
- `Sidebar` takes an optional subtitle (the payout app shows "Daily
  payouts"); the monthly tool's sidebar is as before.

### Pending
- Payouts screen (recording payments, proofs upload, payout slip) and
  History - next version. Until then payments are typed in the register.
- Screens were tested without a display against a stand-in for Google;
  the first run on a real screen with real Google is Brinda's.

## [0.15.0] – 2026-10-05 – Payout app, step 3: scan, calculate, post to the register

The engine of the daily payout app, used through commands for now (screens
come next). The monthly reports tool is **unchanged**.

### Added
- **Payout register Google Sheet "Drive N Style Payout Register"** with the
  tabs Payouts (one row per payout line: calculated columns, then Status /
  Paid date / Mode / Reference / Proof / Remarks for the staff), Invoices
  (every invoice seen and its state), Matches, Log and Summary (live
  totals by payee and by month).
- **Calculation from the invoice PDFs** (`payout_app/engine.py`) with the
  monthly tool's own matching and valuation code: one Labour line per
  invoice, one Spot incentive line for the sales executive (discount rule,
  packages, "Gets incentive = No", "Others"), one Internal team line (car
  PPF). Exact amounts - no rounding. Every line shows its working.
- **Posting rules** (`payout_app/register.py`): an invoice is posted once
  and never calculated again, so a master changed later cannot alter a
  posted line; an invoice that cannot be calculated is recorded "In review"
  with the reasons and retried on every scan; a **re-issued** invoice (same
  number, PDF says something else) corrects unpaid lines in place and adds
  **adjustment lines** for lines already paid; an invoice marked Cancelled
  in the Invoices tab is never posted. The tally always adds up.
- **Lines changed by hand are put back**: each payout row carries a hidden
  sealed copy of its calculated cells; every scan compares, restores and
  logs. Calculated columns also show Google's "protected cell" warning.
  A line marked Paid without reference or proof is listed as a warning.
- **Saved matches** (Matches tab): a printed item / salesperson / car name
  matched to a master record, or to "Others", used by every PC.
- **Commands**: `python -m payout_app.payout_cli create-register |
  use-register <link> | scan "<folder>" [--dry-run] [--from dd-mm-yyyy] |
  status`.

### Pending
- Screens (Scan, Review, Payouts, History); recording payments and
  uploading proofs from the app; cancelling an invoice from the app (for
  now: type Cancelled in the Invoices tab's State column).
- Every scan reads every PDF in the folder (about 1 second per 12 files);
  keep one folder per month, or this will be made smarter later.
- Two PCs scanning at the very same moment could post an invoice twice;
  the next scan reports the duplicate line. To be closed with the screens.

## [0.14.0] – 2026-10-05 – Payout app, step 2: the masters as a Google Sheet

First part of the separate **daily payout app** (`payout_app/`). The
monthly reports tool is **unchanged** and keeps its own masters for now.

### Added
- **`payout_app/` package** in this repository. It imports the invoice
  reader, the matching rules and the incentive calculation from `app/data`
  and `app/reports`, so both apps always use the same rules.
- **Masters Google Sheet "Drive N Style Masters"**: one tab per master
  (Products, Sales executives, Cars, Incentives, Packages) plus Settings.
  A rate change is a NEW ROW with the same name and a later "Effective
  from" date, so an invoice already calculated never changes. Yes/No and
  Category cells are drop-downs; headings are frozen.
- **Validate on read**: every read of the sheet runs the monthly tool's own
  master checks (duplicates, 10-digit mobiles, unknown incentive group,
  package item not in Products, required cells, negative amounts) and
  checks every amount, Yes/No and date cell. Each problem names its tab
  and row. If there is any problem, nothing from the sheet is used.
- **Last good copy**: a successful read is kept on the PC and used, with a
  note, only when the sheet cannot be reached.
- **Commands** (until the app has screens):
  `python -m payout_app.masters_cli create | check | use <link> | preview`.
- **Google sign-in** in the browser, once per PC (`payout_app/google_api.py`).
- `MastersRepo.find_id` (small helper used when loading the sheet).

### Changed
- `requirements.txt`: `google-api-python-client`, `google-auth-oauthlib`.
  Run `pip install -r requirements.txt` once.

### Pending
- The Google calls were written and tested from Linux against a stand-in
  and against Google's own request builder, but **not yet run with a real
  sign-in** - the first real run is `create` on Brinda's PC.
- The Google project is in "Testing": sign-in is asked again every 7 days
  until it is published (needs a homepage and privacy policy link) or the
  app is moved to a service account. To decide before go-live.
- Monthly tool to read the same sheet (later version); Zoho item import to
  write into the sheet.

## [0.13.0] – 2026-10-05 – PDF reader brought up to date (for the daily payout app)

The monthly reports read Zoho's export and are **unchanged**. This version
prepares the PDF reader for the separate daily labour / incentive payout
app, which will read the invoice PDFs the staff save in a folder. Tested
on the 126 September PDFs against the September export: every invoice
reads, and item names, quantities, line amounts, discounts, totals and
the amount billed per line agree.

### Added
- **Note under an item is kept apart from the item name.** Zoho prints the
  item name in black and a typed note ("BOOT LIGHT", "SIDE & REAR") in
  grey; the note was read as part of the name, so the item could not match
  the Product master (3 invoices in September). It is now stored as the
  line's note.
- **"Branch" line** printed on newer invoices is read (stored only, as for
  the export's CF.Branch).
- **Amount billed per line without splitting GST** (`billed_lines`,
  `discount_base` in `app/data/invoices_repo.py`): line amount × (1 −
  discount ÷ value the discount applies on). This is the figure the spot
  incentive rule uses; it is right for invoices with a mix of taxed and
  untaxed lines too.
- **Test: PDFs against the export** – set `DNS_SAMPLE_EXPORT` to the
  Invoice.csv of the same period (with `DNS_SAMPLE_INVOICES`).

### Fixed
- **Invoices with GST on only some lines no longer fail the totals check**
  (DNS-237-2627, DNS-313-2627). They are accepted when Zoho's printed
  figures still agree: "Applied on" value − discount + GST + rounding (or,
  with no discount, Sub Total + rounding) = Total. A real difference is
  still reported.

### Pending
- Not printed on the PDF, so the daily app must handle them itself: SKU
  (items match by name), payment mode, and whether an invoice was
  cancelled or edited later in Zoho.

## [0.12.1] – 2026-10-04 – Incentive rounded up to the next ₹10

### Changed
- **Each executive's spot incentive for the month is rounded UP to the next
  ₹10** (1,492 → 1,500; 2,677.80 → 2,680; an exact multiple of 10 is
  unchanged). The rounding is done once on the executive's total: the "By
  executive" table of the Spot incentive sheet, the Incentive payable
  column of Executive-wise sales, the Summary, the Trend and the PDF. The
  line-by-line detail keeps the exact amounts, so the working is visible.
  The discount rule itself is unchanged.

## [0.12.0] – 2026-10-04 – Internal team incentive (₹3,000 per car PPF)

### Added
- **Product master: "Internal incentive (₹)"** – an amount per unit that
  goes to the internal team when the item is sold, in addition to the
  salesperson's spot incentive. Paid in full whatever the discount, also
  when the item is part of a package, and whoever the salesperson is.
- **Spot incentive sheet**: a separate line **"Internal team"** in "By
  executive" (not split by person), with one detail row per qualifying
  item. The PDF shows it as the last line of the by-executive table.
  The Summary's Costs table and the Trend sheet show "Internal team
  incentive" separately.
- **Upgrade (schema 12)**: car PPF items already in the tool are set to
  ₹3,000; two-wheeler PPF items get no internal incentive and their
  Incentive group is cleared, so they earn no incentive at all (client's
  rule). Each change is in the audit log.

## [0.11.1] – 2026-10-04 – PDF: top lists ranked by profit margin %

### Changed (PDF only)
- At the client's request the Summary's top 5 products, top 5 sales
  executives and branches, and the High-profit top 10 products / services,
  are now **ranked by profit margin %** (not chosen by gross profit and
  then re-ordered). Headings read "… by profit margin %". Equal margins
  are ordered by gross profit. The Excel workbook still ranks by gross
  profit.

## [0.11.0] – 2026-10-04 – "Gets incentive" flag; PDF margin % highest first

### Added
- **Sales executive master: "Gets incentive" (Yes / No, default Yes).** The
  client said Mano Vikram and Nandha Kumar do not get incentives. For an
  executive marked No, the sales count everywhere as before, but no spot
  incentive is worked out (items or packages): they do not appear on the
  Spot incentive sheet (a note names them), and their incentive is nil in
  Executive-wise sales, the Summary, the Trend, the scorecard and the PDF.
  The flag can be set on the Masters screen or imported; changes are in
  the audit log. Database schema version 11.

### Changed (PDF only)
- Tables with a Margin % column are listed highest margin first: the
  Summary's top 5 products, top 5 sales executives and branches (still
  chosen by gross profit), the High-profit top 10s and New-car vs other.
  The Summary's Costs table runs from the highest % of sales.

## [0.10.5] – 2026-10-04 – PDF: no cover block; percentages highest first

### Changed (PDF only; the Excel workbook is unchanged)
- The opening block "Drive N Style – Monthly reports … Notes" is no longer
  in the PDF; it starts with the Executive summary.
- Where a table's point is a percentage, its rows now run from the highest
  to the lowest: indirect cost heads in Indirect vs direct and Profit &
  loss (typed and automatic heads together, largest first), payment modes
  by % of invoice total, and penetration % by location / model (Summary and
  New-car penetration). Rankings by an amount keep their order (top lists by
  gross profit, spot incentive by incentive payable, labour, segments).

## [0.10.4] – 2026-10-04 – PDF: wrong "% of sales" fixed

### Fixed
- **PDF only**: in Profit & loss and Indirect vs direct, the "% of sales"
  column divided by the wrong figure (sales showed 189.2%, product cost
  79.5%). When the sections were joined into one document in v0.10.3, the
  formulas' fixed references to the Sales row were not moved with the
  table. They now move with it; the percentages match the Excel workbook
  (100.0%, 42.0% ...). All amounts were always correct; the Excel workbook
  was never affected.

## [0.10.3] – 2026-10-04 – PDF without graphs, no empty space, page numbers, readable print

### Changed (PDF only; the Excel workbook is unchanged)
- **All graphs removed** from the PDF. (The Excel Trend sheet keeps its
  charts.)
- **No empty space**: the sections now follow one another on one continuous
  document instead of one section per page; a new page starts only when
  the page is full.
- **Footer on every page**: "Drive N Style - <month>" on the left and
  "Page x of y" on the right.
- **Print size**: A4 landscape at (or very near) full size, so the 10 pt
  text prints at about 10 pt. To make that possible the New-car penetration
  table is shown as two tables with the same figures (DNS accessories, then
  OE accessories) and no table is wider than eight columns.

## [0.10.2] – 2026-10-04 – Change a saved match; delete a dated price; History columns

### Added
- **Scan review → Saved matches → "Change selected match"**: point a saved
  match at a different product / executive / car (or Others) in one step.
  Logged with the old and new target.
- **Masters → Rate history → "Delete selected date"**: remove one dated set
  of amounts (e.g. a price saved with a wrong date); the earlier amounts
  apply again. The last remaining date cannot be removed. Logged. Not
  offered while the tab has unsaved edits.

### Fixed
- **History**: the Month column was cut to "S…" and "Generated on" was
  truncated; every column now fits its contents.

## [0.10.1] – 2026-10-04 – Remove a month; remove a History entry

### Added
- **History → "Months read into the tool"**: every month whose invoices
  are in the tool (and so in the trend), with the number of invoices, when
  it was last read and from which file. **Remove month** takes the month's
  invoices out after a confirmation: invoices and lines, the files-read
  list, single-invoice choices, accepted totals differences and the
  month's delivery-list totals. Masters, name matches for all invoices,
  Monthly inputs and saved workbooks are kept. Logged in the audit log.
- **History → Remove** on a generated workbook: takes the month out of the
  History list; the Excel / PDF files are not deleted. Logged.
- History refreshes when a month's invoices are read.

## [0.10.0] – 2026-10-04 – PDF version with graphs; month-wise trend

### Changed
- **The PDF is now a separate "PDF version"** of the reports, for reading
  (Brinda, 04-10-2026); the Excel workbook is unchanged. It holds, one
  section per page, with colourful graphs:
  Cover · Summary (without "Points needing attention") · Service vs product
  (summary) · Labour (by product) · Vehicle-wise (by segment) · Spot
  incentive (by executive, highest payable first) · High-profit (top 10
  products, top 10 services) · Indirect vs direct · Payment modes (by mode,
  by account deposited to) · Profit & loss · New-car penetration · New-car
  vs other (where the business came from) · Trend (two or more months).
  Left out of the PDF: invoice profitability, packages, executive-wise
  sales, missed opportunity, RTO list vs invoices, consultant scorecard,
  not included (`app/reports/pdf_book.py`).
- **History → PDF** builds this PDF from the data as it is now.
- **Trend sheet rebuilt** (workbook sheet "4 Trend" and the PDF's Trend
  page, `app/reports/trend.py`): per month and in total – invoices, sales,
  product / service sales, costs, gross profit and margin, indirect costs,
  net profit and margin, average bill, packages, spot incentive, cars
  delivered, cars that took DNS and penetration %; change from the previous
  month; sales by branch; top 10 products; a line chart and a penetration
  chart.

### Added
- The delivery (RTO) list's totals are kept for each month when a workbook
  is generated with the list, so the trend can show penetration month by
  month (database schema version 10, table `rto_months`).

## [0.9.1] – 2026-10-03 – The workbook as one PDF

### Added
- **"Also save as PDF"** on Generate reports (under Save to): one PDF with
  every sheet, saved beside the workbook with the same name. Each sheet
  starts on a new page, landscape, fitted to the page width; long sheets
  continue on further pages with their headings repeated.
- **PDF button on History** for a workbook already generated.
- The PDF is made by Microsoft Excel on the PC (driven through Windows
  PowerShell, no extra software), so it shows exactly what the workbook
  shows. If Excel is missing or the PDF is open elsewhere, the workbook is
  still saved and a plain message says why the PDF was not made
  (`app/reports/pdf_export.py`).

### Changed
- Every sheet is set up for A4 with narrow margins and a footer
  "sheet name - page x of y"; this also applies when printing from Excel.

## [0.9.0] – 2026-10-03 – Delivery (RTO) list, new-car reports, executive summary

### Added
- **Delivery (RTO) list as a third file** on Generate reports (step 4,
  optional): the dealership's monthly list of cars delivered, with OE and
  DNS accessories per car (`app/data/rto_list.py`). Each car is linked to
  its invoices by the last six digits of the VIN.
- **Five new sheets when the list is given** (`app/reports/rto_reports.py`):
  - 13 New-car penetration – cars delivered vs cars that took DNS
    accessories, OE vs DNS value, by location and by model.
  - 14 Missed opportunity – delivered cars without DNS accessories, with
    the remark given, and a count by remark.
  - 15 RTO list vs invoices – the list's DNS value against what was
    invoiced, car by car; differences first.
  - 16 New-car vs other – sales and profit from delivered cars against all
    other business; profit per car by model and by location.
  - 17 Consultant scorecard – cars delivered, converted, value, profit, and
    the list's Executive Incentive next to the tool's calculation.
- **"Summary" sheet (executive summary)**, always written, right after the
  Cover: headline figures with last month's where available, new-car
  business, penetration by location, top products / executives / branches,
  packages, costs, and points needing attention in plain sentences.
- History's Regenerate uses the same delivery list again (database schema
  version 9: `report_runs.rto_path`).

## [0.8.3] – 2026-10-03 – Saved matches: see and undo Scan review choices

### Added
- **Scan review → "Saved matches" tab.** Lists every choice saved on the
  Issues tab - item, salesperson or vehicle matched to a master row or to
  Others, single-invoice choices, and totals differences accepted - with
  what it was matched to, whether it applies to all invoices or one, how
  many of the month's invoices it touches, and when it was saved.
- **Remove selected match** undoes one choice after a confirmation. The
  invoices are matched again from the masters and return to the Issues tab
  if they still do not match. Each removal is in the audit log.
- **Export matches** saves the list to Excel for checking.

## [0.8.2] – 2026-10-03 – Automatic indirect cost percentages can be changed

### Added
- **Monthly inputs → Report settings** has the two percentages of COGS:
  Breakage / returns / transport (4%) and Compliance GST (3%). They are
  one setting for all months; a change is recorded in the audit log and is
  used by every report generated afterwards, including earlier months.

## [0.8.1] – 2026-10-03 – Automatic indirect costs (4% and 3% of COGS)

### Added
- **Two indirect costs are calculated automatically every month** (Brinda,
  03-10-2026): Breakage / returns / transport = 4% of COGS and Compliance
  GST = 3% of COGS, where COGS = product cost + labour. They appear under
  Indirect costs in report 10 (Indirect vs direct cost %) and report 12
  (Profit & loss) as Excel formulas on "Total direct costs", and apply to
  earlier months too when their reports are generated again.
- A head typed on Monthly inputs whose name contains "breakage" or
  "compliance" is left out of the reports, so it is not counted twice.
- Monthly inputs shows a note about the two automatic heads.

## [0.8.0] – 2026-10-03 – Package sales recognised from the invoice

### Added
- **Packages master** (Masters → Packages; replaces the sample tab). One
  row = a Zoho item that counts as an item of a package (Package, Package
  item, Zoho item name). It can be typed in or imported from Excel; the
  Zoho item must exist in the Product master. Changes are in the audit log.
- **Package recognition**: an invoice is a package sale when every item of
  a package is on it (rule given by Brinda). If two packages fit, the one
  with the higher coupon value is taken. One package per invoice; other
  items on the invoice stay normal sales.
- **Report 5 "Basic package analysis" rewritten**: by package; one row per
  package invoice (list value, coupon value, amount billed, discount given
  against the coupon discount, cost, labour, profit, package incentive and
  incentive payable); the package items as billed; and "Almost a package"
  (exactly one item missing) for checking with the client. The sheet
  carries the date and time of the result.
- **Report file name carries date and time**, e.g.
  `DriveNStyle_Sep-2026_Reports_03-10-2026_2122.xlsx`, so every result is
  kept and none is overwritten.

### Changed
- **Spot incentive**: on a package invoice the package's items earn no
  separate incentive; the invoice gets one row with the package incentive
  (Incentive master row of the same name; its Bill value is the coupon's
  final value). The confirmed discount rule applies to it as to any line.
- A product linked to a "… Package" incentive group is no longer treated
  as a package sale by itself.
- Database schema version 8 (`package_items` table).

## [0.7.1] – 2026-10-03 – "Others" for salesperson and car; Zoho prices from 1 April

### Added
- **"Others (not in master)" on Scan review** for a salesperson or vehicle
  that is not in the masters. Choosing it closes the issue, so the invoice
  goes into the reports instead of being left out. In the reports the
  salesperson / car reads "Others"; the branch is the one on the invoice;
  incentive is still calculated and shown under Others. The Invoice
  register also shows the name printed on the invoice, e.g.
  "Others (DOST - AUTO)". Every such choice is in the audit log.
  Items have no "Others" (without a product there is no cost or labour).

### Changed
- **A Zoho item list import now applies from the start of the financial
  year** (1 April) by default, not from next month, and Zoho's prices are
  final from that date onwards: later dated amounts for the same product
  are removed. Labour charges are kept. (In v0.7.0 the import was dated
  1 November, so September still used the staff sheet's prices for items
  that were already in the tool.)

## [0.7.0] – 2026-10-03 – Zoho's item list is the Product master

### Added
- **Zoho's item export (`Item.csv`) is imported as the Product master**
  (Masters → Products → Import Excel). It is recognised by its headings and
  the columns are pre-set: Item Name → Product name, SKU, HSN/SAC, Rate →
  Selling price, Purchase Rate → Cost price, Product Type (goods / service)
  → Category. "INR 14000.00" is read as an amount.
- Zoho decides **names, prices and category**. Labour charge, incentive
  group and "Vehicle needed" are not in Zoho and keep their values.
- The **₹1 labour items** in Zoho's list are left out (not products), now
  including "Paint Protection Film -Labour Charges".
- **Products not in Zoho's list** are shown after the import and removed on
  confirmation (each removal in the audit log).
- **"Add items that are not in the Product master"** tick box in the Import
  window (products): untick it when importing the staff sheet for labour /
  incentive, so its own item names are not added back.
- Tests for the Zoho import (139 tests).

### Fixed
- A labour charge imported for an EXISTING product did not switch on
  "Labour involved", so that labour was not counted.

## [0.6.7] – 2026-09-30 – Counter sales without a vehicle

### Added
- **"Vehicle needed" (Yes / No) on the Product master.** An invoice with no
  vehicle is accepted when every item on it is "No" (counter items such as
  Turtle Wax perfume, shampoo, glass cleaner, microfiber cloth); it shows in
  the reports as "Counter sale (no vehicle)". A car job billed without a
  vehicle is still flagged on Scan review.
- Default "No" for counter items (words: perfume, shampoo, glass cleaner,
  microfiber, acrylic trim, flex wax, glue remover, compound, Max Power car
  wash) when a product is added without a "Vehicle needed" column, and once
  for existing products on upgrade (database schema 7, each change in the
  audit log, source "Upgrade v0.6.7"). Can be changed on the Masters screen
  or with a "Vehicle needed" column in the client's sheet.
- 4 tests (132 tests).

## [0.6.6] – 2026-09-30 – Spot incentive rule confirmed

### Changed
- The client confirmed the spot incentive rule (incentive × amount billed ÷
  bill value, capped at the full incentive). Report 7 no longer carries the
  PROVISIONAL banner, the cover note is removed and report 8's column is
  "Incentive payable". The calculation is unchanged.

### Pending
- Products must be linked to incentive groups for report 7 to show
  anything (the items sheet has no incentive group column). Draft links for
  83 of 191 items sent to the client for confirmation.

## [0.6.5] – 2026-09-29 – Client's category column; repeated CODEs

### Added
- **The client's category column** in the items sheet is read: SALES →
  Product, SERVICE → Service (heading "category" is matched automatically).
- **A category from the sheet, or chosen on the Masters screen, is final**:
  Zoho's goods / service type never changes it (new `products.category_fixed`,
  database schema 6, filled from the audit log for existing products).
  Products without a sheet category still follow Zoho's item type.

### Fixed
- **Rows lost on import when several items shared one CODE** (the client's
  sheet has HSN codes such as 87089900 typed as the CODE of up to four
  items): each such row overwrote the previous one and only the last
  survived. Now a CODE used for different item names in one file is
  dropped for those rows; each is imported as its own item (matched by
  name) and a warning lists them. Pricelist 3: 191 of 191 rows imported,
  8 previously lost.
- Tests for both (128 tests).

## [0.6.4] – 2026-09-29 – Import window fits the screen

### Fixed
- **Import window taller than the screen**: on a laptop with Windows zoom
  at 125–150 % the Import button was pushed off the bottom and the window
  could not scroll, so masters could not be loaded. The column matching,
  preview and problem list now scroll inside the window; Cancel / Import
  stay fixed at the bottom; the window never opens taller than the screen.
- Same for the Edit form (sized to its fields, capped at the screen).
- Drop-downs and the date box in these windows ignore the mouse wheel until
  clicked, so scrolling the window cannot change a column match by
  accident.

### Added
- `scroll_body`, `fit_to_screen`, `NoWheelComboBox`, `NoWheelDateEdit` in
  `app/widgets/common.py` for any pop-up window.

## [0.6.3] – 2026-09-29 – ₹1 labour lines ignored

### Changed
- **₹1 labour marker lines are ignored** (confirmed by the client): no more
  "Labour line" rows in the reports, and their small value (about ₹0.85
  each after discount and GST) is not in sales. The cover sheet shows how
  many were ignored and their value (September: 40 lines, ₹36.82), with a
  note that sales are therefore slightly below the invoice totals.
- **Labour comes from the product only**: labour charge × quantity for
  products marked "Labour involved" in the Product master (unchanged
  calculation; the labour sheet now says the marker lines are not used).
- Report 2 summary shows Product and Service only.

### Removed
- The Scan review check "labour line but no product on this invoice has
  labour" - it no longer applies, and invoices it held back are now
  included. ("Labour line" issues are no longer exported either.)

## [0.6.2] – 2026-09-29 – Export issues

### Added
- **Export issues** button on Scan review (`app/reports/issues_export.py`):
  saves the month's OPEN issues as `DriveNStyle_<Mon>-<YYYY>_Issues.xlsx`,
  a question list for the client. Sheet "Issues": Type, As printed on the
  invoice, Issue, Invoices, Invoice numbers, **What we need** (plain request
  per kind of issue, e.g. "give the contact no and branch") and a blank
  **Client's reply** column. Sheet "Invoices affected": invoice no, date,
  customer, salesperson, vehicle, total and its issues. Same look as the
  reports workbook. Disabled when nothing is open.
- Issues now carry the reason a salesperson / vehicle was not matched
  (not found / other branch / several / not printed).
- Tests for the export (123 tests).

### Fixed
- Quantities in the reports workbook showed a trailing dot ("9.", "108.");
  they now show as 9, 108 (and 1.5 where not whole).

### Pending
- How the ₹1 labour marker lines should appear in the product reports
  (hide / add to the main product / group) – Brinda to confirm.

## [0.6.1] – 2026-09-28 – Faster Scan review and Masters

### Changed
- **Scan review lists an unknown salesperson (or vehicle) once**, with all
  the invoices showing that name ("Mano Vikram – 29 invoices"), like unknown
  items. One choice fixes all of them and is remembered for later months.
  Ambiguous or missing names stay one row per invoice. On the September
  data: 95 rows → 43.
- **Fix controls appear only on the clicked row**; other rows are plain
  text ("Click to choose the executive"). Status is coloured text instead
  of a small widget. The issues table scrolls on its own (10 rows visible).
- **Saving a master no longer rebuilds Scan review in the background**; it
  is rebuilt when next opened (the sidebar badge is still updated).

### Fixed
- Lag when scrolling Scan review and when editing / saving masters after
  the invoices were read (September data: Scan review build 1.5 s → 0.1 s;
  side effect of each master save 1.2 s → 0.03 s).
- Closing the app referred to the PDF background reader removed in
  v0.6.0 and could raise an error.

## [0.6.0] – 2026-09-28 – Zoho invoice export

### Added
- **Invoices from Zoho's invoice export** (`app/data/invoice_export.py`):
  Generate step 2 is now "Invoice export (.csv / .xlsx)" and the button
  "Read invoices". One row per line is grouped into one invoice per number;
  only the chosen month is kept (other months are counted and ignored, so a
  quarter's export works). Void / Draft and other-GSTIN invoices are listed
  as skipped. A file that is not a Zoho invoice export is refused with the
  missing columns named.
- Zoho's per-line **`Item Total`** (after discount, without GST) and
  **`Item Tax Amount`** are stored as they are - no allocation needed.
  Check per invoice: lines + GST + round-off = Total (within ₹1), plus a
  check that invoice-level columns agree on every line.
- **Category from Zoho's Item Type** (decision A): products whose Category
  was never set by hand take goods → Product / service → Service, applied
  after reading, after mapping an item on Scan review and before
  generating. A Category changed on the Masters screen or by import is
  never overridden. Every change is in the audit log (source "Invoice
  export (Zoho item type)").
- Stored for later use: invoice status (Closed / Overdue), `CF.Branch`,
  line item type. Payment made = Total − Balance.
- Database schema 5 (backup taken before upgrading): invoices.source /
  status / branch, invoice_lines.item_type.
- Tests for the export reader, checks, matching, categories and the
  Items.xlsx headings (118 tests).

### Changed
- **Payment mode fallback** (decision B): the export's `CF.Invoice Type`
  (UPI / Cash / CHY) is used in report 11 only where the Payments Received
  export has nothing for the invoice.
- **Labour markers** also include "Labour - …" ₹1 lines (e.g. "Labour -
  Seat Cover - Art Leather"), not only "Labour Charges …".
- **Salesperson matching** ignores spaces and dots ("Udhayakumar" =
  "UDHAYA KUMAR") and treats branch "Head Office" = "HO", "KTG" =
  "Kothagiri".
- Branch in reports stays the executive's branch from the master
  (decision C).
- Scan review "Open file" opens the export the month was read from.
- The PDF reader (`invoice_reader.py`, `scan_worker.py`) stays in the code
  but is no longer used on screen.

### Fixed
- **Items master import**: a "Labour" heading holding amounts was matched to
  the yes/no field Labour involved; it now goes to Labour charge (Labour
  involved = Yes when the charge is above zero). New headings recognised:
  "Sale with GST", "Purchase without GST" ("CODE" already was).
- "-", "Nil" or "NA" in an amount column now read as 0 instead of
  rejecting the row (the client's Labour column uses "-").
- A Category column holding notes (Items.xlsx "Product Type") no longer
  rejects the row; the note is ignored and the category worked out instead.

### Pending
- 7 Items rows are priced in words ("mrp less 10%", "DC Product…"); they are
  left out on import until the client gives amounts.
- Salespeople still not in the executive list, or at another branch (see
  CLAUDE.md), and the list's open points (a 9-digit number, missing
  branches).
- The client's actual spot incentive rule; package definitions.

## [0.5.0] – 2026-09-28 – The 12 reports

### Added
- **Excel workbook** `DriveNStyle_<Mon>-<YYYY>_Reports.xlsx` with a Cover,
  the 12 reports and a "Not included" sheet (`app/reports/`). Totals,
  gross profit, margins, averages, shares and summaries are live Excel
  formulas; Arial, navy headings, frozen headings, filters, landscape
  fit-to-width printing.
- **Figures**: sales after discount without GST (no-GST invoices in full);
  product cost and labour from the Product master at the rates on the
  invoice date; gross profit; invoices with open issues left out and
  listed with reasons.
- **Report 7 – spot incentive (provisional)**: incentive × (amount billed ÷
  bill value), capped at the full incentive; marked PROVISIONAL.
- **Report 5 – packages**: products whose incentive group is a
  "… Package".
- **Report 11 – payment modes** from Zoho's "Payments Received" export
  (`app/data/payments_io.py`): every payment applied to the month's
  invoices, split by mode and by account deposited to, with "Not received";
  falls back to the mode printed on the invoice.
- **Report 4 – trend** over every scanned month (up to 12).
- **Monthly inputs** saved per month in the database: indirect cost heads
  and amounts (copy from the previous month, usual heads to start), and the
  high-profit threshold. Unsaved-change warnings; changes in the audit log.
- **History** of generated workbooks with Open and Regenerate.
- Generate asks before writing if Scan review issues are open or no
  indirect costs were entered ("Enter them first" opens Monthly inputs on
  that month). "Open workbook" after generating.
- Database schema 4: monthly_costs, monthly_settings, report_runs.
- Tests for inputs, payments export, figures and the workbook (105 tests).

### Changed
- **Contact numbers must be 10-digit mobiles** (+91 / 91 / leading 0
  allowed). Shorter or longer numbers are refused on save and left out on
  import, with the row number.
- Sample indirect costs and history removed from `sample_data.py`.

### Pending
- The client's actual spot incentive rule (report 7 is provisional).
- Package definitions (which items make up each package), if the client
  wants a package's contents analysed.

## [0.4.0] – 2026-09-28 – Invoice reader and Scan review

### Added
- **Invoice reader** for the Carkrafts (Zoho) invoice format
  (`app/data/invoice_reader.py`). Works from word positions on the page, so
  the two-column header, wrapped item descriptions and units ("1.00 no") are
  read correctly. Reads invoice number (all series: `DNS26-GST-`,
  `DNS26-GST1-`, `DNS-xxx-2627`…), dates, P.O.#, place of supply, salesperson,
  customer type, vehicle, VIN / registration, customer, items (description,
  HSN/SAC, qty, unit, rate, amount), Sub Total, discount and its base,
  CGST/SGST/IGST, rounding, total, payment made, balance due, and payment
  mode when printed.
- **Real scan** on Generate reports, in a background thread with per-file log
  (read / skipped / could not be read) and Cancel. Invoices outside the
  chosen month, another firm's GSTIN and repeated invoice numbers are
  skipped with the reason. The month's last scan is shown when the month is
  selected again.
- **Per-line amounts:** value before GST, share of the invoice discount, net
  value and GST for every line, saved at scan time for the reports.
  Invoices with no GST shown count in full as sales.
- **Arithmetic checks** on every invoice (lines = Sub Total; Sub Total before
  GST − discount + GST + rounding = Total, within ₹1).
- **Matching to the masters** every time issues are shown: items by name
  (then remembered mapping, then SKU), salesperson by name and branch
  ("Kumaran - HO"), vehicle by car model ignoring punctuation ("PUNCH.EV" =
  "Punch EV"). "Labour Charges for …" ₹1 lines are treated as labour markers.
- **Scan review rebuilt** on real data: tiles, Issues tab with a fix control
  per issue (searchable product / executive / car drop-downs, "All invoices"
  option, Accept, Open file), Fixed / Open / Skipped pills, and an
  **Invoices read** tab showing each invoice as understood. Items missing
  from the master are listed once with their invoice count.
- Fixes are saved immediately, kept when a month is re-scanned, and logged in
  the audit log (new "Scan review" filter). Adding a missing product or car
  on the Masters screen clears its issue at once.
- Database schema 3: invoices, invoice_lines, invoice_checks, scan_files,
  scan_runs, match_aliases, invoice_overrides, issue_acks.
- Tests for amounts, checks, matching, issues and fixes (85 tests), plus an
  optional test that reads real sample PDFs (`DNS_SAMPLE_INVOICES`).
- `pdfplumber` added to requirements.

### Fixed
- The invoice folder counted every PDF twice on Windows ("*.pdf" and
  "*.PDF" find the same files there). Files are now listed once.

### Changed
- Payment mode report note: uses the payment mode printed on the invoice,
  or the payments export where it is not printed.
- Scan review sample issues removed from `sample_data.py`.

### Pending
- Reports and the Excel workbook (v0.5.0).
- Spot incentive calculation: awaiting the client's rule.

## [0.3.0] – 2026-09-28 – Incentive master, bulk actions and audit log

### Added
- **Incentive master** (Product / Service, Incentive amount, Bill value,
  Active) in the client's sheet layout. Incentive amount and bill value keep
  a dated history like product rates.
- **Incentive group** on the Product master, chosen from the Incentive
  master (drop-down in the table and the Edit form; matched by name on
  import, unknown names are left blank and listed).
- **Audit log** of every master change: added, edited (field, old → new;
  amounts with their effective date), activated, deactivated, deleted
  (with everything the row held) and imported (source = file name), with
  date and time and Windows user name. Written in the same transaction as
  the change; database triggers refuse any edit or deletion of the log.
  New **Audit log** tab with filters (master, action, date range, text) and
  export to Excel.
- **Filters** on every master tab: a column filter (Products: category,
  Sales executives: branch, Cars: segment) and a status filter (active /
  inactive), working together with the search box.
- **Edit form** (Edit button) for the selected row of any master.
- **Selection column** with *Select all* (visible rows) and bulk actions:
  *Mark active*, *Mark inactive*, *Delete*, *Delete all* (type DELETE to
  confirm). Deleting an incentive group warns how many products use it and
  clears their incentive group.
- Duplicate check within a single save (two new rows with the same key).
- Safety copy of the database before a schema upgrade
  (`drivenstyle.schema1.bak.db`).
- Generate reports: "Masters in use" also shows incentive groups.
- Sample sheets: executive and incentive sheets in the client's layout;
  product sheet with an Incentive Group column.
- Tests for incentives, contact-number uniqueness, bulk actions, audit log
  and the upgrade from a v0.2.0 database (57 tests).

### Changed
- **Sales executive master** now follows the client's sheet: Name,
  **Contact no** (required), **Branch** (was City), Active. Executives are
  unique by contact number instead of name, so two people may share a name.
  Numbers are compared as digits (last 10), so `+91 98765 43210` and
  `9876543210` are the same.
- Database schema 2: existing executives are copied into the new layout
  (city → branch); remembered import matches are updated.
- *Remove* (mark inactive) replaced by the bulk actions above. Rows can now
  be deleted permanently; the audit log keeps what they held.
- Rate-change dialog and history now say "amount" (they cover incentives
  too).
- Ghost and Danger buttons have a visible disabled style.
- Masters repository rewritten as one engine for all four masters.

### Pending
- Spot incentive calculation: awaiting the client's rule.
- Packages tab still shows sample data.

## [0.2.0] – 2026-09-25 – Masters

### Added
- **Masters database** (SQLite, `app/data/`). Stored outside the program
  folder (`%LOCALAPPDATA%\Drive N Style Reports\drivenstyle.db`) so upgrades
  keep the data; schema versioning so later versions can upgrade it in place.
- **Product master:** SKU, product name, HSN/SAC, category (Product /
  Service), selling price, cost price, labour involved, labour charge,
  active.
- **Sales executive master:** name, phone, city, active.
- **Car master:** make, model, segment (suggested list, other values
  allowed), active.
- **Dated rate history** for selling price, cost price and labour charge.
  Changing a rate asks for the effective date; earlier months keep the old
  rate. New *Rate history* dialog. Months before a product's first rate use
  that first rate.
- **Import from Excel / CSV** with automatic heading-row detection (works
  below a title row), suggested column matches from common heading
  variations, a live preview of the rows as they will be saved, per-row
  problem list with sheet row numbers, remembered column matches, and an
  import summary (added / updated / new rates / unchanged / left out).
  Existing products are matched by SKU, then name; names are compared
  ignoring case, extra spaces and dash style.
- Category is worked out from the HSN/SAC code when the sheet has no
  category column; *Labour involved* from the labour charge when that column
  is missing.
- **Export** of each master to `.xlsx` in a layout the import reads back.
- **Inactive instead of delete:** *Remove* marks a row inactive (greyed,
  listed last); re-importing it makes it active again.
- *Discard changes* button, and a prompt when closing the window with
  unsaved master edits.
- Generate reports: "Masters in use" now shows the real number of active
  products, sales executives and cars, in amber when a master is empty.
- `scripts/make_sample_masters.py` creates sample master sheets for trying
  the import before the client's sheets arrive.
- Automated tests for the data layer (`tests/`, run with `python -m pytest`)
  and `requirements-dev.txt`.

### Changed
- Masters screen tabs are now Products, Sales executives, Cars, Packages and
  Incentive. The separate Cost sheet and Labour charges tabs are merged into
  Products, as the client's Product master holds both.
- Masters start empty and are filled by import or *Add row*; the sample cost,
  labour and executive rows were removed from `sample_data.py`.
- The product name column keeps a minimum width; the table scrolls sideways
  on narrow windows instead of cutting names short.
- `openpyxl` added to `requirements.txt`.
- Sidebar footer shows the version only (no longer "UI preview").
- `.gitignore`: the client-data rule now covers only the top-level `data/`
  folder, so the `app/data/` code package is committed.

### Pending
- Incentive master and spot incentive calculation: awaiting the client's
  rules. The Incentive tab says so.
- Packages tab still shows sample data: package definitions are not part of
  the client's master sheets yet.

## [0.1.0] – 2026-09-25 – UI preview

### Added
- Desktop application shell in Python + PySide6 with a professional blue theme
  (navy sidebar, blue actions, white cards on a pale grey-blue background, Segoe UI).
- Sidebar navigation with count badge (open scan issues) and version footer.
- Smooth fade-and-slide page transitions, animated primary buttons, animated
  progress bar and fading toast confirmations.
- **Generate reports** screen: report month (defaults to last month), invoice
  folder (counts real PDFs), optional Zoho payments export, save folder, 12-report
  checklist with select/clear all, warning when payment report lacks the export,
  step badges that turn green when complete, simulated scan and generate with log.
- **Scan review** screen: empty state, summary tiles, issues table with inline
  fixes (confirm match, choose car model / salesperson / payment mode, add to
  master, open file), status pills and live open-issue count.
- **Masters** screen: Cost sheet, Labour charges (per item), Packages and
  Executives & incentive tabs; search, add, remove, save; amount validation with
  Indian number formatting; "effective from" date prompt on rate changes;
  unsaved-change tracking.
- **Monthly inputs** screen: indirect cost heads with running total, add/remove,
  copy from last month; high-profit threshold setting.
- **History** screen: processed months with Open / Regenerate actions.
- Indian number formatting helpers (`format_inr`, `parse_inr`).
- README.md, CHANGELOG.md, requirements.txt, .gitignore.

### Notes
- All figures are sample data. Invoice reading, calculations and Excel output
  are not implemented yet.
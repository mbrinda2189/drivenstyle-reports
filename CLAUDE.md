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

Current version: **v0.6.0** (tags v0.1.0 … v0.6.0 on GitHub
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
- Qt combo boxes: store item data as strings/ints, never Python tuples
  (`findData` cannot match tuples – this caused a bug in v0.5.0).
- On Windows `glob("*.pdf")` is case-insensitive; never add a second
  `"*.PDF"` search (counted every file twice until v0.4.0).

## Business rules already agreed (do not change without asking)

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
- **Category**: products never set by hand take Zoho's Item Type (goods →
  Product, service → Service); a hand-set Category is never overridden
  (`invoices_repo.apply_zoho_categories`, audit source "Invoice export (Zoho
  item type)").
- **Branch** in reports = the executive's branch from the master; the
  invoice's CF.Branch is stored only.
- **₹1 "Labour Charges for …" and "Labour - …" lines are markers** that labour was done,
  not products (category "Labour line"; their ₹1 stays in sales so totals
  agree).
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
- **Spot incentive (report 7) is PROVISIONAL**: incentive × qty ×
  min(1, amount billed incl. GST ÷ (bill value × qty)). The client has not
  confirmed the rule; the sheet says so.
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

## Next – ideas, NOT confirmed (ask before coding)
- "Incentive Details" sheet in the pricelist lists incentives actually
  paid per invoice – could be used to derive / test the spot incentive rule
  (report 7).
- "Labour Payment" sheet gives labour paid by car model (e.g. VERNA PVC
  500, ALCAZAR PVC 600) – labour may depend on the car, not only the item.
- Items master open points: Water Wash cost ₹1; Sunfilm Budget Nano
  Ceramic min price > sale price.

## Still awaited from the client (not blocking)
- The actual spot incentive rule (report 7 is provisional).
- Package contents, if they want a package's items analysed.
- Monthly indirect costs (entered on the Monthly inputs screen).
- Any report layout they already use.

## Later
- Packaging as a Windows `.exe` with PyInstaller (include `app/assets/`;
  see `theme.asset()` for `sys._MEIPASS`).

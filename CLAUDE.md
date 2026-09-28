# CLAUDE.md – Drive N Style Reports

Read this first in every session. It records how Brinda wants work done,
the decisions already made, and what is next. README.md (features, usage,
project structure) and CHANGELOG.md (history) are the other two sources of
truth. Keep all three up to date.

## What this is

A Windows desktop tool (Python 3.10+, PySide6) for the client **Drive N
Style / Carkrafts** (car accessories and detailing, Coimbatore; GSTIN
`33AAOFD7793F1Z2`). Each month it reads the month's Zoho invoices, matches
every line, salesperson and car to the masters, lets anything unclear be
fixed on a Scan review screen, and writes one Excel workbook with 12
management reports. The user is Brinda, a Chartered Accountant, preparing
the reports for her client before the 7th of each month.

Current version: **v0.5.0** (tags v0.1.0 … v0.5.0 on GitHub
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
`DNS_REPORTS_DATA_DIR`; tests always do).

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
- **₹1 "Labour Charges for …" lines are markers** that labour was done,
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
  matched on name AND branch; none or several matches → Scan review.
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
  date; otherwise the mode printed on the invoice; the rest is "Not
  received".
- Workbook: Cover, 12 report sheets, "Not included". Totals, profits,
  margins, averages and summaries are **live Excel formulas** (verify with
  LibreOffice recalculation: zero errors).

## Next: v0.6.0 – switch to the Zoho invoice export (PROPOSED, NOT YET CONFIRMED)

Brinda found that invoices can be exported from Zoho as a spreadsheet
(`Invoice.csv`, 181 columns) and supplied the client's items master
(`Items.xlsx`). The analysis below was shown to her; **she has not yet
confirmed points 1–5 or answered A–C. Ask before coding.**

### What the export contains (September 2026 sample: 127 invoices, 371 lines, 1–26 Sep)
- One row per invoice line. Key columns: `Invoice Number`, `Invoice Date`
  (YYYY-MM-DD), `Invoice Status` (Closed / Overdue), `Customer Name`,
  `Sales person`, `CF.Vehicle`, `CF.VIN / Registration Number`,
  `CF.Customer Type`, `CF.Branch`, `CF.Invoice Type` (UPI / Cash / CHY),
  `Item Name`, `SKU` (297 of 371 lines), `HSN/SAC`, `Item Type`
  (goods/service), `Quantity`, `Item Price` (tax inclusive), `Item Total`,
  `Item Tax %`, `Item Tax Amount`, `CGST`, `SGST`, `IGST`,
  `Entity Discount Amount`, `SubTotal`, `Round Off`, `Total`, `Balance`,
  `Supplier GST Registration Number`.
- **`Item Total` = the line's value after its share of the entity-level
  discount, excluding GST; `Item Tax Amount` = its GST.** Verified equal
  to the tool's own allocation to the paisa on DNS-226-2627,
  DNS26-GST-0753 and DNS26-GST1-0770.
- Series: `DNS-###-2627` (99 invoices, only 5 with GST), `DNS26-GST-####`
  (26, all GST), `DNS26-GST1-####` (2). All `Is Inclusive Tax` = True,
  discount entity-level before tax.
- Every invoice has a salesperson; 4 have no vehicle. 8 are Overdue
  (unpaid) – their sales count; report 11 shows them as not received.

### Items.xlsx (179 items, no duplicate names/codes)
Columns: (serial), `CODE`, `Item Description`, `Vendor`, `Labour`,
`Sale with GST`, `Purchase without GST`, `Margin`,
`Min Sale Price with GST`, `HSN/SAC`, `Product Type` (notes), `Usuage Unit`.
Map: CODE → SKU, Item Description → Product name, Sale with GST → Selling
price (GST incl.), Purchase without GST → Cost price, Labour → Labour charge
(Labour involved = Yes when > 0), HSN/SAC. Ignore Vendor, Margin, Min Sale
Price for now. The master's Margin = price/1.18 − purchase − labour, which
confirms the cost rules above.
- 213 of 267 sold (non-labour) lines match by name or code; 26 distinct item
  names (54 lines) are not in the master, e.g. "Roof Rail - All cars" (13),
  "Steering Grip - All cars", "MLF MAT EXTER/CRETA/VENUE + LABOUR EXTRA",
  "HORN RELAY", "Headlight Restoration", "PVC Boot Mat".
- Water Wash items have cost ₹1 (≈100% margin) – ask if intended.
- "Sunfilm - Budget Nano Ceramic - Side and Rear (SK)": min sale price
  ₹7,000 > sale price ₹6,000 – ask the client.

### Salespeople vs the executive list (62 people)
22 of 38 printed names match; 16 do not: not in the list (Karupusamy,
Arunkumar, Asanar, Mano Vikram, Faizal, Thiyagarajan, Asif, Manojkumar,
Karthickperiyasamy, Muthu, Johnson, Nandha Kumar, H.Vignesh) or branch
differs (Karthick - HO, Udhayakumar - HO, Pravin - CMP). Printed branches
include "Head Office", "Ho", "OOTY", "KTG".
The executive list itself still has open points (see
Sales_executive_master_check.xlsx given to Brinda): one 9-digit number
(NAVEENDRAN), 6 people without branch, KTG vs KOTHAGIRI, Edhayan's branch.

### Proposed changes (1–5 awaiting confirmation)
1. Generate step 2 becomes **"Invoice export (.csv / .xlsx)"** instead of
   the PDF folder. Keep `invoice_reader.py` in the code, off the screen.
2. Use Zoho's per-line `Item Total` and `Item Tax Amount` directly; check
   that each invoice's lines + GST + round-off = `Total` (flag differences
   on Scan review as today). Month by `Invoice Date`.
3. Items master import: recognise its headings automatically. Fix:
   a heading "Labour" (amounts) is currently matched to the yes/no field
   `has_labour`; it must map to `labour_charge`. Add synonyms "Sale with
   GST", "Purchase without GST", "CODE".
4. Labour markers also include "Labour - …" lines billed at ₹1 (e.g.
   "Labour - Seat Cover - Art Leather"), not only "Labour Charges for …".
5. Salesperson matching ignores spaces and dots ("Udhayakumar" =
   "UDHAYA KUMAR") and treats branch "Head Office" = "HO", "KTG" =
   "Kothagiri".

### Open decisions (A–C) – ask Brinda
- **A. Product vs service**: Items.xlsx has no category. Zoho `Item Type`
  and HSN codes both mark sunfilm and coatings as goods. Suggested: default
  from Zoho Item Type, and the client corrects the Category of items they
  count as services.
- **B. `CF.Invoice Type` (UPI / Cash / CHY)**: is it the payment mode?
  CHY appears on Chandra Hyundai invoices. Suggested: payments export stays
  the main source for report 11; Invoice Type is the fallback.
- **C. `CF.Branch` on invoices** (HO, Kothagiri, KVP…, "Walk-In", blank on
  a third of lines): add a branch-wise summary to the reports, or keep using
  the salesperson's branch from the executive master?

## Still awaited from the client (not blocking)
- The actual spot incentive rule (report 7 is provisional).
- Package contents, if they want a package's items analysed.
- Monthly indirect costs (entered on the Monthly inputs screen).
- Any report layout they already use.

## Later
- Packaging as a Windows `.exe` with PyInstaller (include `app/assets/`;
  see `theme.asset()` for `sys._MEIPASS`).

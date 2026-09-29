# Drive N Style Reports

A Windows desktop tool for **Drive N Style** that reads a month's invoices
from Zoho Books' invoice export and produces one Excel workbook with 12
management reports. Reports are
prepared each month before the 7th, for the month just ended.

> **Current status: v0.6.5 – Zoho invoice export; client's category column.** The tool reads the
> month's invoices from Zoho's invoice export (`Invoice.csv` / `.xlsx`),
> matches them to the masters, lets anything unclear
> be fixed on Scan review, and writes the Excel workbook with all 12 reports.
> Monthly inputs (indirect costs, high-profit threshold) and History (Open /
> Regenerate) are live. Still to come: the client's actual spot incentive
> rule (a provisional rule is used and marked), package definitions, and
> packaging as an .exe.

## The 12 reports

1. Invoice-wise profitability
2. Service vs product profitability
3. Labour calculation
4. Trend analysis (month on month)
5. Basic package analysis
6. Vehicle-wise average per car
7. Spot incentive calculation
8. Executive-wise sales
9. High-profit product sales
10. Indirect vs direct cost %
11. Payment mode analysis
12. Profit & loss

## Screens

| Screen | What it is for |
|---|---|
| **Generate reports** | Choose the month, Zoho's invoice export, the optional Zoho payments export and the save folder; tick reports; read the invoices, then generate the workbook. |
| **Scan review** | Everything the scan could not settle: items not in the Product master, salesperson or vehicle not found / ambiguous / not printed, labour lines without a labour item, totals that do not add up, and skipped files - each with a fix control. A second tab lists every invoice read, as understood by the tool. |
| **Masters** | Products, Sales executives, Cars and Incentives, stored in the database. Search, filter, Edit form, import from Excel with column matching, export, rate history, Select all with Mark active / inactive / Delete / Delete all. Changing an amount asks for an "effective from" date so earlier months keep the old amount. Packages (sample) and Audit log tabs. |
| **Monthly inputs** | Indirect costs for the month (for the P&L and cost % report) and the high-profit threshold. |
| **History** | Months already processed, with Open and Regenerate. Feeds the month-on-month trend report. |

## Key decisions so far

- **Invoices come from Zoho's invoice export (v0.6.0).** Zoho Books › Sales ›
  Invoices › Export gives one row per invoice line. Zoho's own `Item Total`
  (the line after its share of the invoice discount, without GST) is the
  line's **sales**, and `Item Tax Amount` its GST - checked equal to the
  tool's own calculation to the paisa. Each invoice must satisfy lines + GST
  + round-off = Total. The GSTIN `33AAOFD7793F1Z2` is checked as a safety
  net; Void / Draft invoices are skipped. The invoice PDF reader of v0.4.0
  is kept in the code but no longer used on screen.
- **Tax-inclusive rates.** Invoices that show **no GST** (e.g. the
  `DNS-xxx-2627` series) count in full as sales.
- **₹1 "Labour Charges for …" and "Labour - …" lines are ignored** (v0.6.3,
  confirmed by the client); their few paise are left out of sales and noted
  on the cover sheet. They are markers that labour was done, not
  sales items. The labour cost comes from the main product's labour charge in
  the Product master.
- **Salesperson** is printed as "Name - Branch" (e.g. "Kumaran - HO"); it is
  matched on name and branch. Without a branch, the name must match exactly
  one executive. Spaces and dots are ignored ("Udhayakumar" = "UDHAYA
  KUMAR") and "Head Office" = "HO", "KTG" = "Kothagiri".
- **Payment mode** comes from the optional Zoho payments export; where it has
  nothing for an invoice, the export's `CF.Invoice Type` (UPI / Cash / CHY)
  is used.
- **Branch** in the reports is the salesperson's branch from the Sales
  executive master; the invoice's `CF.Branch` is stored but not reported.
- **Category from the Product master.** Every invoice line carries SAC
  998729, so product vs service comes from the Product master's Category,
  not from the invoice. If the client's sheet has no Category column, it is
  worked out from the master's HSN/SAC code (SAC codes start with 99) and
  then replaced by Zoho's Item Type from the invoice export (see *Reading
  the invoices*), unless set by hand.
- **Item matching** by item name, then a remembered mapping, then the SKU
  (the export gives the SKU for most lines). Any other name is mapped once
  on Scan review and remembered.
- **Labour depends on the item** and is kept on the Product master
  (Labour involved + Labour charge).
- **Incentive groups.** The client's incentive sheet lists groups ("PPF",
  "Dashcam", "Basic Package") with an incentive amount and a bill value.
  Each product is linked to its group through the Product master's
  *Incentive group* column (chosen from the Incentive master).
- **Spot incentive rules are awaited.** The calculation (incentive reduced
  when a discount is given) will be built once the client confirms the rule.
- **Sales executives are unique by contact number**, not name: two people
  may share a name.

## Masters

The client provides the masters as Excel sheets. They are loaded once and
kept in the tool; the Masters screen is used for occasional changes.

| Master | Fields | Unique by |
|---|---|---|
| Product | SKU, Product name, HSN/SAC, Category (Product / Service), Incentive group, Selling price, Cost price, Labour involved, Labour charge, Effective from, Active | Product name, and SKU when given |
| Sales executive | Name, Contact no, Branch, Active | Contact no - a 10-digit mobile (`+91 98765 43210` = `9876543210`) |
| Car | Make, Model, Segment (Hatchback, Sedan, Compact SUV, SUV, MUV…; other values can be typed), Active | Make + model |
| Incentive | Product / Service, Incentive amount, Bill value, Effective from, Active | Product / Service |

Duplicates are refused when saving (the message names the existing row) and
when importing (the row is left out and listed). Names are compared ignoring
capitals, extra spaces and dash style.

**Importing.** Masters → choose tab → *Import Excel* → pick an `.xlsx` or
`.csv` file (old `.xls` files must first be saved as `.xlsx`). The tool
finds the heading row even below a title, suggests which column is which
field (e.g. "Rate" → Selling price, "CONTACT NO" → Contact no; an "S.No"
column is ignored), shows a preview of the first rows exactly as they will
be saved, and lists any row it cannot read. Column matches are remembered
for the next import. Importing again updates existing rows and adds new
ones. **Import the Incentive sheet before the Product sheet**, so product
incentive groups can be linked.

The client's items sheet (*Master Data - Items* in the Chandra Hyundai
pricelist) is recognised as it is: CODE → SKU, Item Description → Product
name, Labour (amounts; "-" = none) → Labour charge, Sale with GST → Selling
price, Purchase without GST → Cost price, HSN/SAC. Labour involved is set
for items with a labour charge. Vendor, Margin, Min Sale Price and Usage
Unit are not used; the "Product Type" notes column is ignored as a
category. Rows priced in words ("mrp less 10%") are listed and left out.
From v0.6.5 the sheet's own "category" column is read (SALES = Product,
SERVICE = Service) and is final - Zoho's item type never overrides it. A
CODE used for several different items in the sheet is ignored for those
rows (each imported by name, with a warning) so no item is overwritten.

**Finding rows.** Each tab has a search box, a filter (Products: category,
Sales executives: branch, Cars: segment) and a status filter (active /
inactive).

**Editing.** Double-click a cell, or select a row and click *Edit* to change
it in a form. Edits are held (rows tinted blue) until *Save changes*.

**Amounts and dates.** Product selling price, cost price and labour charge,
and incentive amount and bill value, keep a history. Each change is stored
with the date it applies from; a report for a month uses the amount that
applied then. *Rate history* shows every change. For a month before the
first recorded amount, that first amount is used.

**Selecting and bulk actions.** Tick rows in the first column, or *Select
all* (ticks every row the search and filters show). Then *Mark active*,
*Mark inactive* or *Delete*. *Delete all* removes every row of that master
and asks you to type DELETE. Deleting cannot be undone, but the audit log
keeps a record of what each deleted row held. Staff who leave are better
marked inactive than deleted, so earlier months still show their sales.

**Audit log.** Every change to any master - added, edited (old → new),
activated, deactivated, deleted, imported - is recorded with the date and
time, Windows user name and source (screen or file name). The *Audit log*
tab filters by master, action, date range and text, and exports to Excel.
The log cannot be edited or deleted from the tool; the database itself
refuses it.

**Trying it without the client's sheets.** Run
`python scripts/make_sample_masters.py` to create four sample sheets in
`data/samples/` (sales executive and incentive sheets in the client's own
layout), then import them - incentives first.

## Reading the invoices

1. In Zoho Books: **Sales › Invoices › Export**, CSV or XLSX, covering at
   least the month (a longer period is fine - other months are ignored).
2. On **Generate reports**, choose the month and that file (step 2), then
   **Read invoices**. The log shows how many invoices were read, how many
   dated in other months were ignored, and any Void / Draft or other-firm
   invoice skipped.
3. The month's invoices are saved in the database, replacing an earlier
   reading of the same month. **Fixes made on Scan review are kept**, so
   reading a fresh export again (e.g. after late invoices) never loses work.
4. **Category from Zoho.** Products whose Category was never set by hand
   take Zoho's Item Type (goods → Product, service → Service) - the HSN
   code alone is not reliable (many goods carry the service code 998729).
   Change a product's Category on the Masters screen and Zoho no longer
   touches it. Each change is in the audit log (source "Invoice export").
3. **Scan review** lists what needs attention. Each fix is saved at once:
   - *Item not in the Product master* - choose the product; the tool
     remembers that name for every invoice. Or add the product on the Masters
     screen; the issue clears immediately.
   - *Salesperson / vehicle not found* - listed once per printed name with
     all its invoices; choose the executive / car and it applies to all of
     them (and later months). *Ambiguous or not printed* - one row per
     invoice; "All invoices" can be ticked.
   Click a row to show its Fix controls (only one row has them at a time,
   which keeps the list fast).
   **Export issues** saves the open issues to Excel with a "What we need"
   and a blank "Client's reply" column (plus the invoices affected), to
   send to the client as a question list.
   - *Labour line without a labour item* / *totals do not add up* - open the
     export to check, then Accept (or correct the master).
   Every fix is recorded in the audit log (master "Scan review").
4. The **Invoices read** tab shows each invoice as the tool understood it;
   hover an invoice number to see its lines and the product each matched.

Each invoice's arithmetic is checked: the lines' Item Total + GST + round-off
must equal the invoice Total, within ₹1.

## The reports workbook

**Generate Excel** writes `DriveNStyle_<Mon>-<YYYY>_Reports.xlsx` in the
"Save to" folder with the ticked reports:

| Sheet | Contents |
|---|---|
| Cover | Month, when and by whom generated, key figures, contents, notes |
| 1 Invoice profitability | Per invoice: customer, salesperson, car, sales, discount, GST, total, product cost, labour, gross profit, margin % |
| 2 Service vs product | Product / Service / labour-line summary and item-wise detail |
| 3 Labour | Labour cost by product and every line with labour |
| 4 Trend | One column per scanned month (up to 12): invoices, sales, product/service sales, costs, gross profit, margin, average bill, change |
| 5 Packages | Sales of products whose incentive group is a "… Package" |
| 6 Vehicle-wise | By segment and car model, with average sales and profit per car |
| 7 Spot incentive | **Provisional** rule: incentive × (amount billed ÷ bill value), capped at the full incentive; by executive and per line |
| 8 Executive-wise sales | Per executive (name and branch), including provisional incentive |
| 9 High-profit products | Products at or above the month's threshold margin |
| 10 Indirect vs direct | Direct and indirect costs as % of sales |
| 11 Payment modes | Received by mode (payments export or mode printed on the invoice), by account, per invoice, and "Not received" |
| 12 Profit & loss | Sales → gross profit → net profit, with % of sales |
| Not included | Invoices left out (open issues) and skipped files, with reasons |

How the figures are worked out:

- **Sales** = each line after its share of the invoice discount, without
  GST. Invoices that show no GST count in full.
- **Product cost** and **labour** = the Product master's cost price and
  labour charge (GST-exclusive) × quantity, at the rates that applied on the
  invoice date. Labour only for products marked "Labour involved".
- **Gross profit** = sales − product cost − labour.
- Invoices with **open issues** on Scan review are left out of every report
  and listed on "Not included", so included + left out = every invoice read.
- **Payment modes** come from Zoho's "Payments Received" export (step 3),
  counting every payment applied to the month's invoices whatever its date;
  otherwise from the mode printed on the invoice.
- Totals, profits, margins, averages and summaries are **live Excel
  formulas**, so the workbook stays consistent if a figure is corrected.

Before writing, Generate asks for confirmation if issues are still open or
no indirect costs were entered for the month. If the file is open in Excel,
close it and generate again.

**Monthly inputs**: choose the month, enter the indirect cost heads and
amounts (or "Copy from <previous month>"), set the high-profit threshold,
and Save. Changes are logged in the audit log.

**History**: the latest workbook of each month, with Open and Regenerate
(same reports, folder and payments export; uses the current masters, fixes
and inputs).

## Where the data is kept

The masters are stored in one SQLite file, created on first run:

- Windows: `%LOCALAPPDATA%\Drive N Style Reports\drivenstyle.db`
  (e.g. `C:\Users\<name>\AppData\Local\Drive N Style Reports\`)

It is outside the program folder, so installing a newer version keeps the
data. **Back up this file** to back up the tool's masters and audit log.
When a new version upgrades the file, it first saves a copy next to it
(e.g. `drivenstyle.schema1.bak.db`). Set the
environment variable `DNS_REPORTS_DATA_DIR` to use a different folder (the
automated tests do this).

## Requirements

- Windows 10 or 11
- Python 3.10 or later

## Setup and running (development)

```powershell
cd drivenstyle-reports
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Automated tests

The data layer (database, masters, rate history, Excel import/export,
invoice amounts, matching, Scan review fixes, monthly inputs, payments
export, report figures and workbook) has automated tests that never touch
the real data file:

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

Client invoices are never committed to Git. To also test the reader on real
PDFs, point `DNS_SAMPLE_INVOICES` at a folder of sample invoices; every PDF
must read and add up:

```powershell
$env:DNS_SAMPLE_INVOICES = "C:\path\to\sample invoices"
python -m pytest tests/test_invoice_pdfs.py
```

## Project structure

```
drivenstyle-reports/
├── main.py                  Entry point: opens the database, applies the theme, opens the window
├── requirements.txt         Runtime dependencies
├── requirements-dev.txt     + pytest, for the automated tests
├── README.md                This file
├── CHANGELOG.md             Version history
├── scripts/
│   └── make_sample_masters.py  Creates sample master sheets for trying the import
├── tests/                   Automated tests (python -m pytest)
└── app/
    ├── __init__.py          Version number (keep in step with CHANGELOG.md)
    ├── theme.py             Colour palette + application stylesheet (change the look here)
    ├── utils.py             Indian number formatting (12,34,567.00), parsing, date helper
    ├── sample_data.py       Placeholder rows for screens not yet connected
    ├── main_window.py       Window layout and wiring between pages
    ├── scan_worker.py       Reads invoice PDFs in a background thread (not used from v0.6.0)
    ├── assets/              SVG icons used by the stylesheet
    ├── data/                No UI code here
    │   ├── paths.py         Where the database file lives
    │   ├── master_defs.py   Fields of each master (drives screen, import and export)
    │   ├── database.py      SQLite tables and schema upgrades
    │   ├── masters_repo.py  Reading/saving masters, rate history, duplicates, audit log
    │   ├── invoice_export.py  Reads Zoho's invoice export (one invoice per number) - v0.6.0
    │   ├── invoice_reader.py  Reads one Carkrafts invoice PDF (kept; not used on screen)
    │   ├── invoices_repo.py   Stores scans, matches to masters, Scan review issues and fixes
    │   ├── inputs_repo.py     Monthly inputs (indirect costs, threshold) and report history
    │   └── payments_io.py     Reads Zoho's Payments Received export
    ├── reports/
    │   ├── data.py          Every figure for a month (rates on the invoice date)
    │   ├── workbook.py      Writes the Excel workbook (cover, 12 reports, not included)
    │   └── generate.py      One call: figures -> workbook -> history
    │   └── excel_io.py      Reading client sheets, column matching, export
    ├── widgets/
    │   ├── common.py        Card, AnimatedButton, PathPicker, StatTile, Toast, headers
    │   ├── animated_stack.py  Fade-and-slide page transitions
    │   ├── sidebar.py       Navy navigation sidebar with count badges
    │   ├── master_table.py  Editable master tab: filters, selection, bulk actions, save
    │   ├── edit_dialog.py   Edit form for one master row
    │   ├── import_dialog.py Column matching, preview and import summary
    │   └── audit_view.py    Audit log tab: filters and export
    └── pages/
        ├── base.py          Scrollable page frame shared by all screens
        ├── generate_page.py
        ├── review_page.py
        ├── masters_page.py
        ├── inputs_page.py
        └── history_page.py
```

## Look and feel

Professional blue theme defined in `app/theme.py`:

| Role | Colour |
|---|---|
| Sidebar | Navy `#0B2545` |
| Primary buttons, highlights | Blue `#1F5FBF` |
| Hover / focus | Sky `#3B82F6` |
| Page background | `#F4F7FB` with white cards |

Font: Segoe UI (native Windows). Motion: pages fade and slide in when switched,
primary buttons glide between colours on hover, progress bars animate, and
confirmations appear as fading toast messages.

## Packaging (planned)

The tool will be packaged as a single `.exe` with PyInstaller. The
`app/assets` folder must be included, e.g.:

```powershell
pyinstaller --noconsole --onefile --add-data "app/assets;app/assets" main.py
```

## Roadmap

- ~~v0.2 – Masters database (SQLite) and import of the client's master sheets~~ ✔
- ~~v0.3 – Incentive master, filters, edit form, bulk actions, audit log~~ ✔
- ~~v0.4 – Invoice reader, matching to the masters, real Scan review~~ ✔
- ~~v0.5 – The 12 reports, Excel workbook, Monthly inputs, History~~ ✔
- ~~v0.6 – Invoices from Zoho's invoice export; Items master import fixes~~ ✔
- Spot incentive calculation – once the client confirms the rule
- Package definitions, packaging as .exe

## Version control

The project is a Git repository. Each change is committed with a clear
message, releases are tagged (`v0.1.0`, …), and every change is recorded in
`CHANGELOG.md`.
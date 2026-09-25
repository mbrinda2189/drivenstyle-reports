# Drive N Style Reports

A Windows desktop tool for **Drive N Style** that reads a month's Zoho invoice
PDFs and produces one Excel workbook with 12 management reports. Reports are
prepared each month before the 7th, for the month just ended.

> **Current status: v0.2.0 – Masters.** The Product, Sales executive and Car
> masters are stored in the tool's own database and can be imported from the
> client's Excel sheets, edited, and exported. Invoice reading, calculations
> and the Excel output are not connected yet; the Generate, Scan review,
> Monthly inputs and History screens still use sample data.

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
| **Generate reports** | Choose the month, the invoice folder, the optional Zoho payments export and the save folder; tick reports; scan the invoices, then generate the workbook. |
| **Scan review** | Lists invoices that need attention (item not in the cost sheet, missing car model/salesperson/payment mode, other-firm or unreadable PDFs) with a control to fix each one. |
| **Masters** | Products, Sales executives and Cars, stored in the database. Import from Excel with column matching, edit, export, rate history. Changing a price or labour charge asks for an "effective from" date so earlier months keep the old rate. Packages (sample) and Incentive (awaiting rules) tabs. |
| **Monthly inputs** | Indirect costs for the month (for the P&L and cost % report) and the high-profit threshold. |
| **History** | Months already processed, with Open and Regenerate. Feeds the month-on-month trend report. |

## Key decisions so far

- **Drive N Style only.** Invoices are identified by GSTIN `33AAOFD7793F1Z2`;
  any other firm's invoice in the folder (e.g. DNS Enterprises) is skipped and
  listed on Scan review.
- **Invoices are Zoho text PDFs** – read directly, no OCR.
- **Tax-inclusive rates.** GST is removed from line amounts and the
  invoice-level discount is spread across lines in proportion to their value
  before profit is calculated.
- **Category from the Product master.** Every invoice line carries SAC
  998729, so product vs service comes from the Product master's Category,
  not from the invoice. If the client's sheet has no Category column, it is
  worked out from the master's HSN/SAC code (SAC codes start with 99).
- **Item matching:** by SKU first, then by item name (some items have no SKU).
- **Car model and salesperson** will be printed on invoices going forward.
- **Payment mode** is not on the invoice; it comes from the optional Zoho
  "Payments Received" export.
- **Labour depends on the item** and is kept on the Product master
  (Labour involved + Labour charge).
- **Incentive rules are awaited.** The Incentive master and the spot
  incentive module (incentive reduced in proportion to the discount given)
  will be built once the client confirms the rules.

## Masters

The client provides the masters as Excel sheets. They are loaded once and
kept in the tool; the Masters screen is used for occasional changes.

| Master | Fields |
|---|---|
| Product | SKU, Product name, HSN/SAC, Category (Product / Service), Selling price, Cost price, Labour involved, Labour charge, Effective from, Active |
| Sales executive | Name, Phone, City, Active |
| Car | Make, Model, Segment (Hatchback, Sedan, Compact SUV, SUV, MUV…; other values can be typed), Active |

**Importing.** Masters → choose tab → *Import Excel* → pick an `.xlsx` or
`.csv` file (old `.xls` files must first be saved as `.xlsx`). The tool
finds the heading row even below a title, suggests which column is which
field (e.g. "Rate" → Selling price, "Mobile No" → Phone), shows a preview of
the first rows exactly as they will be saved, and lists any row it cannot
read. Column matches are remembered for the next import. Importing again
updates existing rows (matched by SKU, then name) and adds new ones.

**Rates and dates.** Selling price, cost price and labour charge keep a
history. Each change is stored with the date it applies from; a report for
a month uses the rate that applied then. *Rate history* shows every change
of a product. For a month before a product's first recorded rate, that
first rate is used.

**Nothing is deleted.** *Remove* marks a row inactive (greyed, listed last)
so re-running earlier months still finds it. Tick *Active* to restore it;
it is also restored automatically if it appears in a later import.

**Trying it without the client's sheets.** Run
`python scripts/make_sample_masters.py` to create three sample sheets in
`data/samples/`, then import them.

## Where the data is kept

The masters are stored in one SQLite file, created on first run:

- Windows: `%LOCALAPPDATA%\Drive N Style Reports\drivenstyle.db`
  (e.g. `C:\Users\<name>\AppData\Local\Drive N Style Reports\`)

It is outside the program folder, so installing a newer version keeps the
data. **Back up this file** to back up the tool's masters. Set the
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

The data layer (database, masters, rate history, Excel import/export) has
automated tests that never touch the real data file:

```powershell
pip install -r requirements-dev.txt
python -m pytest
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
    ├── assets/              SVG icons used by the stylesheet
    ├── data/                No UI code here
    │   ├── paths.py         Where the database file lives
    │   ├── master_defs.py   Fields of each master (drives screen, import and export)
    │   ├── database.py      SQLite tables and schema upgrades
    │   ├── masters_repo.py  Reading/saving masters, rate history, import rules
    │   └── excel_io.py      Reading client sheets, column matching, export
    ├── widgets/
    │   ├── common.py        Card, AnimatedButton, PathPicker, StatTile, Toast, headers
    │   ├── animated_stack.py  Fade-and-slide page transitions
    │   ├── sidebar.py       Navy navigation sidebar with count badges
    │   ├── master_table.py  Editable master tab: validation, rate dates, save
    │   └── import_dialog.py Column matching, preview and import summary
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
- v0.3 – Invoice reader for Drive N Style Zoho PDFs, matching invoice lines to
  the masters, real Scan review
- Incentive master and spot incentive module – once the client confirms the rules
- v0.4 – Report calculations and Excel workbook output
- v0.5 – History, trend analysis, payments export, packaging as .exe

## Version control

The project is a Git repository. Each change is committed with a clear
message, releases are tagged (`v0.1.0`, …), and every change is recorded in
`CHANGELOG.md`.

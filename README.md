# Drive N Style Reports

A Windows desktop tool for **Drive N Style** that reads a month's Zoho invoice
PDFs and produces one Excel workbook with 12 management reports. Reports are
prepared each month before the 7th, for the month just ended.

> **Current status: v0.1.0 – UI preview.** All screens are built and
> interactive, using sample data. Invoice reading, calculations and the Excel
> output are not connected yet (waiting for the client's cost sheet and labour
> charges sheet).

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
| **Masters** | Cost sheet, labour charges (per item), packages, executives & incentive. Editable; changing a rate asks for an "effective from" date so earlier months keep the old rate. |
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
- **Category from the cost sheet.** Every line carries SAC 998729, so product
  vs service comes from the cost sheet, not the HSN/SAC.
- **Item matching:** by SKU first, then by item name (some items have no SKU).
- **Car model and salesperson** will be printed on invoices going forward.
- **Payment mode** is not on the invoice; it comes from the optional Zoho
  "Payments Received" export.
- **Labour depends on the item** and is kept per SKU in the Labour charges master.

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

## Project structure

```
drivenstyle-reports/
├── main.py                  Entry point: creates the app, applies the theme, opens the window
├── requirements.txt
├── README.md                This file
├── CHANGELOG.md             Version history
└── app/
    ├── __init__.py          Version number (keep in step with CHANGELOG.md)
    ├── theme.py             Colour palette + application stylesheet (change the look here)
    ├── utils.py             Indian number formatting (12,34,567.00) and parsing
    ├── sample_data.py       Placeholder rows for the preview (to be removed)
    ├── main_window.py       Window layout and wiring between pages
    ├── assets/              SVG icons used by the stylesheet
    ├── widgets/
    │   ├── common.py        Card, AnimatedButton, PathPicker, StatTile, Toast, headers
    │   ├── animated_stack.py  Fade-and-slide page transitions
    │   └── sidebar.py       Navy navigation sidebar with count badges
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

- v0.2 – Masters database (SQLite) and import of the client's cost sheet and labour charges
- v0.3 – Invoice reader for Drive N Style Zoho PDFs + real Scan review
- v0.4 – Report calculations and Excel workbook output
- v0.5 – History, trend analysis, payments export, packaging as .exe

## Version control

The project is a Git repository. Each change is committed with a clear
message, releases are tagged (`v0.1.0`, …), and every change is recorded in
`CHANGELOG.md`.

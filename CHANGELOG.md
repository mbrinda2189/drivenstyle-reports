# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
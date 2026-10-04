# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

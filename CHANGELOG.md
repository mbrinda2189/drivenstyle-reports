# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

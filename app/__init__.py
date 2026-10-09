"""
Drive N Style Reports Tool
==========================

Top-level application package.

This package holds everything the desktop tool needs:

    app/theme.py         - Colour palette and the Qt stylesheet (QSS) for the
                           whole application. Change the look here only.
    app/utils.py         - Small helpers, e.g. Indian-style number formatting.
    app/sample_data.py   - Placeholder rows for screens not yet connected
                           (packages, scan issues, history).
    app/data/            - Database, masters, invoices, monthly inputs and
                           Excel import/export. No UI code, so it can be
                           tested on its own.
    app/reports/         - The 12 reports: figures and the Excel workbook.
    app/main_window.py   - The main window: sidebar + animated page area.
    app/widgets/         - Reusable UI building blocks (cards, buttons, etc.).
    app/pages/           - One module per screen of the tool.

The version string below is shown in the sidebar footer and must be kept in
step with CHANGELOG.md whenever a new version is released.
"""

__version__ = "0.22.0"
__app_name__ = "Drive N Style Reports"
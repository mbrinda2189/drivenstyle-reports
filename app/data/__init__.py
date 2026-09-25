"""
app.data - Everything that stores or reads data (no screens here)
=================================================================

This package is deliberately free of Qt/UI code, so the same logic can be
used by the screens, by the command-line test suite, and later by the
invoice reader and report builder.

    paths.py         - Where the tool keeps its files (the SQLite database).
    master_defs.py   - The field list of each master (Product, Sales
                       executive, Car): names, types, whether required, and
                       the column headings recognised on import.
    database.py      - Opens the SQLite database and creates / upgrades its
                       tables.
    masters_repo.py  - Reading and saving the masters, including the dated
                       rate history of products.
    excel_io.py      - Reading the client's Excel / CSV master sheets,
                       suggesting column matches, converting rows, and
                       exporting a master back to Excel.
"""

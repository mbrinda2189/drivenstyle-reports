"""
import_dialog.py - Import a master from the client's Excel sheet
================================================================

WHAT THIS DIALOG DOES
---------------------
Opened by Masters > Import Excel after a file is chosen. It lets the user
check, before anything is saved, how the sheet will be read:

    +----------------------------------------------------------------+
    |  Import products                                               |
    |  product_master.xlsx  ·  headings on row 3  ·  42 rows        |
    |  Sheet [Sheet1 v]                    (only if several sheets)  |
    |                                                                |
    |  Match the columns                                             |
    |    Product name *     [Item Name        v]                     |
    |    Selling price      [Rate             v]                     |
    |    Category           [— Not in sheet — v]  From HSN/SAC…      |
    |    ...                                                         |
    |  Preview (first 5 rows)   <- values as they will be saved      |
    |  Amounts apply from [01-10-2026]  (products and incentives)    |
    |  ⚠ 2 rows will be left out: Row 7: Selling price “abc”…        |
    |                                     [Cancel] [Import 40 rows]  |
    +----------------------------------------------------------------+

* Column matches are suggested automatically (last import's matches first,
  then known headings - see excel_io.suggest_mapping) and can be changed.
* Fields marked * must be matched before Import is enabled.
* The preview and the "left out" warning update as soon as a match changes.
* A "S.No" column is simply left unmatched; it is not needed.
* Import stores the rows (masters_repo.import_records), writes an audit log
  entry for every row added or changed (source "Import: <file name>"),
  remembers the column matches for next time, and closes. The caller then
  calls `show_summary()` to report what was added, updated and left out.

ZOHO'S ITEM LIST (v0.7.0)
------------------------
Zoho's item export (Items > Export, Item.csv) is recognised by its
headings and is the source of the Product master's names and prices:
    Item Name -> Product name, SKU, HSN/SAC, Rate -> Selling price,
    Purchase Rate -> Cost price, Product Type (goods / service) -> Category
The columns are pre-set (excel_io.zoho_item_mapping). On Import:
    * the Rs. 1 labour items in Zoho's list are left out (not products)
    * labour charge, incentive group and "Vehicle needed" are not in Zoho,
      so they keep their values in the tool
    * products in the tool that are NOT in Zoho's list are shown, and
      removed if the user confirms (each removal is in the audit log)
"Add items that are not in the Product master" (products only): untick it
when importing the staff sheet for labour / incentive, so its own item
names are not added back.

The window never opens taller than the screen: everything above the Cancel
/ Import buttons scrolls, and the buttons stay at the bottom (v0.6.4 - on a
zoomed-in laptop screen the Import button could not be reached). Drop-downs
ignore the mouse wheel until clicked, so scrolling cannot change a column
match by accident.

"Amounts apply from" (products and incentives) defaults to 1st April of the
current financial year when the master is still empty (first load),
otherwise to the 1st of next month, matching the amount-change dialog.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QGridLayout,
    QCheckBox, QHBoxLayout, QHeaderView, QMessageBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from app.data.excel_io import (
    ImportFileError, SheetData, convert_rows, is_zoho_item_export, read_sheet,
    suggest_mapping, zoho_item_mapping)
from app.data.master_defs import MasterDef
from app.data.masters_repo import ImportResult, MastersRepo
from app.theme import Colors
from app.utils import first_of_next_month, format_inr
from app.widgets.common import (
    NoWheelComboBox, NoWheelDateEdit, button, fit_to_screen, label, scroll_body)

NOT_IN_SHEET = "— Not in this sheet —"
PREVIEW_ROWS = 5

# What happens when an optional field is not in the sheet (shown beside it).
FALLBACK_HINTS = {
    "category": "Not in sheet? Worked out from the HSN/SAC code.",
    "has_labour": "Not in sheet? Yes when the labour charge is above zero.",
    "active": "Not in sheet? Every imported row is active.",
    "incentive_group": "Must match a name in the Incentive master.",
}


def financial_year_start(today: date | None = None) -> date:
    """1st April of the current Indian financial year."""
    today = today or date.today()
    return date(today.year if today.month >= 4 else today.year - 1, 4, 1)


class ImportDialog(QDialog):
    """Column matching, preview and import of one master sheet."""

    def __init__(self, mdef: MasterDef, repo: MastersRepo, path: str,
                 sheet: SheetData, parent=None):
        super().__init__(parent)
        self.mdef, self.repo, self.path, self.sheet = mdef, repo, path, sheet
        self.records: list[dict] = []
        self.problems: list[str] = []
        self.result_summary: ImportResult | None = None

        self.setWindowTitle(f"Import {mdef.title.lower()}")
        self.setModal(True)
        self.setMinimumSize(720, 420)
        lay, btns = scroll_body(self)
        lay.addWidget(label(f"Import {mdef.title.lower()}", "PageTitle"))
        self.file_info = label("", "Muted", wrap=True)
        lay.addWidget(self.file_info)

        # --- sheet chooser (only when the workbook has several sheets) ----
        self.sheet_combo = NoWheelComboBox()
        self.sheet_combo.addItems(sheet.sheet_names)
        self.sheet_combo.setCurrentText(sheet.sheet)
        self.sheet_combo.currentTextChanged.connect(self._change_sheet)
        if len(sheet.sheet_names) > 1:
            row = QHBoxLayout()
            row.addWidget(label("Sheet"))
            row.addWidget(self.sheet_combo)
            row.addStretch(1)
            lay.addLayout(row)

        # --- column matching ------------------------------------------------
        lay.addWidget(label("Match the columns", "SectionTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.combos: dict[str, QComboBox] = {}
        for i, f in enumerate(mdef.importable_fields):
            grid.addWidget(label(f.label + ("  *" if f.required else "")), i, 0,
                           Qt.AlignVCenter)
            combo = NoWheelComboBox()
            combo.setMinimumWidth(240)
            combo.setMinimumHeight(34)      # keep full height in a tight dialog
            combo.currentIndexChanged.connect(self._refresh)
            self.combos[f.key] = combo
            grid.addWidget(combo, i, 1)
            if f.key in FALLBACK_HINTS:
                grid.addWidget(label(FALLBACK_HINTS[f.key], "Muted"), i, 2)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

        # --- preview ----------------------------------------------------------
        lay.addWidget(label(f"Preview (first {PREVIEW_ROWS} rows, as they "
                            "will be saved)", "SectionTitle"))
        self.preview = QTableWidget(0, 0)
        self.preview.verticalHeader().hide()
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.NoSelection)
        self.preview.setAlternatingRowColors(True)
        self.preview.verticalHeader().setDefaultSectionSize(34)
        self.preview.setMinimumHeight(34 * PREVIEW_ROWS + 44)
        self.preview.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        lay.addWidget(self.preview, 1)

        # --- effective date for rates (products only) ------------------------
        self.date_edit = None
        if mdef.has_rates:
            row = QHBoxLayout()
            row.addWidget(label("Amounts apply from"))
            empty = not self.repo.list_rows(mdef.key)
            default = financial_year_start() if empty else first_of_next_month()
            self.date_edit = NoWheelDateEdit(QDate(default.year, default.month, default.day))
            self.date_edit.setCalendarPopup(True)
            self.date_edit.setDisplayFormat("dd-MM-yyyy")
            row.addWidget(self.date_edit)
            row.addWidget(label(f"{mdef.title} already in the tool keep their "
                                "old amounts for earlier months.", "Muted",
                                wrap=True), 1)
            lay.addLayout(row)

        # --- Zoho item list / add new items (products only) -------------------
        self.is_zoho = False
        self.zoho_note = label("", wrap=True)
        self.zoho_note.setStyleSheet(
            f"background: {Colors.BLUE_TINT}; color: {Colors.INK};"
            "border-radius: 6px; padding: 8px 10px;")
        self.zoho_note.hide()
        lay.addWidget(self.zoho_note)
        self.add_new = QCheckBox("Add items that are not in the Product master")
        self.add_new.setChecked(True)
        self.add_new.setToolTip(
            "Untick when the sheet only supplies labour / incentive for items "
            "already in the master (e.g. the staff sheet after Zoho's item list "
            "was imported): rows with a new name are then left out.")
        self.add_new.setVisible(mdef.key == "products")
        lay.addWidget(self.add_new)

        # --- problems + buttons ----------------------------------------------
        self.problem_note = label("", wrap=True)
        self.problem_note.setStyleSheet(
            f"background: {Colors.AMBER_TINT}; color: {Colors.AMBER};"
            "border-radius: 6px; padding: 8px 10px;")
        lay.addWidget(self.problem_note)

        btns.addStretch(1)
        cancel = button("Cancel", "Secondary")
        cancel.clicked.connect(self.reject)
        self.import_btn = button("Import", "Primary")
        self.import_btn.clicked.connect(self._do_import)
        btns.addWidget(cancel)
        btns.addWidget(self.import_btn)
        fit_to_screen(self, 900, 860)

        self._fill_combos()

    # ------------------------------------------------------------------
    # Sheet and column matching
    # ------------------------------------------------------------------
    def _fill_combos(self) -> None:
        """Offer the sheet's headings in every drop-down and pre-select the
        suggested match for each field."""
        s = self.sheet
        self.file_info.setText(
            f"{Path(self.path).name}  ·  headings found on row {s.header_row}"
            f"  ·  {len(s.rows)} data row{'s' if len(s.rows) != 1 else ''}")
        self.is_zoho = self.mdef.key == "products" and is_zoho_item_export(s.headers)
        if self.is_zoho:
            suggestion = zoho_item_mapping(s.headers)
            self.zoho_note.setText(
                "Zoho item list recognised. Names, SKU, HSN/SAC, prices and "
                "category (goods / service) come from Zoho. Labour, incentive "
                "group and “Vehicle needed” stay as they are in the tool. "
                "The ₹1 labour items are left out. After the import you are "
                "asked about products that are not in Zoho's list.")
            self.add_new.setChecked(True)
        else:
            suggestion = suggest_mapping(self.mdef, s.headers,
                                         self.repo.get_mapping(self.mdef.key))
        self.zoho_note.setVisible(self.is_zoho)
        self.add_new.setEnabled(not self.is_zoho)
        for key, combo in self.combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([NOT_IN_SHEET, *s.headers])
            combo.setCurrentText(suggestion.get(key) or NOT_IN_SHEET)
            combo.blockSignals(False)
        self._refresh()

    def _change_sheet(self, name: str) -> None:
        try:
            self.sheet = read_sheet(self.path, self.mdef, name)
        except ImportFileError as exc:
            QMessageBox.warning(self, "Cannot read this sheet", str(exc))
            return
        self._fill_combos()

    def mapping(self) -> dict[str, str | None]:
        """field key -> chosen heading (None when 'Not in this sheet')."""
        return {k: (c.currentText() if c.currentIndex() > 0 else None)
                for k, c in self.combos.items()}

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _refresh(self, *_) -> None:
        """Re-convert the rows with the current matches and update the
        preview, the warning and the Import button."""
        mapping = self.mapping()
        missing = [self.mdef.get_field(k).label for k, h in mapping.items()
                   if h is None and self.mdef.get_field(k).required]
        self.records, self.problems = convert_rows(self.mdef, self.sheet, mapping)

        # Preview columns: only the matched fields, in master order.
        fields = [f for f in self.mdef.importable_fields if mapping.get(f.key)]
        self.preview.clear()
        self.preview.setColumnCount(len(fields))
        self.preview.setHorizontalHeaderLabels([f.label for f in fields])
        # Columns fit their headings and values so nothing is cut off; the
        # name column gets a fixed comfortable width. Wide sheets scroll
        # sideways; a narrow sheet stretches its last column to fill.
        hdr = self.preview.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)
        for c, f in enumerate(fields):
            if f.key in ("name", "model"):
                hdr.setSectionResizeMode(c, QHeaderView.Interactive)
                self.preview.setColumnWidth(c, 260)
        shown = self.records[:PREVIEW_ROWS]
        self.preview.setRowCount(len(shown))
        for r, rec in enumerate(shown):
            for c, f in enumerate(fields):
                v = rec.get(f.key)
                if f.kind == "money":
                    text = format_inr(v or 0)
                elif f.kind == "bool":
                    text = "Yes" if v else "No"
                else:
                    text = "" if v is None else str(v)
                it = QTableWidgetItem(text)
                if f.kind == "money":
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.preview.setItem(r, c, it)

        # Warning and button
        notes = []
        if missing:
            notes.append(f"Choose the column for: {', '.join(missing)}.")
        if self.problems:
            n = len(self.problems)
            listed = "\n".join(self.problems[:3])
            more = f"\n…and {n - 3} more." if n > 3 else ""
            notes.append(f"{n} row{'s' if n != 1 else ''} will be left out:\n"
                         f"{listed}{more}")
        self.problem_note.setText("\n\n".join(notes))
        self.problem_note.setVisible(bool(notes))
        n = len(self.records)
        if self.is_zoho:                    # the Rs. 1 labour items are left out
            n = len(MastersRepo.split_zoho_items(self.records)[0])
        self.import_btn.setText(f"Import {n} row{'s' if n != 1 else ''}")
        self.import_btn.setEnabled(not missing and n > 0)

    # ------------------------------------------------------------------
    # Import and summary
    # ------------------------------------------------------------------
    def _do_import(self) -> None:
        day = None
        if self.date_edit is not None:
            q = self.date_edit.date()
            day = date(q.year(), q.month(), q.day())
        source = f"Import: {Path(self.path).name}"
        records, markers = self.records, []
        if self.is_zoho:
            records, markers = MastersRepo.split_zoho_items(records)
        try:
            result = self.repo.import_records(
                self.mdef.key, records, day, source=source,
                add_new=self.add_new.isChecked() or self.is_zoho)
        except Exception as exc:                      # unexpected: nothing saved
            QMessageBox.critical(self, "Import failed",
                                 f"Nothing was imported.\n\n{exc}")
            return
        result.skipped = self.problems + result.skipped
        if markers:
            result.warnings.append(
                f"{len(markers)} ₹1 labour item{'s' if len(markers) != 1 else ''} "
                "in Zoho's list left out (not products): " + "; ".join(markers) + ".")
        if result.not_added:
            result.warnings.append(
                f"{result.not_added} row{'s' if result.not_added != 1 else ''} with "
                "a name that is not in the master left out (“Add items…” is unticked).")
        if self.is_zoho:
            self._remove_not_in_zoho(result, source)
        self.repo.set_mapping(self.mdef.key, self.mapping())
        self.result_summary = result
        self.accept()

    def _remove_not_in_zoho(self, result: ImportResult, source: str) -> None:
        """Products that are not in Zoho's list: show them, remove if confirmed."""
        mapping = self.mapping()
        col = self.sheet.headers.index(mapping["name"])
        names = [str(cells[col]).strip() for _, cells in self.sheet.rows
                 if cells[col] not in (None, "")]
        missing = self.repo.products_not_in(names)
        if not missing:
            return
        shown = "\n".join("  • " + p["name"] for p in missing[:12])
        more = f"\n  … and {len(missing) - 12} more" if len(missing) > 12 else ""
        box = QMessageBox(self)
        box.setWindowTitle("Products not in Zoho's list")
        box.setIcon(QMessageBox.Question)
        box.setText(f"{len(missing)} product{'s' if len(missing) != 1 else ''} in the "
                    "tool are not in Zoho's item list.")
        box.setInformativeText(
            f"{shown}{more}\n\nRemove them from the Product master? Their labour "
            "and incentive settings go with them. Each removal is kept in the "
            "audit log.")
        remove = box.addButton("Remove them", QMessageBox.DestructiveRole)
        box.addButton("Keep them", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is remove:
            n = self.repo.delete("products", [p["id"] for p in missing],
                                 source=f"{source} (not in Zoho's item list)")
            result.warnings.append(
                f"{n} product{'s' if n != 1 else ''} not in Zoho's item list removed: "
                + "; ".join(p["name"] for p in missing) + ".")
        else:
            result.warnings.append(
                f"{len(missing)} product{'s' if len(missing) != 1 else ''} not in "
                "Zoho's item list kept: " + "; ".join(p["name"] for p in missing) + ".")

    def show_summary(self, parent) -> None:
        """Tell the user what the import did (called after the dialog closes)."""
        r = self.result_summary
        lines = [f"{r.added} added, {r.updated} updated, {r.unchanged} unchanged."]
        if self.mdef.has_rates and r.rates_changed:
            day = self.date_edit.date().toString("dd-MM-yyyy")
            lines.append(f"{r.rates_changed} {self.mdef.singular}"
                         f"{'s' if r.rates_changed != 1 else ''} got new amounts "
                         f"from {day}.")
        if r.skipped:
            lines.append(f"{len(r.skipped)} row{'s' if len(r.skipped) != 1 else ''}"
                         " left out (see details).")
        if r.warnings:
            lines.append(f"{len(r.warnings)} note{'s' if len(r.warnings) != 1 else ''}"
                         " (see details).")
        box = QMessageBox(parent)
        box.setWindowTitle("Import complete")
        box.setIcon(QMessageBox.Warning if r.skipped else QMessageBox.Information)
        box.setText(f"{self.mdef.title} imported from {Path(self.path).name}.")
        box.setInformativeText("\n".join(lines))
        if r.skipped or r.warnings:
            box.setDetailedText("\n".join(
                (["Left out:"] + r.skipped if r.skipped else [])
                + ([""] if r.skipped and r.warnings else [])
                + (["Notes:"] + r.warnings if r.warnings else [])))
        box.exec()
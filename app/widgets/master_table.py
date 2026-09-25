"""
master_table.py - One editable master, backed by the database
=============================================================

WHAT THIS MODULE DOES
---------------------
`MasterTable` is the content of one tab on the Masters screen (Products,
Sales executives or Cars). Everything about it - columns, how each cell is
edited, what is checked - comes from the master's definition in
app/data/master_defs.py, so the three tabs behave identically.

    +---------------------------------------------------------------------+
    | [Search…]            [Rate history] [Import Excel] [Export] [Add row]|
    |                                                          [Remove]   |
    | +-----------------------------------------------------------------+ |
    | | SKU | Product name | HSN/SAC | Category | Selling price | ...    | |
    | +-----------------------------------------------------------------+ |
    | 3 unsaved changes                                  [Save changes]   |
    +---------------------------------------------------------------------+

EDITING
-------
    text / money   double-click (or start typing) to edit
    money          validated: must be a number, not negative; shown with
                   Indian grouping (2,400.00)
    choice         a drop-down (Category: Product / Service; car Segment,
                   where a new value can also be typed)
    yes / no       a tick box (Labour involved, Active)
    Effective from read-only; set by the rate-change dialog

Changing a product's selling price, cost price or labour charge asks
"When does this rate apply from?" (default: 1st of next month). The old rate
stays in the history for earlier months. The chosen date is used for all
rate changes made to that row before saving.

Edited and new rows are tinted light blue and counted. If an edit is undone
by typing the old value back, the row is no longer counted as changed.
Nothing reaches the database until "Save changes"; the save is all-or-
nothing, and any problems (duplicate name, missing name...) are listed.

REMOVE
------
Saved rows are never deleted: Remove unticks "Active" so the row stays
available for past months (see masters_repo.py). A new row that has not
been saved yet is simply taken out.

INACTIVE ROWS
-------------
are shown in grey, below the active ones.

SIGNALS
-------
    saved()   emitted after a successful save or import, so other screens
              (e.g. the Generate page's "Masters in use") can refresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QFileDialog, QHBoxLayout,
    QHeaderView, QLineEdit, QMessageBox, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.data.excel_io import ImportFileError, export_rows, read_sheet
from app.data.master_defs import FieldDef, MasterDef
from app.data.masters_repo import MasterError, MastersRepo, RowChange
from app.theme import Colors
from app.utils import first_of_next_month, format_inr, parse_inr
from app.widgets.common import button, label
from app.widgets.import_dialog import ImportDialog

STATE_ROLE = Qt.UserRole + 1        # where each row's RowState is kept


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


# ---------------------------------------------------------------------------
# Row state
# ---------------------------------------------------------------------------
@dataclass
class RowState:
    """
    Bookkeeping for one table row, stored on the row's first cell so it
    moves with the row when rows are added, removed or hidden.

    id         database id (None for a row added on screen, not yet saved)
    original   values as last loaded from the database
    shown      values currently in the cells (used to undo a cancelled edit)
    rate_date  effective date chosen for this row's rate changes, if any
    """
    id: int | None
    original: dict
    shown: dict = field(default_factory=dict)
    rate_date: date | None = None

    @property
    def is_new(self) -> bool:
        return self.id is None

    def is_changed(self) -> bool:
        return self.is_new or any(
            self.shown.get(k) != v for k, v in self.original.items()
            if k not in ("id", "effective_from"))


# ---------------------------------------------------------------------------
# Drop-down editor for "choice" columns
# ---------------------------------------------------------------------------
class ChoiceDelegate(QStyledItemDelegate):
    """Shows a drop-down instead of a text box when a choice cell is edited."""

    def __init__(self, fdef: FieldDef, extra_values, parent=None):
        super().__init__(parent)
        self.fdef = fdef
        self.extra_values = extra_values     # callable -> values already used

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        values = list(self.fdef.choices)
        if self.fdef.open_choice:
            values += sorted(v for v in self.extra_values() if v and v not in values)
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)
        combo.addItems(values)
        return combo

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or "")

    def setModelData(self, editor, model, index):
        model.setData(index, " ".join(editor.currentText().split()))


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class EffectiveDateDialog(QDialog):
    """Asks from which date a changed rate applies."""

    def __init__(self, item_name: str, what: str, old: str, new: str,
                 default: date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rate change")
        self.setModal(True)
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label("When does this rate apply from?", "SectionTitle"))
        lay.addWidget(label(f"{item_name}\n{what}: {old}  →  {new}",
                            "Muted", wrap=True))
        self.date_edit = QDateEdit(_qdate(default))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MM-yyyy")
        lay.addWidget(self.date_edit)
        lay.addWidget(label("Months before this date keep the old rate.", "Muted"))

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancel", "Secondary")
        cancel.clicked.connect(self.reject)
        ok = button("Apply rate", "Primary")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def chosen_date(self) -> date:
        return _pydate(self.date_edit.date())


class RateHistoryDialog(QDialog):
    """Read-only list of every rate change of one product, newest first."""

    def __init__(self, product_name: str, history: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rate history")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label(product_name, "SectionTitle"))
        lay.addWidget(label("Each row applies from its date until the next "
                            "change. Reports for a month use the rate that "
                            "applied in that month.", "Muted", wrap=True))

        heads = ["Effective from", "Selling price (₹)", "Cost price (₹)",
                 "Labour charge (₹)"]
        table = QTableWidget(len(history), len(heads))
        table.setHorizontalHeaderLabels(heads)
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, h in enumerate(history):
            table.setItem(r, 0, QTableWidgetItem(
                h["effective_from"].strftime("%d-%m-%Y")))
            for c, k in enumerate(("selling_price", "cost_price",
                                   "labour_charge"), start=1):
                it = QTableWidgetItem(format_inr(h[k]))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, it)
        # Just tall enough for its rows (scrolls beyond ten changes).
        table.setFixedHeight(table.horizontalHeader().sizeHint().height()
                             + 36 * min(10, max(1, len(history))) + 4)
        lay.addWidget(table)

        close = button("Close", "Secondary")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)


# ---------------------------------------------------------------------------
# MasterTable
# ---------------------------------------------------------------------------
class MasterTable(QWidget):
    """An editable master (one tab of the Masters screen)."""

    saved = Signal()

    CHANGED_BG = QColor(Colors.BLUE_TINT)
    NAME_MIN_WIDTH = 240     # the name column never gets narrower than this

    def __init__(self, mdef: MasterDef, repo: MastersRepo, toast, parent=None):
        """
        mdef   the master's definition (columns, kinds, labels)
        repo   MastersRepo used to load and save
        toast  function(text) that shows a short confirmation message
        """
        super().__init__(parent)
        self.mdef = mdef
        self.repo = repo
        self.toast = toast
        self.fields = list(mdef.fields)
        self._col = {f.key: i for i, f in enumerate(self.fields)}
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(12)
        lay.addLayout(self._build_toolbar())

        self.empty_note = label("", "Muted", wrap=True)
        self.empty_note.setText(
            f"No {mdef.title.lower()} yet. Use Import Excel to load the "
            f"client's {mdef.singular} master, or Add row to enter one.")
        self.empty_note.setStyleSheet(
            f"background: {Colors.BLUE_TINT}; border-radius: 6px;"
            f"padding: 10px 12px; color: {Colors.INK};")
        lay.addWidget(self.empty_note)

        self.table = self._build_table()
        lay.addWidget(self.table)

        foot = QHBoxLayout()
        self.changes_label = label("", "Muted")
        foot.addWidget(self.changes_label, 1)
        self.discard_btn = button("Discard changes", "Ghost")
        self.discard_btn.clicked.connect(self._discard)
        foot.addWidget(self.discard_btn)
        self.save_btn = button("Save changes", "Primary")
        self.save_btn.clicked.connect(self._save)
        foot.addWidget(self.save_btn)
        lay.addLayout(foot)

        self.reload()

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------
    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {self.mdef.title.lower()}…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search)
        bar.addStretch(1)

        if self.mdef.has_rates:
            history = button("Rate history", "Ghost")
            history.clicked.connect(self._show_history)
            bar.addWidget(history)
        for text, handler in (("Import Excel", self._import),
                              ("Export", self._export),
                              ("Add row", self._add_row)):
            b = button(text, "Secondary")
            b.clicked.connect(handler)
            bar.addWidget(b)
        remove = button("Remove", "Danger")
        remove.setToolTip("Marks the row inactive. It stays available for "
                          "past months.")
        remove.clicked.connect(self._remove_row)
        bar.addWidget(remove)
        return bar

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(self.fields))
        table.setHorizontalHeaderLabels([f.label for f in self.fields])
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.DoubleClicked
                              | QAbstractItemView.EditKeyPressed
                              | QAbstractItemView.AnyKeyPressed)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setMinimumHeight(400)
        hdr = table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Fixed-width columns keep their width; the one column without a
        # width (the name) takes the spare space but never goes below
        # NAME_MIN_WIDTH - see _fit_name_column. If the window is too narrow
        # for everything, the table scrolls sideways instead of squeezing
        # the name to "Dash ...".
        self._name_col = next(i for i, f in enumerate(self.fields) if not f.width)
        for i, f in enumerate(self.fields):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
            table.setColumnWidth(i, f.width or self.NAME_MIN_WIDTH)
            if f.kind == "choice":
                table.setItemDelegateForColumn(
                    i, ChoiceDelegate(f, lambda k=f.key: self._used_values(k), table))
        table.viewport().installEventFilter(self)
        table.itemChanged.connect(self._on_item_changed)
        return table

    def eventFilter(self, obj, event):
        """Re-fit the name column whenever the table changes size."""
        table = getattr(self, "table", None)      # not set while building
        if table is not None and obj is table.viewport() \
                and event.type() == QEvent.Resize:
            self._fit_name_column()
        return super().eventFilter(obj, event)

    def _fit_name_column(self) -> None:
        others = sum(self.table.columnWidth(i)
                     for i in range(len(self.fields)) if i != self._name_col)
        spare = self.table.viewport().width() - others
        self.table.setColumnWidth(self._name_col,
                                  max(self.NAME_MIN_WIDTH, spare))

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """(Re)fill the table from the database, dropping unsaved edits."""
        self._loading = True
        self.table.setRowCount(0)
        for values in self.repo.list_rows(self.mdef.key):
            self._append_row(values, RowState(values["id"], dict(values),
                                              dict(values)))
        self._loading = False
        self._filter(self.search.text())
        self._update_footer()

    def _append_row(self, values: dict, state: RowState) -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, f in enumerate(self.fields):
            self.table.setItem(r, c, self._make_item(f, values.get(f.key)))
        self.table.item(r, 0).setData(STATE_ROLE, state)
        self._paint_row(r)
        return r

    def _make_item(self, f: FieldDef, value) -> QTableWidgetItem:
        """Create a cell showing `value` the way field `f` needs."""
        item = QTableWidgetItem()
        if f.kind == "bool":
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                          | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)
            return item
        if f.kind == "money":
            item.setText(format_inr(float(value or 0)))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        elif f.kind == "date":
            item.setText(value.strftime("%d-%m-%Y") if value else "")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setToolTip("Date the current rates apply from. Set when a "
                            "rate is changed.")
        else:
            item.setText(str(value or ""))
        return item

    # ------------------------------------------------------------------
    # Reading cells
    # ------------------------------------------------------------------
    def _state(self, row: int) -> RowState:
        return self.table.item(row, 0).data(STATE_ROLE)

    def _cell_value(self, row: int, f: FieldDef):
        item = self.table.item(row, self._col[f.key])
        if f.kind == "bool":
            return item.checkState() == Qt.Checked
        if f.kind == "money":
            return parse_inr(item.text()) or 0.0
        if f.kind == "date":
            return self._state(row).original.get(f.key)
        return " ".join(item.text().split())

    def _row_values(self, row: int) -> dict:
        return {f.key: self._cell_value(row, f) for f in self.fields}

    def _row_name(self, row: int) -> str:
        if self.mdef.key == "cars":
            v = self._row_values(row)
            return " ".join(p for p in (v["make"], v["model"]) if p) or "This car"
        return self._row_values(row).get("name") or f"This {self.mdef.singular}"

    def _used_values(self, key: str) -> set[str]:
        """Values already in a column (offered in open drop-downs)."""
        c = self._col[key]
        return {self.table.item(r, c).text() for r in range(self.table.rowCount())
                if self.table.item(r, c)}

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Validate an edit, ask for an effective date for rates, mark the row."""
        if self._loading:
            return
        row, f = item.row(), self.fields[item.column()]
        state = self._state(row) if self.table.item(row, 0) else None
        if state is None:
            return

        if f.kind == "money":
            value = parse_inr(item.text())
            if value is None or value < 0:
                self._set_text(item, format_inr(state.shown.get(f.key) or 0))
                self.toast("Enter a valid amount, e.g. 2400 or 2,400.00")
                return
            value = round(value, 2)
            self._set_text(item, format_inr(value))
            if value == state.shown.get(f.key):
                return
            if f.dated and not state.is_new and state.rate_date is None:
                old = state.original.get(f.key) or 0
                dlg = EffectiveDateDialog(self._row_name(row), f.label,
                                          format_inr(old), format_inr(value),
                                          first_of_next_month(), self)
                if dlg.exec() != QDialog.Accepted:
                    self._set_text(item, format_inr(state.shown.get(f.key) or 0))
                    return
                state.rate_date = dlg.chosen_date()
        else:
            value = self._cell_value(row, f)
            if f.kind in ("text", "choice") and item.text() != value:
                self._set_text(item, value)       # tidy extra spaces

        state.shown[f.key] = value
        self._after_edit(row)

    def _after_edit(self, row: int) -> None:
        """Forget the rate date if all rates are back to their saved values,
        show the pending effective date, repaint, update the counter."""
        state = self._state(row)
        if state.rate_date and all(
                state.shown.get(f.key) == state.original.get(f.key)
                for f in self.mdef.dated_fields):
            state.rate_date = None
        if "effective_from" in self._col:
            shown = state.rate_date or state.original.get("effective_from")
            self._set_text(self.table.item(row, self._col["effective_from"]),
                           shown.strftime("%d-%m-%Y") if shown else "")
        self._paint_row(row)
        self._update_footer()

    def _set_text(self, item: QTableWidgetItem, text: str) -> None:
        """Change a cell's text without triggering _on_item_changed."""
        self._loading = True
        item.setText(text)
        self._loading = False

    def _paint_row(self, row: int) -> None:
        """Blue tint for unsaved rows; grey text for inactive rows."""
        state = self._state(row)
        active = state.shown.get("active", True)
        bg = QBrush(self.CHANGED_BG) if state.is_changed() else QBrush()
        fg = QBrush(QColor(Colors.FAINT if not active else Colors.INK))
        was = self._loading
        self._loading = True
        for c, f in enumerate(self.fields):
            it = self.table.item(row, c)
            it.setBackground(bg)
            it.setForeground(QBrush(QColor(Colors.SLATE)) if f.kind == "date"
                             and active else fg)
        self._loading = was

    def _changed_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self._state(r).is_changed()]

    def has_unsaved_changes(self) -> bool:
        return bool(self._changed_rows())

    def _update_footer(self) -> None:
        n = len(self._changed_rows())
        total = self.table.rowCount()
        inactive = sum(1 for r in range(total)
                       if not self._state(r).shown.get("active", True))
        if n:
            self.changes_label.setText(
                f"{n} unsaved change{'s' if n != 1 else ''}")
        else:
            text = f"{total - inactive} {self.mdef.title.lower()}"
            if inactive:
                text += f"  ·  {inactive} inactive"
            self.changes_label.setText(
                text + "  ·  Double-click a cell to edit." if total else "")
        self.save_btn.setEnabled(n > 0)
        self.discard_btn.setVisible(n > 0)
        self.empty_note.setVisible(total == 0)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------
    def _add_row(self) -> None:
        """Append an empty row with default values and start editing it."""
        values = {f.key: f.default for f in self.fields}
        if "effective_from" in values:
            values["effective_from"] = date.today()
        self._loading = True
        state = RowState(None, dict(values), dict(values))
        r = self._append_row(values, state)
        self._loading = False
        self._update_footer()
        self.search.clear()
        self.table.scrollToBottom()
        first_text = next(i for i, f in enumerate(self.fields)
                          if f.required)
        self.table.setCurrentCell(r, first_text)
        self.table.editItem(self.table.item(r, first_text))

    def _remove_row(self) -> None:
        """Take out an unsaved row, or mark a saved row inactive."""
        row = self.table.currentRow()
        if row < 0:
            self.toast(f"Select a {self.mdef.singular} to remove.")
            return
        name = self._row_name(row)
        state = self._state(row)
        if state.is_new:
            self.table.removeRow(row)
            self._update_footer()
            return
        if not state.shown.get("active", True):
            self.toast(f"{name} is already inactive.")
            return
        # Unticking Active goes through _on_item_changed like a user click.
        self.table.item(row, self._col["active"]).setCheckState(Qt.Unchecked)
        self.toast(f"{name} marked inactive. Save changes to keep this.")

    def _discard(self) -> None:
        self.reload()
        self.toast("Changes discarded.")

    def _save(self) -> None:
        """Send all changed rows to the database in one go."""
        changes = [RowChange(self._state(r).id, self._row_values(r),
                             self._state(r).rate_date)
                   for r in self._changed_rows()]
        try:
            self.repo.save(self.mdef.key, changes)
        except MasterError as err:
            QMessageBox.warning(
                self, "Changes not saved",
                "Nothing was saved. Please correct the following and try "
                "again:\n\n• " + "\n• ".join(err.messages))
            return
        self.reload()
        self.toast(f"{self.mdef.title} saved.")
        self.saved.emit()

    def _filter(self, text: str) -> None:
        """Hide rows that do not contain the search text in any column."""
        needle = text.strip().lower()
        for r in range(self.table.rowCount()):
            match = not needle or any(
                needle in (self.table.item(r, c).text().lower()
                           if self.table.item(r, c) else "")
                for c in range(self.table.columnCount()))
            self.table.setRowHidden(r, not match)

    def _show_history(self) -> None:
        row = self.table.currentRow()
        if row < 0 or self._state(row).is_new:
            self.toast("Select a saved product to see its rate history.")
            return
        RateHistoryDialog(self._row_name(row),
                          self.repo.rate_history(self._state(row).id),
                          self).exec()

    def _export(self) -> None:
        """Write the saved master to an Excel file the user chooses."""
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {self.mdef.title.lower()}",
            f"{self.mdef.title.replace(' ', '_')}_{date.today():%d-%m-%Y}.xlsx",
            "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_rows(self.mdef, self.repo.list_rows(self.mdef.key), path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed",
                                f"The file could not be written:\n{exc}\n\n"
                                "If it is open in Excel, close it and try again.")
            return
        note = " Unsaved changes were not included." if \
            self.has_unsaved_changes() else ""
        self.toast(f"{self.mdef.title} exported.{note}")

    def _import(self) -> None:
        """Choose a file and open the column-matching import dialog."""
        if self.has_unsaved_changes():
            self.toast("Save or discard your changes before importing.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"Import {self.mdef.singular} master", "",
            "Excel or CSV (*.xlsx *.xlsm *.csv);;Old Excel (*.xls)")
        if not path:
            return
        try:
            sheet = read_sheet(path, self.mdef)
        except ImportFileError as exc:
            QMessageBox.warning(self, "Cannot import this file", str(exc))
            return
        dlg = ImportDialog(self.mdef, self.repo, path, sheet, self)
        if dlg.exec() == QDialog.Accepted and dlg.result_summary:
            self.reload()
            self.saved.emit()
            dlg.show_summary(self)

"""
master_table.py - One editable master, backed by the database
=============================================================

WHAT THIS MODULE DOES
---------------------
`MasterTable` is the content of one tab on the Masters screen (Products,
Sales executives, Cars or Incentives). Everything about it - columns, how
each cell is edited, which filter is offered, what is checked - comes from
the master's definition in app/data/master_defs.py, so all tabs behave the
same way.

    +----------------------------------------------------------------------+
    | [Search…] [All branches v] [All v]   Rate history  Edit  Import Excel |
    |                                                  Export   Add row     |
    | [ ] Select all   2 selected   Mark active  Mark inactive  Delete      |
    |                                                         Delete all    |
    | +------------------------------------------------------------------+ |
    | |[ ]| Name | Contact no | Branch | Active                           | |
    | +------------------------------------------------------------------+ |
    | 3 unsaved changes                        Discard changes  Save changes|
    +----------------------------------------------------------------------+

FINDING ROWS
------------
    Search box     rows containing the text in any column
    Filter         one column's values (Products: Category, Sales
                   executives: Branch, Cars: Segment)
    Status         All / Active only / Inactive only
All three work together. "n shown" appears in the footer while filtering.

EDITING (staged until "Save changes")
-------------------------------------
    * In the table: double-click a cell (or start typing). Drop-downs for
      Category / Segment / Incentive group; tick boxes for yes/no fields.
    * With "Edit": a form for the selected row (app/widgets/edit_dialog.py).
    * Changing a dated amount (product prices, labour charge, incentive
      amount, bill value) asks "When does this apply from?" (default 1st of
      next month). Earlier months keep the old amount.
Edited and new rows are tinted light blue and counted; typing the old value
back un-marks the row. "Save changes" stores everything in one go and
writes the audit log; problems (duplicates, missing fields) are listed and
nothing is saved. "Discard changes" reloads from the database.

SELECTING AND BULK ACTIONS (immediate, with confirmation)
---------------------------------------------------------
Tick the first column of rows (or "Select all", which ticks every row
currently shown by the search / filters). Then:
    Mark active / Mark inactive   for the ticked rows
    Delete                        delete the ticked rows
    Delete all                    delete every row of this master; you must
                                  type DELETE to confirm
These act on the database straight away (each is logged in the audit log),
so they are only allowed when there are no unsaved edits.

SIGNALS
-------
    saved()   after a save, import or bulk action, so other screens (the
              Generate page counts, the audit log, lookups in other tabs)
              can refresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog,
    QHBoxLayout, QHeaderView, QInputDialog, QLineEdit, QMessageBox,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.data.excel_io import ImportFileError, export_rows, read_sheet
from app.data.master_defs import FieldDef, MasterDef
from app.data.masters_repo import MasterError, MastersRepo, RowChange
from app.theme import Colors
from app.utils import first_of_next_month, format_inr, parse_inr
from app.widgets.common import button, label
from app.widgets.edit_dialog import EditDialog
from app.widgets.import_dialog import ImportDialog

STATE_ROLE = Qt.UserRole + 1        # where each row's RowState is kept
SELECT_COL = 0                      # the tick column; fields start at 1
STATUS_ALL, STATUS_ACTIVE, STATUS_INACTIVE = range(3)


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
    Bookkeeping for one table row, stored on the row's tick cell so it
    moves with the row when rows are added, hidden or re-ordered.

    id         database id (None for a row added on screen, not yet saved)
    original   values as last loaded from the database
    shown      values currently in the cells (used to undo a cancelled edit)
    rate_date  effective date chosen for this row's amount changes, if any
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
# Drop-down editor for "choice" and "lookup" columns
# ---------------------------------------------------------------------------
class ChoiceDelegate(QStyledItemDelegate):
    """Shows a drop-down instead of a text box when the cell is edited."""

    def __init__(self, fdef: FieldDef, values_func, parent=None):
        """
        values_func   function returning the values to offer:
                      choice - values already used in the column (added to
                               the fixed list when `open_choice`)
                      lookup - the other master's active names
        """
        super().__init__(parent)
        self.fdef = fdef
        self.values_func = values_func

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        if self.fdef.kind == "lookup":
            combo.addItems(["", *self.values_func()])   # "" = no group
            return combo
        values = list(self.fdef.choices)
        if self.fdef.open_choice:
            values += sorted(v for v in self.values_func() if v and v not in values)
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
    """Asks from which date a changed amount applies."""

    def __init__(self, item_name: str, what: str, old: str, new: str,
                 default: date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Amount change")
        self.setModal(True)
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label("When does this amount apply from?", "SectionTitle"))
        lay.addWidget(label(f"{item_name}\n{what}: {old}  →  {new}",
                            "Muted", wrap=True))
        self.date_edit = QDateEdit(_qdate(default))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MM-yyyy")
        lay.addWidget(self.date_edit)
        lay.addWidget(label("Months before this date keep the old amount.", "Muted"))

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancel", "Secondary")
        cancel.clicked.connect(self.reject)
        ok = button("Apply", "Primary")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def chosen_date(self) -> date:
        return _pydate(self.date_edit.date())


class RateHistoryDialog(QDialog):
    """
    Every dated change of one row, newest first.

    v0.10.2: when `repo` and `row_id` are given, a wrong date can be removed
    ("Delete selected date", after a confirmation, logged in the audit
    log). The last remaining date cannot be removed. `changed` tells the
    caller to reload the master. Without them the list is read-only (used
    while the Masters tab has unsaved edits, which a reload would lose).
    """

    def __init__(self, mdef: MasterDef, row_name: str, history: list[dict],
                 parent=None, repo: MastersRepo | None = None,
                 row_id: int | None = None):
        super().__init__(parent)
        self.mdef, self.repo, self.row_id = mdef, repo, row_id
        self.history, self.changed = history, False
        self.setWindowTitle("Rate history")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label(row_name, "SectionTitle"))
        lay.addWidget(label("Each row applies from its date until the next "
                            "change. Reports for a month use the amounts that "
                            "applied in that month.", "Muted", wrap=True))

        dated = mdef.dated_fields
        table = QTableWidget(len(history), 1 + len(dated))
        table.setHorizontalHeaderLabels(["Effective from", *[f.label for f in dated]])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection if repo
                               else QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table = table
        for r, h in enumerate(history):
            table.setItem(r, 0, QTableWidgetItem(h["effective_from"].strftime("%d-%m-%Y")))
            for c, f in enumerate(dated, start=1):
                it = QTableWidgetItem(format_inr(h[f.key]))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, it)
        # Just tall enough for its rows (scrolls beyond ten changes).
        table.setFixedHeight(table.horizontalHeader().sizeHint().height()
                             + 36 * min(10, max(1, len(history))) + 4)
        lay.addWidget(table)

        close = button("Close", "Secondary")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        if repo is not None and row_id is not None:
            delete = button("Delete selected date", "Danger")
            delete.setToolTip("Remove the amounts entered for the selected date, e.g. a "
                              "price saved with a wrong date.")
            delete.clicked.connect(self._delete)
            row.addWidget(delete)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    def _delete(self) -> None:
        r = self.table.currentRow()
        if not 0 <= r < len(self.history):
            QMessageBox.information(self, "Rate history", "Select a date first.")
            return
        day = self.history[r]["effective_from"]
        if QMessageBox.question(
                self, "Delete dated amounts",
                f"Remove the amounts that apply from {day:%d-%m-%Y}?\n\nThe earlier "
                "amounts will apply again from their own date. Reports for the months "
                "affected change the next time they are generated.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.repo.delete_rate(self.mdef.key, self.row_id, day)
        except MasterError as exc:
            QMessageBox.warning(self, "Rate history", str(exc))
            return
        self.changed = True
        self.history.pop(r)
        self.table.removeRow(r)


# ---------------------------------------------------------------------------
# MasterTable
# ---------------------------------------------------------------------------
class MasterTable(QWidget):
    """An editable master (one tab of the Masters screen)."""

    saved = Signal()

    CHANGED_BG = QColor(Colors.BLUE_TINT)
    NAME_MIN_WIDTH = 240     # the stretching column never gets narrower

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
        self._col = {f.key: i + 1 for i, f in enumerate(self.fields)}
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(10)
        lay.addLayout(self._build_toolbar())
        lay.addLayout(self._build_selection_bar())

        self.empty_note = label(
            f"No {mdef.title.lower()} yet. Use Import Excel to load the "
            f"client's {mdef.singular} master, or Add row to enter one.",
            wrap=True)
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
        self.search.setMinimumWidth(180)
        self.search.setMaximumWidth(240)
        self.search.textChanged.connect(self._apply_filters)
        bar.addWidget(self.search)

        # Filter on one column (only when the master defines one).
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(150)
        self.filter_combo.currentIndexChanged.connect(self._apply_filters)
        self.filter_combo.setVisible(bool(self.mdef.filter_field))
        bar.addWidget(self.filter_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["Active and inactive", "Active only",
                                    "Inactive only"])
        self.status_combo.currentIndexChanged.connect(self._apply_filters)
        bar.addWidget(self.status_combo)
        bar.addStretch(1)

        if self.mdef.has_rates:
            history = button("Rate history", "Ghost")
            history.clicked.connect(self._show_history)
            bar.addWidget(history)
        edit = button("Edit", "Ghost")
        edit.setToolTip(f"Edit the selected {self.mdef.singular} in a form.")
        edit.clicked.connect(self._edit_row)
        bar.addWidget(edit)
        for text, handler in (("Import Excel", self._import),
                              ("Export", self._export),
                              ("Add row", self._add_row)):
            b = button(text, "Secondary")
            b.clicked.connect(handler)
            bar.addWidget(b)
        return bar

    def _build_selection_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.select_all = QCheckBox("Select all")
        self.select_all.setToolTip("Tick every row currently shown.")
        self.select_all.setCursor(Qt.PointingHandCursor)
        self.select_all.clicked.connect(self._toggle_select_all)
        bar.addWidget(self.select_all)
        self.selected_label = label("", "Muted")
        bar.addWidget(self.selected_label)
        bar.addSpacing(8)
        self.mark_active_btn = button("Mark active", "Ghost")
        self.mark_active_btn.clicked.connect(lambda: self._bulk_active(True))
        self.mark_inactive_btn = button("Mark inactive", "Ghost")
        self.mark_inactive_btn.clicked.connect(lambda: self._bulk_active(False))
        self.delete_btn = button("Delete", "Danger")
        self.delete_btn.clicked.connect(self._delete_selected)
        for b in (self.mark_active_btn, self.mark_inactive_btn, self.delete_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        self.delete_all_btn = button("Delete all", "Danger")
        self.delete_all_btn.clicked.connect(self._delete_all)
        bar.addWidget(self.delete_all_btn)
        return bar

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(self.fields) + 1)
        table.setHorizontalHeaderLabels(["", *[f.label for f in self.fields]])
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.DoubleClicked
                              | QAbstractItemView.EditKeyPressed
                              | QAbstractItemView.AnyKeyPressed)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setMinimumHeight(400)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        hdr = table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Fixed-width columns keep their width; the one column without a
        # width (the name) takes the spare space but never goes below
        # NAME_MIN_WIDTH - see _fit_name_column. If the window is too narrow
        # for everything, the table scrolls sideways instead of squeezing
        # names to "Dash ...".
        hdr.setSectionResizeMode(SELECT_COL, QHeaderView.Fixed)
        table.setColumnWidth(SELECT_COL, 38)
        self._name_col = next(self._col[f.key] for f in self.fields if not f.width)
        for f in self.fields:
            c = self._col[f.key]
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
            table.setColumnWidth(c, f.width or self.NAME_MIN_WIDTH)
            if f.kind == "choice":
                table.setItemDelegateForColumn(
                    c, ChoiceDelegate(f, lambda k=f.key: self._used_values(k), table))
            elif f.kind == "lookup":
                table.setItemDelegateForColumn(
                    c, ChoiceDelegate(f, lambda m=f.lookup: self.repo.lookup_names(m),
                                      table))
        table.itemChanged.connect(self._on_item_changed)
        table.viewport().installEventFilter(self)
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
                     for i in range(self.table.columnCount()) if i != self._name_col)
        spare = self.table.viewport().width() - others
        self.table.setColumnWidth(self._name_col, max(self.NAME_MIN_WIDTH, spare))

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """(Re)fill the table from the database, dropping unsaved edits."""
        self._loading = True
        self.table.setRowCount(0)
        for values in self.repo.list_rows(self.mdef.key):
            self._append_row(values, RowState(values["id"], dict(values), dict(values)))
        self._loading = False
        self._refresh_filter_values()
        self._apply_filters()

    def _append_row(self, values: dict, state: RowState) -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        tick = QTableWidgetItem()
        tick.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        tick.setCheckState(Qt.Unchecked)
        tick.setData(STATE_ROLE, state)
        self.table.setItem(r, SELECT_COL, tick)
        for f in self.fields:
            self.table.setItem(r, self._col[f.key], self._make_item(f, values.get(f.key)))
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
            item.setToolTip("Date the current amounts apply from. Set when "
                            "an amount is changed.")
        else:
            item.setText(str(value or ""))
        return item

    # ------------------------------------------------------------------
    # Reading cells
    # ------------------------------------------------------------------
    def _state(self, row: int) -> RowState:
        return self.table.item(row, SELECT_COL).data(STATE_ROLE)

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
        return (self.repo.display_name(self.mdef.key, self._row_values(row))
                or f"This {self.mdef.singular}")

    def _used_values(self, key: str) -> set[str]:
        """Values already in a column (offered in open drop-downs)."""
        c = self._col[key]
        return {self.table.item(r, c).text() for r in range(self.table.rowCount())
                if self.table.item(r, c)}

    def _ticked_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, SELECT_COL).checkState() == Qt.Checked]

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Validate an edit, ask for an effective date for amounts, mark the row."""
        if self._loading:
            return
        if item.column() == SELECT_COL:          # a tick, not an edit
            self._update_selection()
            return
        row, f = item.row(), self.fields[item.column() - 1]
        state = self._state(row)

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
                dlg = EffectiveDateDialog(self._row_name(row), f.label,
                                          format_inr(state.original.get(f.key) or 0),
                                          format_inr(value), first_of_next_month(), self)
                if dlg.exec() != QDialog.Accepted:
                    self._set_text(item, format_inr(state.shown.get(f.key) or 0))
                    return
                state.rate_date = dlg.chosen_date()
        else:
            value = self._cell_value(row, f)
            if f.kind in ("text", "choice", "lookup") and item.text() != value:
                self._set_text(item, value)       # tidy extra spaces

        state.shown[f.key] = value
        self._after_edit(row)

    def _after_edit(self, row: int) -> None:
        """Forget the rate date if all amounts are back to their saved
        values, show the pending effective date, repaint, update counts."""
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
        was = self._loading
        self._loading = True
        item.setText(text)
        self._loading = was

    def _paint_row(self, row: int) -> None:
        """Blue tint for unsaved rows; grey text for inactive rows."""
        state = self._state(row)
        active = state.shown.get("active", True)
        bg = QBrush(self.CHANGED_BG) if state.is_changed() else QBrush()
        fg = QBrush(QColor(Colors.INK if active else Colors.FAINT))
        slate = QBrush(QColor(Colors.SLATE))
        was = self._loading
        self._loading = True
        self.table.item(row, SELECT_COL).setBackground(bg)
        for f in self.fields:
            it = self.table.item(row, self._col[f.key])
            it.setBackground(bg)
            it.setForeground(slate if f.kind == "date" and active else fg)
        self._loading = was

    def _changed_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self._state(r).is_changed()]

    def has_unsaved_changes(self) -> bool:
        return bool(self._changed_rows())

    def _update_footer(self) -> None:
        n = len(self._changed_rows())
        total = self.table.rowCount()
        shown = sum(not self.table.isRowHidden(r) for r in range(total))
        inactive = sum(1 for r in range(total)
                       if not self._state(r).shown.get("active", True))
        if n:
            text = f"{n} unsaved change{'s' if n != 1 else ''}"
        elif total:
            text = f"{total - inactive} active"
            if inactive:
                text += f"  ·  {inactive} inactive"
            if shown != total:
                text += f"  ·  {shown} shown"
            text += "  ·  Double-click a cell to edit."
        else:
            text = ""
        self.changes_label.setText(text)
        self.save_btn.setEnabled(n > 0)
        self.discard_btn.setVisible(n > 0)
        self.empty_note.setVisible(total == 0)
        self.delete_all_btn.setEnabled(total > 0)
        self._update_selection()

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    def _refresh_filter_values(self) -> None:
        """Fill the filter drop-down with the values in its column."""
        if not self.mdef.filter_field:
            return
        f = self.mdef.get_field(self.mdef.filter_field)
        current = self.filter_combo.currentText()
        values = sorted(v for v in self._used_values(f.key) if v)
        plural = {"branch": "branches", "category": "categories",
                  "segment": "segments"}.get(f.key, f.label.lower() + "s")
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem(f"All {plural}")
        self.filter_combo.addItems(values)
        if current in values:
            self.filter_combo.setCurrentText(current)
        self.filter_combo.blockSignals(False)

    def _apply_filters(self, *_) -> None:
        """Show only rows matching the search text, filter and status."""
        needle = self.search.text().strip().lower()
        want = (self.filter_combo.currentText()
                if self.mdef.filter_field and self.filter_combo.currentIndex() > 0
                else None)
        status = self.status_combo.currentIndex()
        for r in range(self.table.rowCount()):
            state = self._state(r)
            show = True
            if needle:
                show = any(needle in (self.table.item(r, c).text().lower())
                           for c in range(1, self.table.columnCount()))
            if show and want is not None:
                show = self.table.item(r, self._col[self.mdef.filter_field]).text() == want
            if show and status != STATUS_ALL and not state.is_new:
                active = state.shown.get("active", True)
                show = active if status == STATUS_ACTIVE else not active
            self.table.setRowHidden(r, not show)
        self._update_footer()

    # ------------------------------------------------------------------
    # Selection (tick column)
    # ------------------------------------------------------------------
    def _toggle_select_all(self, checked: bool) -> None:
        """Tick / untick every row currently shown."""
        self._loading = True
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.item(r, SELECT_COL).setCheckState(
                    Qt.Checked if checked else Qt.Unchecked)
            elif checked is False:
                self.table.item(r, SELECT_COL).setCheckState(Qt.Unchecked)
        self._loading = False
        self._update_selection()

    def _update_selection(self) -> None:
        ticked = self._ticked_rows()
        visible = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        n = len(ticked)
        self.selected_label.setText(f"{n} selected" if n else "")
        for b in (self.mark_active_btn, self.mark_inactive_btn, self.delete_btn):
            b.setEnabled(n > 0)
        self.select_all.blockSignals(True)
        self.select_all.setChecked(bool(visible) and all(r in ticked for r in visible))
        self.select_all.blockSignals(False)

    # ------------------------------------------------------------------
    # Bulk actions (straight to the database, with confirmation)
    # ------------------------------------------------------------------
    def _bulk_allowed(self) -> bool:
        if self.has_unsaved_changes():
            QMessageBox.information(
                self, "Unsaved changes",
                "Save or discard your changes first, then try again.")
            return False
        return True

    def _ticked_ids(self) -> list[int]:
        return [self._state(r).id for r in self._ticked_rows()
                if self._state(r).id is not None]

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel) == QMessageBox.Yes

    def _bulk_active(self, active: bool) -> None:
        ids = self._ticked_ids()
        if not ids or not self._bulk_allowed():
            return
        word = "active" if active else "inactive"
        if not self._confirm(f"Mark {word}",
                             f"Mark {len(ids)} {self._noun(len(ids))} as {word}?"):
            return
        done = self.repo.set_active(self.mdef.key, ids, active)
        self._after_bulk(f"{done} {self._noun(done)} marked {word}.")

    def _delete_selected(self) -> None:
        ids = self._ticked_ids()
        if not ids or not self._bulk_allowed():
            return
        extra = self._incentive_warning(ids)
        if not self._confirm(
                "Delete", f"Delete {len(ids)} {self._noun(len(ids))}? This cannot "
                f"be undone. The audit log keeps a record of what was deleted.{extra}"):
            return
        done = self.repo.delete(self.mdef.key, ids)
        self._after_bulk(f"{done} {self._noun(done)} deleted.")

    def _delete_all(self) -> None:
        if not self._bulk_allowed():
            return
        ids = [self._state(r).id for r in range(self.table.rowCount())]
        if not ids:
            return
        extra = self._incentive_warning(ids)
        text, ok = QInputDialog.getText(
            self, "Delete all",
            f"This deletes ALL {len(ids)} {self._noun(len(ids))}, including "
            f"inactive ones and any hidden by the filters. It cannot be undone; "
            f"the audit log keeps a record.{extra}\n\nType DELETE to confirm:")
        if not ok:
            return
        if text.strip().upper() != "DELETE":
            self.toast("Nothing deleted: the confirmation word did not match.")
            return
        done = self.repo.delete(self.mdef.key, ids)
        self._after_bulk(f"All {done} {self._noun(done)} deleted.")

    def _incentive_warning(self, ids: list[int]) -> str:
        """Extra line when deleting incentive groups that products use."""
        if self.mdef.key != "incentives":
            return ""
        placeholders = ", ".join("?" * len(ids))
        n = self.repo.conn.execute(
            f"SELECT COUNT(*) FROM products WHERE incentive_id IN ({placeholders})",
            ids).fetchone()[0]
        return (f"\n\n{n} product{'s' if n != 1 else ''} linked to "
                f"{'these groups' if len(ids) > 1 else 'this group'} will be "
                "left without an incentive group." if n else "")

    def _noun(self, n: int) -> str:
        return self.mdef.singular + ("s" if n != 1 else "")

    def _after_bulk(self, message: str) -> None:
        self.reload()
        self.toast(message)
        self.saved.emit()

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------
    def _add_row(self) -> None:
        """Append an empty row with default values and start editing it."""
        values = {f.key: f.default for f in self.fields}
        if "effective_from" in values:
            values["effective_from"] = date.today()
        self._loading = True
        r = self._append_row(values, RowState(None, dict(values), dict(values)))
        self._loading = False
        self.search.clear()
        self.status_combo.setCurrentIndex(STATUS_ALL)
        if self.mdef.filter_field:
            self.filter_combo.setCurrentIndex(0)
        self._apply_filters()
        self.table.scrollToBottom()
        first = self._col[next(f.key for f in self.fields if f.required)]
        self.table.setCurrentCell(r, first)
        self.table.editItem(self.table.item(r, first))

    def _edit_row(self) -> None:
        """Open the Edit form for the selected (or single ticked) row and
        copy the result back into the cells."""
        row = self.table.currentRow()
        if row < 0 and len(self._ticked_rows()) == 1:
            row = self._ticked_rows()[0]
        if row < 0:
            self.toast(f"Select a {self.mdef.singular} to edit.")
            return
        values = self._row_values(row)
        values["effective_from"] = self._state(row).rate_date or \
            self._state(row).original.get("effective_from")
        dlg = EditDialog(self.mdef, values, self._row_name(row),
                         self.repo.lookup_names, self)
        if dlg.exec() != QDialog.Accepted:
            return
        new = dlg.values()
        # Apply field by field, exactly like typing into the cells, so the
        # same checks and the effective-date question happen.
        for f in self.fields:
            if f.kind == "date" or new.get(f.key) == values.get(f.key):
                continue
            item = self.table.item(row, self._col[f.key])
            if f.kind == "bool":
                item.setCheckState(Qt.Checked if new[f.key] else Qt.Unchecked)
            elif f.kind == "money":
                item.setText(format_inr(new[f.key]))
            else:
                item.setText(new[f.key])
        self._refresh_filter_values()
        self._apply_filters()

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

    def _show_history(self) -> None:
        row = self.table.currentRow()
        if row < 0 or self._state(row).is_new:
            self.toast(f"Select a saved {self.mdef.singular} to see its history.")
            return
        # Deleting a date reloads the tab, which would lose unsaved edits:
        # with unsaved edits the history is shown read-only.
        can_delete = not self.has_unsaved_changes()
        row_id = self._state(row).id
        dlg = RateHistoryDialog(self.mdef, self._row_name(row),
                                self.repo.rate_history(self.mdef.key, row_id), self,
                                repo=self.repo if can_delete else None, row_id=row_id)
        dlg.exec()
        if dlg.changed:
            self.reload()
            self.saved.emit()

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
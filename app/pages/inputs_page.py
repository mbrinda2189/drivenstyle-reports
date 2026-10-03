"""
inputs_page.py - "Monthly inputs" screen
========================================

WHAT THIS SCREEN DOES
---------------------
Collects the figures that are NOT on the invoices but are needed for the
reports, entered once per month and saved in the database
(app/data/inputs_repo.py):

    Indirect costs (left card)
        Expense heads (Rent, Salaries, Electricity, ...) and the month's
        amount for each. Add or remove heads; a running total is shown.
        "Copy from <month>" fills the table with the latest earlier month's
        heads and amounts, since most repeat. A month with nothing saved
        starts with the usual heads at zero.
        Used by report 10 (indirect vs direct cost %) and 12 (P&L).

    Report settings (right card)
        High-profit threshold (%): products whose margin is at or above
        this appear in report 9. Default 40%.

Changing the month shows that month's saved figures. Edits are held until
"Save inputs" (the heading shows "unsaved changes"); switching month or
closing with unsaved edits asks first. Duplicate heads and negative amounts
are refused. Every saved change is recorded in the audit log (Masters >
Audit log, "Monthly inputs").

SIGNALS
-------
    saved(int, int)   inputs were saved for (year, month)
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QMessageBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.data.inputs_repo import DEFAULT_HEADS, InputsRepo
from app.data.invoices_repo import month_key, month_label
from app.pages.base import ScrollPage
from app.theme import Colors
from app.utils import format_inr, parse_inr
from app.widgets.common import Card, button, label


class InputsPage(ScrollPage):
    """Monthly indirect costs and report settings."""

    saved = Signal(int, int)

    def __init__(self, inputs: InputsRepo, parent: QWidget | None = None):
        super().__init__(
            "Monthly inputs",
            "Figures that are not on the invoices: indirect costs for the P&L and report settings.",
            parent,
        )
        self.inputs = inputs
        self._loading = False
        self._dirty = False
        self._shown: tuple[int, int] | None = None

        columns = QHBoxLayout()
        columns.setSpacing(20)
        columns.addWidget(self._build_costs_card(), 3)
        right = QVBoxLayout()
        right.setSpacing(20)
        right.addWidget(self._build_settings_card())
        right.addStretch(1)
        columns.addLayout(right, 2)
        self.content.addLayout(columns, 1)
        self._load_month()

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------
    def _build_costs_card(self):
        card = Card()
        head = QHBoxLayout()
        head.addWidget(label("Indirect costs", "SectionTitle"))
        self.dirty_label = label("", "Muted")
        head.addWidget(self.dirty_label)
        head.addStretch(1)
        # This month and the 23 before it; last month is selected, as reports
        # are prepared for the month just ended.
        self.month_combo = QComboBox()
        today = QDate.currentDate()
        for back in range(0, 24):
            d = today.addMonths(-back)
            # Stored as "YYYY-MM" text: Qt cannot look up Python tuples.
            self.month_combo.addItem(month_label(d.year(), d.month()),
                                     month_key(d.year(), d.month()))
        self.month_combo.setCurrentIndex(1)
        self.month_combo.currentIndexChanged.connect(self._month_changed)
        head.addWidget(self.month_combo)
        card.body.addLayout(head)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Expense head", "Amount (₹)"])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setMinimumHeight(300)
        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 170)
        self.table.itemChanged.connect(self._on_changed)
        card.body.addWidget(self.table)

        # v0.8.1: two heads are not typed here - the reports work them out.
        card.body.addWidget(label(
            "Added automatically in the reports (do not enter them here): "
            "Breakage / returns / transport = 4% of COGS, and Compliance GST "
            "= 3% of COGS. COGS = product cost + labour of the month.",
            "Muted", wrap=True))

        total_row = QHBoxLayout()
        total_row.addWidget(label("Total indirect costs entered", "SectionTitle"))
        total_row.addStretch(1)
        self.total_label = label("0.00", "SectionTitle")
        self.total_label.setStyleSheet(f"color: {Colors.BLUE};")
        total_row.addWidget(self.total_label)
        card.body.addLayout(total_row)

        btns = QHBoxLayout()
        add = button("Add head", "Secondary")
        add.clicked.connect(self._add_head)
        remove = button("Remove", "Danger")
        remove.clicked.connect(self._remove_head)
        self.copy_btn = button("Copy from last month", "Ghost")
        self.copy_btn.clicked.connect(self._copy_previous)
        btns.addWidget(add)
        btns.addWidget(remove)
        btns.addWidget(self.copy_btn)
        btns.addStretch(1)
        save = button("Save inputs", "Primary")
        save.clicked.connect(self._save)
        btns.addWidget(save)
        card.body.addLayout(btns)
        return card

    def _build_settings_card(self):
        card = Card()
        card.body.addWidget(label("Report settings", "SectionTitle"))
        card.body.addWidget(label("High-profit threshold"))
        row = QHBoxLayout()
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 100)
        self.threshold.setSuffix(" %")
        self.threshold.setFixedWidth(110)
        self.threshold.valueChanged.connect(lambda _: self._mark_dirty())
        row.addWidget(self.threshold)
        row.addStretch(1)
        card.body.addLayout(row)
        card.body.addWidget(label(
            "Products with a margin at or above this are listed in the "
            "high-profit product sales report. Saved with the month's inputs.",
            "Muted", wrap=True))
        return card

    # ------------------------------------------------------------------
    # Month
    # ------------------------------------------------------------------
    def month(self) -> tuple[int, int]:
        year, month = self.month_combo.currentData().split("-")
        return int(year), int(month)

    def show_month(self, year: int, month: int) -> None:
        """Select a month (used when Generate sends the user here)."""
        i = self.month_combo.findData(month_key(year, month))
        if i >= 0:
            self.month_combo.setCurrentIndex(i)

    def _month_changed(self, *_) -> None:
        if self._dirty and self._shown and self._shown != self.month():
            answer = QMessageBox.question(
                self, "Unsaved inputs",
                f"Inputs for {month_label(*self._shown)} are not saved. Save them now?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Save
                                                and not self._save(self._shown)):
                self.month_combo.blockSignals(True)
                self.show_month(*self._shown)
                self.month_combo.blockSignals(False)
                return
        self._load_month()

    def _load_month(self) -> None:
        """Show the selected month's saved figures (or the usual heads at zero)."""
        year, month = self.month()
        rows = self.inputs.costs(year, month)
        if not rows:
            rows = [(h, 0.0) for h in DEFAULT_HEADS]
        self._fill(rows)
        self._loading = True
        self.threshold.setValue(int(round(self.inputs.threshold(year, month))))
        self._loading = False
        prev_label, prev = self.inputs.previous_costs(year, month)
        self.copy_btn.setText(f"Copy from {prev_label}" if prev else "Copy from last month")
        self.copy_btn.setEnabled(bool(prev))
        self._shown = (year, month)
        self._set_dirty(False)

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------
    def _fill(self, rows) -> None:
        self._loading = True
        self.table.setRowCount(0)
        for head, amount in rows:
            self._append(head, amount)
        self._loading = False
        self._update_total()

    def _append(self, head: str, amount: float) -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(head))
        amt = QTableWidgetItem(format_inr(amount))
        amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(r, 1, amt)
        return r

    def _rows(self) -> list[tuple[str, float]]:
        out = []
        for r in range(self.table.rowCount()):
            head = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            amount = parse_inr(self.table.item(r, 1).text()) if self.table.item(r, 1) else 0
            out.append((head, amount or 0.0))
        return out

    def _on_changed(self, item: QTableWidgetItem) -> None:
        """Re-format edited amounts, refresh the total, mark unsaved."""
        if self._loading:
            return
        if item.column() == 1:
            value = parse_inr(item.text())
            self._loading = True
            item.setText(format_inr(value if value is not None and value >= 0 else 0))
            self._loading = False
            if value is None or value < 0:
                self.toast("Enter a valid amount, e.g. 45000")
        self._update_total()
        self._mark_dirty()

    def _update_total(self) -> None:
        total = sum(a for _, a in self._rows())
        self.total_label.setText(f"₹ {format_inr(total)}")

    def _add_head(self) -> None:
        self._loading = True
        r = self._append("", 0.0)
        self._loading = False
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))
        self._mark_dirty()

    def _remove_head(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            self.toast("Select a row to remove.")
            return
        self.table.removeRow(r)
        self._update_total()
        self._mark_dirty()

    def _copy_previous(self) -> None:
        prev_label, prev = self.inputs.previous_costs(*self.month())
        if prev:
            self._fill(prev)
            self._mark_dirty()
            self.toast(f"{prev_label} figures copied. Adjust any that changed, then save.")

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        if not self._loading:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self.dirty_label.setText("· unsaved changes" if dirty else "")

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def _save(self, month: tuple[int, int] | None = None) -> bool:
        year, mon = month or self.month()
        try:
            self.inputs.save_costs(year, mon, self._rows())
        except ValueError as exc:
            QMessageBox.warning(self, "Inputs not saved", str(exc))
            return False
        self.inputs.save_threshold(year, mon, float(self.threshold.value()))
        self._set_dirty(False)
        self.toast(f"Inputs for {month_label(year, mon)} saved.")
        self.saved.emit(year, mon)
        return True
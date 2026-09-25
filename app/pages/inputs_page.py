"""
inputs_page.py - "Monthly inputs" screen
========================================

WHAT THIS SCREEN DOES
---------------------
Collects the figures that are NOT on the invoices but are needed for the
reports, entered once per month:

    Indirect costs (left card)
        A table of expense heads (Rent, Salaries, Electricity, ...) with the
        month's amount for each. The user can add or remove heads. A running
        total is shown underneath. "Copy from last month" refills the table
        with the previous month's figures, since most heads repeat.
        Used by: report 10 (indirect vs direct cost %) and report 12 (P&L).

    Report settings (right card)
        High-profit threshold (%): items whose margin is at or above this
        are listed in report 9 (high-profit product sales).

CURRENT BEHAVIOUR (v0.1.0 - UI preview)
---------------------------------------
Starts with the sample heads from sample_data.INDIRECT_COSTS. Editing, the
running total, add/remove and "Copy from last month" work on screen. Save
shows a confirmation only.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.pages.base import ScrollPage
from app.pages.generate_page import MONTHS
from app.sample_data import INDIRECT_COSTS
from app.theme import Colors
from app.utils import format_inr, parse_inr
from app.widgets.common import Card, button, label


class InputsPage(ScrollPage):
    """Monthly indirect costs and report settings."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Monthly inputs",
            "Figures that are not on the invoices: indirect costs for the P&L and report settings.",
            parent,
        )
        self._loading = False

        columns = QHBoxLayout()
        columns.setSpacing(20)
        columns.addWidget(self._build_costs_card(), 3)

        right = QVBoxLayout()
        right.setSpacing(20)
        right.addWidget(self._build_settings_card())
        right.addStretch(1)
        columns.addLayout(right, 2)
        self.content.addLayout(columns, 1)

        self._fill(INDIRECT_COSTS)

    # ------------------------------------------------------------------
    def _build_costs_card(self) -> Card:
        card = Card()
        head = QHBoxLayout()
        head.addWidget(label("Indirect costs", "SectionTitle"))
        head.addStretch(1)
        last = QDate.currentDate().addMonths(-1)
        self.month_combo = QComboBox()
        for back in range(0, 12):
            d = last.addMonths(-back)
            self.month_combo.addItem(f"{MONTHS[d.month() - 1]} {d.year()}")
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

        # Total line
        total_row = QHBoxLayout()
        total_row.addWidget(label("Total indirect costs", "SectionTitle"))
        total_row.addStretch(1)
        self.total_label = label("0.00", "SectionTitle")
        self.total_label.setStyleSheet(f"color: {Colors.BLUE};")
        total_row.addWidget(self.total_label)
        card.body.addLayout(total_row)

        # Buttons
        btns = QHBoxLayout()
        add = button("Add head", "Secondary")
        add.clicked.connect(self._add_head)
        remove = button("Remove", "Danger")
        remove.clicked.connect(self._remove_head)
        copy = button("Copy from last month", "Ghost")
        copy.clicked.connect(self._copy_last_month)
        btns.addWidget(add)
        btns.addWidget(remove)
        btns.addWidget(copy)
        btns.addStretch(1)
        save = button("Save inputs", "Primary")
        save.clicked.connect(lambda: self.toast(
            f"Inputs for {self.month_combo.currentText()} saved."))
        btns.addWidget(save)
        card.body.addLayout(btns)
        return card

    def _build_settings_card(self) -> Card:
        card = Card()
        card.body.addWidget(label("Report settings", "SectionTitle"))
        card.body.addWidget(label("High-profit threshold", ))
        row = QHBoxLayout()
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 100)
        self.threshold.setValue(40)
        self.threshold.setSuffix(" %")
        self.threshold.setFixedWidth(110)
        row.addWidget(self.threshold)
        row.addStretch(1)
        card.body.addLayout(row)
        card.body.addWidget(label(
            "Items with a margin at or above this are listed in the "
            "high-profit product sales report.", "Muted", wrap=True))
        return card

    # ------------------------------------------------------------------
    def _fill(self, rows) -> None:
        """Put (head, amount) rows into the table."""
        self._loading = True
        self.table.setRowCount(0)
        for head, amount in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(head))
            amt = QTableWidgetItem(format_inr(amount))
            amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, amt)
        self._loading = False
        self._update_total()

    def _on_changed(self, item: QTableWidgetItem) -> None:
        """Re-format edited amounts and refresh the total."""
        if self._loading or item.column() != 1:
            return
        value = parse_inr(item.text())
        self._loading = True
        item.setText(format_inr(value if value is not None and value >= 0 else 0))
        self._loading = False
        if value is None:
            self.toast("Enter a valid amount, e.g. 45000")
        self._update_total()

    def _update_total(self) -> None:
        total = 0.0
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 1)
            total += parse_inr(it.text()) or 0 if it else 0
        self.total_label.setText(f"₹ {format_inr(total)}")

    def _add_head(self) -> None:
        self._loading = True
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(""))
        amt = QTableWidgetItem(format_inr(0))
        amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(r, 1, amt)
        self._loading = False
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))

    def _remove_head(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            self.toast("Select a row to remove.")
            return
        self.table.removeRow(r)
        self._update_total()

    def _copy_last_month(self) -> None:
        self._fill(INDIRECT_COSTS)
        self.toast("Last month's figures copied. Adjust any that changed.")

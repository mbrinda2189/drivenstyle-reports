"""
tables.py - A plain read-only table, set up the same way on every page
======================================================================

The monthly tool learnt (v0.6.1) never to put a widget in every row of a
long table - scrolling lagged. The payout app's tables therefore hold
plain text only; controls for a row are built outside the table, for the
selected row alone. `make_table` gives every page the same behaviour:
whole-row selection, no editing, alternating rows, smooth scrolling,
left-aligned headings, amounts right-aligned with `money_item`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem)

from app.utils import format_inr


def make_table(headings: list[str], stretch: int, widths: dict[int, int] | None = None
               ) -> QTableWidget:
    """A read-only table. Column `stretch` takes the spare width."""
    table = QTableWidget(0, len(headings))
    table.setHorizontalHeaderLabels(headings)
    table.verticalHeader().hide()
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setWordWrap(True)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for i in range(len(headings)):
        header.setSectionResizeMode(
            i, QHeaderView.Stretch if i == stretch else QHeaderView.Interactive)
    for i, width in (widths or {}).items():
        table.setColumnWidth(i, width)
    return table


def text_item(text) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text if text is not None else ""))
    item.setToolTip(item.text())
    return item


def money_item(amount: float) -> QTableWidgetItem:
    item = QTableWidgetItem(format_inr(float(amount or 0)))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def fill(table: QTableWidget, rows: list[list]) -> None:
    """Replace the table's rows. A float cell is shown as an amount."""
    table.setRowCount(0)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, money_item(value) if isinstance(value, float)
                          else text_item(value))
    table.resizeRowsToContents()

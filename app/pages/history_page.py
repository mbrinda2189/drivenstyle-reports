"""
history_page.py - "History" screen
==================================

WHAT THIS SCREEN DOES
---------------------
Lists every month that has already been processed, newest first:

    Month | Invoices | Sales (Rs.) | Generated on | Actions

Actions for each month:
    Open        - open that month's Excel workbook
    Regenerate  - rebuild the workbook (e.g. after a correction in the
                  masters; earlier months still use the rates that applied
                  then, thanks to effective dates)

The stored history of processed months is also what feeds report 4
(month-on-month trend analysis).

CURRENT BEHAVIOUR (v0.1.0 - UI preview)
---------------------------------------
Rows come from sample_data.HISTORY. The buttons show a message only.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QTableWidget,
    QTableWidgetItem, QWidget,
)

from app.pages.base import ScrollPage
from app.sample_data import HISTORY
from app.utils import format_inr
from app.widgets.common import Card, button, label


class HistoryPage(ScrollPage):
    """Table of processed months with Open / Regenerate actions."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "History",
            "Months already processed. Their figures feed the month-on-month trend report.",
            parent,
        )
        card = Card()
        card.body.addWidget(label("Processed months", "SectionTitle"))

        table = QTableWidget(len(HISTORY), 5)
        table.setHorizontalHeaderLabels(
            ["Month", "Invoices", "Sales (₹)", "Generated on", ""])
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.verticalHeader().setDefaultSectionSize(48)
        hdr = table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 100), (2, 160), (3, 170), (4, 220)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            table.setColumnWidth(col, width)

        for r, (month, count, sales, generated) in enumerate(HISTORY):
            table.setItem(r, 0, QTableWidgetItem(month))
            for c, text in ((1, str(count)), (2, format_inr(sales))):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, it)
            table.setItem(r, 3, QTableWidgetItem(generated))

            actions = QWidget()
            a_lay = QHBoxLayout(actions)
            a_lay.setContentsMargins(6, 4, 6, 4)
            a_lay.setSpacing(4)
            open_btn = button("Open", "Ghost")
            open_btn.clicked.connect(
                lambda _=False, m=month: self.toast(f"Opening the {m} workbook (preview)."))
            regen_btn = button("Regenerate", "Ghost")
            regen_btn.clicked.connect(
                lambda _=False, m=month: self.toast(f"{m} will be regenerated (preview)."))
            a_lay.addWidget(open_btn)
            a_lay.addWidget(regen_btn)
            a_lay.addStretch(1)
            table.setCellWidget(r, 4, actions)

        table.setFixedHeight(hdr.height() + 48 * len(HISTORY) + 6)
        card.body.addWidget(table)
        card.body.addWidget(label("Sample months shown for the preview.", "Muted"))
        self.content.addWidget(card)
        self.content.addStretch(1)

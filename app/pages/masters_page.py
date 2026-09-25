"""
masters_page.py - "Masters" screen
==================================

WHAT THIS SCREEN DOES
---------------------
Shows and edits the masters the reports are calculated from. The client's
masters rarely change, so they are imported once from the client's Excel
sheets and kept in the tool's database; this screen is where occasional
changes are made.

Tabs:
    Products          SKU | Product name | HSN/SAC | Category |
                      Selling price | Cost price | Labour involved |
                      Labour charge | Effective from | Active
    Sales executives  Name | Phone | City | Active
    Cars              Make | Model | Segment | Active
    Packages          sample package definitions (read-only; the client's
                      four master sheets do not define packages yet)
    Incentive         placeholder: the incentive rules and the spot
                      incentive calculation are awaited from the client

The first three tabs are `MasterTable` widgets (app/widgets/master_table.py)
backed by the SQLite database: search, Import Excel (with column matching),
Export, Add row, Remove (marks inactive), rate history, and Save changes.

SIGNALS
-------
    mastersChanged()   a master was saved or imported; the main window uses
                       it to refresh "Masters in use" on the Generate page.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from app.data.master_defs import CARS, EXECUTIVES, PRODUCTS
from app.data.masters_repo import MastersRepo
from app.pages.base import ScrollPage
from app.sample_data import PACKAGES
from app.theme import Colors
from app.utils import format_inr
from app.widgets.common import Card, label
from app.widgets.master_table import MasterTable


def _notice(text: str, amber: bool = False) -> QWidget:
    """A tinted note: blue for information, amber for 'not final yet'."""
    note = label(text, wrap=True)
    bg, fg = ((Colors.AMBER_TINT, Colors.AMBER) if amber
              else (Colors.BLUE_TINT, Colors.INK))
    note.setStyleSheet(f"background: {bg}; color: {fg};"
                       "border-radius: 6px; padding: 10px 12px;")
    return note


class MastersPage(ScrollPage):
    """Tabs holding the master tables."""

    mastersChanged = Signal()

    def __init__(self, repo: MastersRepo, parent: QWidget | None = None):
        super().__init__(
            "Masters",
            "Products, sales executives and cars used to calculate the reports.",
            parent,
        )
        self.repo = repo

        card = Card()
        self.tabs = QTabWidget()
        card.body.addWidget(self.tabs)
        self.content.addWidget(card, 1)

        # --- Database-backed masters ---------------------------------------
        self.tables: dict[str, MasterTable] = {}
        for mdef in (PRODUCTS, EXECUTIVES, CARS):
            table = MasterTable(mdef, repo, self.toast)
            table.saved.connect(self.mastersChanged.emit)
            self.tables[mdef.key] = table
            self.tabs.addTab(table, mdef.title)

        # --- Packages (sample, read-only) ------------------------------------
        self.tabs.addTab(self._build_packages_tab(), "Packages")

        # --- Incentive (awaiting rules) --------------------------------------
        self.tabs.addTab(self._build_incentive_tab(), "Incentive")

    # ------------------------------------------------------------------
    def _build_packages_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(_notice(
            "Sample packages. Package definitions are not part of the client's "
            "master sheets yet; they are needed for the basic package "
            "analysis report.", amber=True))
        table = QTableWidget(len(PACKAGES), 3)
        table.setHorizontalHeaderLabels(["Package", "Items included", "Price (₹)"])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(40)
        hdr = table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        table.setColumnWidth(0, 180)
        table.setColumnWidth(2, 140)
        for r, (name, items, price) in enumerate(PACKAGES):
            table.setItem(r, 0, QTableWidgetItem(name))
            table.setItem(r, 1, QTableWidgetItem(items))
            p = QTableWidgetItem(format_inr(price))
            p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(r, 2, p)
        table.setFixedHeight(hdr.sizeHint().height() + 40 * len(PACKAGES) + 6)
        lay.addWidget(table)
        lay.addStretch(1)
        return page

    def _build_incentive_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label("Awaiting incentive rules", "SectionTitle"))
        lay.addWidget(label(
            "The incentive for each product, and how a discount reduces the "
            "spot incentive, will be set up here once the client confirms the "
            "rules. Until then the spot incentive report cannot be "
            "calculated.", "Muted", wrap=True))
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------
    def has_unsaved_changes(self) -> bool:
        """True if any master tab has edits that are not saved yet."""
        return any(t.has_unsaved_changes() for t in self.tables.values())

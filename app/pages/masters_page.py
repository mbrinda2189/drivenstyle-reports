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
                      Incentive group | Selling price | Cost price |
                      Labour involved | Labour charge | Effective from | Active
    Sales executives  Name | Contact no | Branch | Active
    Cars              Make | Model | Segment | Active
    Incentives        Product / Service | Incentive amount | Bill value |
                      Effective from | Active
    Packages          sample package definitions (read-only; the client's
                      master sheets do not define packages yet)
    Audit log         every change made to the masters (read-only)

The first four tabs are `MasterTable` widgets (app/widgets/master_table.py)
backed by the SQLite database: search, filter, status, Edit form, Import
Excel (with column matching), Export, Add row, tick-box selection with
Select all, Mark active / inactive, Delete, Delete all, rate history, and
Save changes. Every change is written to the audit log.

KEEPING TABS IN STEP
--------------------
When one master changes, the other tabs are reloaded (unless they have
unsaved edits, which are never thrown away) - e.g. renaming an incentive
group shows the new name in the Products tab's Incentive group column -
and the audit log is refreshed.

SIGNALS
-------
    mastersChanged()   a master was saved, imported or changed by a bulk
                       action; the main window uses it to refresh
                       "Masters in use" on the Generate page.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from app.data.master_defs import (
    CARS, EXECUTIVES, INCENTIVES, PACKAGE_ITEMS, PRODUCTS)
from app.data.masters_repo import MastersRepo
from app.pages.base import ScrollPage
from app.sample_data import PACKAGES
from app.theme import Colors
from app.utils import format_inr
from app.widgets.audit_view import AuditLogView
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
    """Tabs holding the master tables and the audit log."""

    mastersChanged = Signal()

    def __init__(self, repo: MastersRepo, parent: QWidget | None = None):
        super().__init__(
            "Masters",
            "Products, sales executives, cars and incentives used to "
            "calculate the reports.",
            parent,
        )
        self.repo = repo

        card = Card()
        self.tabs = QTabWidget()
        card.body.addWidget(self.tabs)
        self.content.addWidget(card, 1)

        # --- Database-backed masters ---------------------------------------
        self.tables: dict[str, MasterTable] = {}
        for mdef in (PRODUCTS, EXECUTIVES, CARS, INCENTIVES, PACKAGE_ITEMS):
            table = MasterTable(mdef, repo, self.toast)
            table.saved.connect(lambda key=mdef.key: self._on_master_saved(key))
            self.tables[mdef.key] = table
            if mdef is INCENTIVES:
                self.tabs.addTab(self._with_notice(table, (
                    "Each product is linked to one of these groups through "
                    "the Incentive group column on the Products tab. The spot "
                    "incentive calculation (incentive reduced when a discount "
                    "is given) will be added once the client confirms the "
                    "rules.")), mdef.title)
            elif mdef is PACKAGE_ITEMS:
                # v0.8.0: the real Packages master replaces the sample tab.
                self.tabs.addTab(self._with_notice(table, (
                    "One row = a Zoho item that counts as an item of a "
                    "package. An invoice is a package sale when every item "
                    "of the package is on it. The package's final value and "
                    "incentive come from the row with the same name in the "
                    "Incentive master.")), mdef.title)
            else:
                self.tabs.addTab(table, mdef.title)

        # --- Audit log ----------------------------------------------------------
        self.audit_view = AuditLogView(repo, self.toast)
        self.tabs.addTab(self.audit_view, "Audit log")

    # ------------------------------------------------------------------
    def _on_master_saved(self, key: str) -> None:
        """Reload the other master tabs (if they have no unsaved edits),
        refresh the audit log, and tell the main window."""
        for other_key, table in self.tables.items():
            if other_key != key and not table.has_unsaved_changes():
                table.reload()
        self.audit_view.show_latest()
        self.mastersChanged.emit()

    @staticmethod
    def _with_notice(widget: QWidget, text: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(_notice(text))
        lay.addWidget(widget)
        return page

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

    # ------------------------------------------------------------------
    def has_unsaved_changes(self) -> bool:
        """True if any master tab has edits that are not saved yet."""
        return any(t.has_unsaved_changes() for t in self.tables.values())
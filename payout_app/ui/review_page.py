"""
review_page.py - The Review screen: names that hold invoices up
===============================================================

WHAT THE STAFF DO HERE
----------------------
An invoice is not posted while something on it is unknown: an item that is
not in the Product master, a salesperson or a vehicle that is not found,
or totals that do not agree. After a scan this screen lists each such
thing ONCE, with the invoices it holds up ("Vehicle NIOS - 3 invoices").

Click a row; the panel below then offers, for that row only:

    Match to…        choose the master record the printed name stands for
                     (likely ones first), or "Others" for a salesperson or
                     vehicle that is deliberately not in the master.
                     "Save match and scan again" stores the choice in the
                     register's Matches tab - every PC uses it from then on
                     - and scans again, so the invoices are posted at once.
    Cancel invoice   for an invoice that should not be paid on at all:
                     choose the invoice, give the reason. Its unpaid lines
                     are cancelled; lines already paid are left alone and
                     named in a message.

If the name is really MISSING from the masters (a new executive, a new car
model), the right fix is to add it to the masters sheet and scan again -
the panel says so.

A match is saved even after a TRIAL run (it is a decision, not a payout).

COPY FROM THE MONTHLY TOOL
--------------------------
On the PC that also has the monthly reports tool, the matches chosen on
its Scan review can be copied: the button lists them, nothing is ticked,
and only the ticked ones are saved. (Brinda, 05-10-2026: they must be
approved one by one - some were trial choices.)

KEEPING IT FAST
---------------
The table holds plain text only; the drop-downs exist once, in the panel
(the monthly tool's lesson from v0.6.1).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLineEdit, QMessageBox, QTableWidgetItem, QVBoxLayout)

from app.pages.base import ScrollPage
from app.widgets.common import Card, NoWheelComboBox, button, fit_to_screen, label
from payout_app import engine, service
from payout_app.ui.tables import fill, make_table

OTHERS_CHOICE = "Others (not in the master)"


class ReviewPage(ScrollPage):
    rescanRequested = Signal()

    def __init__(self, window):
        super().__init__("Review", "Names on invoices that the masters do not know. "
                                   "Decide each once; the invoices are then posted.")
        self.win = window
        self.issues: list[engine.ReviewIssue] = []
        self.choices: dict[str, list[str]] = {}

        card = Card()
        top = QHBoxLayout()
        self.summary = label("Scan first - anything that needs a decision is "
                             "listed here.", "SectionTitle")
        top.addWidget(self.summary, 1)
        self.copy_button = button("Copy matches from the monthly tool…", "Secondary")
        self.copy_button.clicked.connect(self._copy_from_monthly)
        top.addWidget(self.copy_button)
        card.body.addLayout(top)
        self.table = make_table(["Kind", "Printed on invoice", "Invoices", "What is wrong"],
                                3, {0: 110, 1: 240, 2: 250})
        self.table.setMinimumHeight(280)
        self.table.currentCellChanged.connect(lambda *_: self._show_panel())
        card.body.addWidget(self.table)
        self.content.addWidget(card)

        # --- the panel for the selected row ---------------------------------
        self.panel = Card()
        self.panel_title = label("", "SectionTitle")
        self.panel.body.addWidget(self.panel_title)
        self.hint = label("", "Muted", wrap=True)
        self.panel.body.addWidget(self.hint)
        row = QHBoxLayout()
        self.match_label = label("Match to")
        row.addWidget(self.match_label)
        self.match_combo = NoWheelComboBox()
        self.match_combo.setMinimumWidth(420)
        self.match_combo.setMaxVisibleItems(18)
        row.addWidget(self.match_combo, 1)
        self.save_button = button("Save match and scan again", "Primary")
        self.save_button.clicked.connect(self._save_match)
        row.addWidget(self.save_button)
        self.panel.body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(label("Or cancel invoice"))
        self.invoice_combo = NoWheelComboBox()
        self.invoice_combo.setMinimumWidth(190)
        row.addWidget(self.invoice_combo)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Reason (required)")
        row.addWidget(self.reason, 1)
        self.cancel_button = button("Cancel invoice", "Danger")
        self.cancel_button.clicked.connect(self._cancel_invoice)
        row.addWidget(self.cancel_button)
        self.panel.body.addLayout(row)
        self.panel.hide()
        self.content.addWidget(self.panel)
        self.content.addStretch(1)

        window.busyChanged.connect(self._set_busy)
        self.copy_button.setVisible(bool(service.monthly_tool_matches()))

    def _set_busy(self, busy: bool) -> None:
        for control in (self.save_button, self.cancel_button, self.copy_button):
            control.setEnabled(not busy)

    # ------------------------------------------------------------------
    def show_report(self, report: service.ScanReport) -> None:
        """Called after every scan."""
        self.issues = list(report.issues)
        self.choices = report.choices
        invoices = len(report.review)
        if report.stopped:
            self.summary.setText("The last scan was stopped - see the Scan screen.")
        elif not self.issues:
            self.summary.setText("Nothing needs review.")
        else:
            self.summary.setText(f"{len(self.issues)} thing(s) to decide, holding up "
                                 f"{invoices} invoice(s)")
        fill(self.table, [[i.kind, i.printed or "–",
                           f"{len(i.invoices)}:  " + ", ".join(i.invoices), i.message]
                          for i in self.issues])
        self.panel.hide()
        if self.issues:
            self.table.setCurrentCell(0, 0)
            self._show_panel()

    def _current(self) -> engine.ReviewIssue | None:
        row = self.table.currentRow()
        return self.issues[row] if 0 <= row < len(self.issues) else None

    def _show_panel(self) -> None:
        issue = self._current()
        if issue is None:
            self.panel.hide()
            return
        self.panel_title.setText(f"{issue.kind}: “{issue.printed}”" if issue.printed
                                 else issue.kind)
        can_match = issue.kind in ("Item", "Salesperson", "Car") and bool(issue.printed)
        for control in (self.match_label, self.match_combo, self.save_button):
            control.setVisible(can_match)
        self.match_combo.clear()
        if can_match:
            self.match_combo.addItem("Choose…", "")
            for name in issue.suggestions:
                self.match_combo.addItem(f"{name}   (likely)", name)
            if issue.kind != "Item":
                self.match_combo.addItem(OTHERS_CHOICE, engine.OTHERS)
            for name in self.choices.get(issue.kind, []):
                if name not in issue.suggestions:
                    self.match_combo.addItem(name, name)
            master = {"Item": "Products", "Salesperson": "Sales executives",
                      "Car": "Cars"}[issue.kind]
            self.hint.setText(
                f"If this is only another way of writing a record that exists, choose "
                f"the record. If it is missing from the masters, add it to the “{master}” "
                f"tab of the masters sheet and scan again."
                + ("" if issue.kind == "Item" else " Choose “Others” for one that is "
                   "deliberately not in the master."))
        else:
            self.hint.setText("The figures printed on this invoice do not agree with "
                              "each other. Check the invoice in Zoho and save its PDF "
                              "again, or cancel it here.")
        self.invoice_combo.clear()
        for number in issue.invoices:
            self.invoice_combo.addItem(number, number)
        self.reason.clear()
        self.panel.show()

    # ------------------------------------------------------------------
    def _save_match(self) -> None:
        issue = self._current()
        target = self.match_combo.currentData()
        if issue is None or not target:
            self.win.toast("Choose what it should be matched to.")
            return

        def work(_progress):
            service.save_match(self.win.session, issue.kind, issue.printed, target)
            return target

        def done(saved: str) -> None:
            self.win.toast(f"“{issue.printed}” matched to {saved}.")
            self.rescanRequested.emit()

        self.win.run("Saving the match…", work, done)

    def _cancel_invoice(self) -> None:
        number = self.invoice_combo.currentData()
        reason = self.reason.text().strip()
        if not number:
            return
        if not reason:
            self.win.toast("Please give the reason for cancelling.")
            self.reason.setFocus()
            return
        answer = QMessageBox.question(
            self, "Cancel invoice",
            f"Cancel invoice {number}?\n\nIt will not be posted. Lines of it that are "
            "not yet paid are cancelled; paid lines are left as they are.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return

        def work(_progress):
            return service.cancel_invoice(self.win.session, number, reason)

        def done(paid: list[str]) -> None:
            if paid:
                QMessageBox.information(
                    self, "Cancel invoice",
                    f"Invoice {number} is cancelled.\n\nThese lines were already paid "
                    "and were left as they are:\n" + "\n".join(paid))
            else:
                self.win.toast(f"Invoice {number} cancelled.")
            self.rescanRequested.emit()

        self.win.run("Cancelling the invoice…", work, done)

    # ------------------------------------------------------------------
    def _copy_from_monthly(self) -> None:
        matches = service.monthly_tool_matches()
        dialog = CopyMatchesDialog(matches, self)
        if dialog.exec() != QDialog.Accepted or not dialog.chosen():
            return
        chosen = dialog.chosen()

        def work(_progress):
            for m in chosen:
                service.save_match(self.win.session, m["kind"], m["printed"], m["target"])
            return len(chosen)

        def done(count: int) -> None:
            self.win.toast(f"{count} match(es) copied.")
            self.rescanRequested.emit()

        self.win.run("Copying the matches…", work, done)


class CopyMatchesDialog(QDialog):
    """Tick the monthly tool's matches that should be used by the payout app."""

    def __init__(self, matches: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Copy matches from the monthly tool")
        self.matches = matches
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(label("Tick the matches to copy. Check each one - some may have "
                            "been trial choices.", "Muted", wrap=True))
        self.table = make_table(["Copy", "Kind", "Printed on invoice", "Matched to"], 3,
                                {0: 60, 1: 110, 2: 260})
        fill(self.table, [["", m["kind"], m["printed"], m["target"]] for m in matches])
        for row in range(len(matches)):
            box = QTableWidgetItem()
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            box.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, box)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = button("Close", "Secondary")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        copy = button("Copy ticked matches", "Primary")
        copy.clicked.connect(self.accept)
        row.addWidget(copy)
        lay.addLayout(row)
        fit_to_screen(self, 860, 560)

    def chosen(self) -> list[dict]:
        return [m for row, m in enumerate(self.matches)
                if self.table.item(row, 0).checkState() == Qt.Checked]

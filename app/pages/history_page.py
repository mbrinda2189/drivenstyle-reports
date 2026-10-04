"""
history_page.py - "History" screen
==================================

WHAT THIS SCREEN DOES
---------------------
Lists every month for which a workbook has been generated, newest first
(the latest workbook of each month), from the database
(inputs_repo.runs):

    Month | Invoices | Left out | Sales (₹) | Gross profit (₹) | Generated on | Actions

Actions for each month:
    Open        open that month's Excel workbook (if it is still where it
                was saved)
    Regenerate  write the workbook again with the same reports, folder and
                payments export - e.g. after fixing Scan review issues or
                correcting a rate in the masters. Earlier months still use
                the rates that applied then (effective dates).

The months' invoices themselves are kept in the database, which is what
report 4 (month-on-month trend) is built from.

SIGNALS
-------
    regenerated(int, int)   a month's workbook was written again
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QMessageBox,
    QTableWidget, QTableWidgetItem, QWidget,
)

from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import InvoicesRepo, month_label
from app.data.masters_repo import MastersRepo
from app.pages.base import ScrollPage
from app.reports.generate import GenerateError, generate, make_pdf
from app.reports.pdf_export import PdfError
from app.utils import format_inr
from app.widgets.common import Card, button, label

ROW = 48


class HistoryPage(ScrollPage):
    """Table of generated months with Open / Regenerate actions."""

    regenerated = Signal(int, int)
    monthRemoved = Signal(int, int)       # v0.10.1: a month's invoices were removed

    def __init__(self, masters: MastersRepo, invoices: InvoicesRepo,
                 inputs: InputsRepo, parent: QWidget | None = None):
        super().__init__(
            "History",
            "Workbooks already generated. Every scanned month also feeds the "
            "month-on-month trend report.",
            parent,
        )
        self.masters, self.invoices, self.inputs = masters, invoices, inputs
        card = Card()
        card.body.addWidget(label("Generated workbooks", "SectionTitle"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Month", "Invoices", "Left out", "Sales (₹)", "Gross profit (₹)",
             "Generated on", ""])
        t = self.table
        t.verticalHeader().hide()
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.verticalHeader().setDefaultSectionSize(ROW)
        hdr = t.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # v0.10.2: every column wide enough for its contents (the month
        # was cut to "S..." when the action buttons took the room). "Generated
        # on" fits the date, time and user; the action buttons take the
        # spare width (at least 340). On a narrow window the table scrolls
        # sideways instead of squeezing columns.
        for col, width in ((0, 150), (1, 80), (2, 80), (3, 140), (4, 150), (5, 230)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            t.setColumnWidth(col, width)
        hdr.setSectionResizeMode(6, QHeaderView.Stretch)
        hdr.setMinimumSectionSize(80)
        t.setColumnWidth(6, 340)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        card.body.addWidget(t)
        self.note = label("", "Muted")
        card.body.addWidget(self.note)
        self.content.addWidget(card)

        # --- Months read into the tool (v0.10.1) -----------------------------
        # Every month listed here feeds the Trend sheet. "Remove month" takes
        # a month read by mistake (or with trial data) out of the tool.
        months = Card()
        months.body.addWidget(label("Months read into the tool", "SectionTitle"))
        months.body.addWidget(label(
            "Every month here is part of the month-on-month trend. Removing a month takes "
            "out its invoices only: masters, saved name matches, Monthly inputs and the "
            "workbooks already saved are kept. Reading the month's export again brings "
            "it back.", "Muted", wrap=True))
        self.months_table = QTableWidget(0, 5)
        self.months_table.setHorizontalHeaderLabels(
            ["Month", "Invoices read", "Last read", "File read", ""])
        m = self.months_table
        m.verticalHeader().hide()
        m.setAlternatingRowColors(True)
        m.setEditTriggers(QAbstractItemView.NoEditTriggers)
        m.setSelectionMode(QAbstractItemView.NoSelection)
        m.setFocusPolicy(Qt.NoFocus)
        m.verticalHeader().setDefaultSectionSize(ROW)
        mh = m.horizontalHeader()
        mh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        mh.setSectionResizeMode(3, QHeaderView.Stretch)
        for col, width in ((0, 170), (1, 120), (2, 170), (4, 170)):
            mh.setSectionResizeMode(col, QHeaderView.Fixed)
            m.setColumnWidth(col, width)
        months.body.addWidget(m)
        self.months_note = label("", "Muted")
        months.body.addWidget(self.months_note)
        self.content.addWidget(months)
        self.content.addStretch(1)
        self.refresh()

    def refresh(self, *_) -> None:
        runs = self.inputs.runs()
        t = self.table
        t.setRowCount(len(runs))
        for r, run in enumerate(runs):
            year, month = map(int, run["month"].split("-"))
            t.setItem(r, 0, QTableWidgetItem(month_label(year, month)))
            for c, text in ((1, str(run["invoices"])), (2, str(run["left_out"])),
                            (3, format_inr(run["sales"])), (4, format_inr(run["gross_profit"]))):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, it)
            when = datetime.fromisoformat(run["generated_at"]).strftime("%d-%m-%Y %H:%M")
            it = QTableWidgetItem(when + (f"  ({run['user']})" if run["user"] else ""))
            it.setToolTip(run["file_path"])
            t.setItem(r, 5, it)

            actions = QWidget()
            lay = QHBoxLayout(actions)
            lay.setContentsMargins(6, 4, 6, 4)
            lay.setSpacing(4)
            open_btn = button("Open", "Ghost")
            open_btn.clicked.connect(lambda _=False, p=run["file_path"]: self._open(p))
            regen = button("Regenerate", "Ghost")
            regen.clicked.connect(lambda _=False, x=run: self._regenerate(x))
            pdf_btn = button("PDF", "Ghost")
            pdf_btn.setToolTip("Save this workbook as one PDF beside it and open it "
                               "(needs Microsoft Excel on this PC).")
            pdf_btn.clicked.connect(lambda _=False, x=run: self._pdf(x))
            remove = button("Remove", "Ghost")
            remove.setToolTip("Take this month out of this list. The Excel and PDF files "
                              "stay in their folder.")
            remove.clicked.connect(lambda _=False, x=run: self._remove_run(x))
            lay.addWidget(open_btn)
            lay.addWidget(pdf_btn)
            lay.addWidget(regen)
            lay.addWidget(remove)
            lay.addStretch(1)
            t.setCellWidget(r, 6, actions)
        t.setFixedHeight(t.horizontalHeader().height() + ROW * max(1, len(runs)) + 6)
        self.note.setText("" if runs else
                          "No workbooks yet. Scan a month and generate it on Generate reports.")
        self._fill_months()

    def _fill_months(self) -> None:
        rows = self.invoices.months_read()
        m = self.months_table
        m.setRowCount(len(rows))
        for r, row in enumerate(rows):
            year, month = map(int, row["month"].split("-"))
            m.setItem(r, 0, QTableWidgetItem(month_label(year, month)))
            n = QTableWidgetItem(str(row["invoices"]))
            n.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            m.setItem(r, 1, n)
            when = datetime.fromisoformat(row["scanned_at"]).strftime("%d-%m-%Y %H:%M")
            m.setItem(r, 2, QTableWidgetItem(when))
            source = QTableWidgetItem(Path(row["folder"]).name)
            source.setToolTip(row["folder"])
            m.setItem(r, 3, source)
            holder = QWidget()
            lay = QHBoxLayout(holder)
            lay.setContentsMargins(6, 4, 6, 4)
            remove = button("Remove month", "Danger")
            remove.clicked.connect(lambda _=False, y=year, mo=month, c=row["invoices"]:
                                   self._remove_month(y, mo, c))
            lay.addWidget(remove)
            lay.addStretch(1)
            m.setCellWidget(r, 4, holder)
        m.setFixedHeight(m.horizontalHeader().height() + ROW * max(1, len(rows)) + 6)
        self.months_note.setText("" if rows else "No month has been read yet.")

    def _remove_month(self, year: int, month: int, count: int) -> None:
        name = month_label(year, month)
        if QMessageBox.question(
                self, "Remove month",
                f"Remove {name} from the tool?\n\n"
                f"Its {count} invoice(s) will be taken out and {name} will no longer appear "
                "in the trend. Masters, saved name matches, Monthly inputs and saved "
                "workbooks are kept.\n\nTo bring the month back, read its invoice export "
                "again.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        done = self.invoices.remove_month(year, month)
        self.refresh()
        self.monthRemoved.emit(year, month)
        self.toast(f"{name} removed ({done} invoices).")

    def _remove_run(self, run: dict) -> None:
        year, month = map(int, run["month"].split("-"))
        name = month_label(year, month)
        if QMessageBox.question(
                self, "Remove from History",
                f"Remove {name} from this list?\n\nThe Excel and PDF files already saved "
                "are not deleted, and the month's invoices stay in the tool.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.inputs.remove_runs(year, month)
        self.refresh()
        self.toast(f"{name} removed from History.")

    def _pdf(self, run: dict) -> None:
        """
        The month's PDF (summary tables and graphs - app/reports/pdf_book.py),
        saved beside the workbook. It is built from the data as it is now.
        """
        year, month = map(int, run["month"].split("-"))
        files = [run["payments_path"], run.get("rto_path") or ""]
        payments, rto = [f if f and Path(f).exists() else "" for f in files]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pdf = make_pdf(self.masters, self.invoices, self.inputs, year, month,
                           run["file_path"], payments, rto)
        except (PdfError, GenerateError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "PDF not made", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.toast(f"{pdf.name} saved.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))

    def _open(self, path: str) -> None:
        if not Path(path).exists():
            self.toast("The workbook is no longer where it was saved. Regenerate it.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _regenerate(self, run: dict) -> None:
        year, month = map(int, run["month"].split("-"))
        payments = run["payments_path"]
        if payments and not Path(payments).exists():
            payments = ""
        rto = run.get("rto_path") or ""          # delivery list (v0.9.0)
        if rto and not Path(rto).exists():
            rto = ""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = generate(self.masters, self.invoices, self.inputs, year, month,
                              str(Path(run["file_path"]).parent),
                              json.loads(run["reports_json"]), payments, rto)
        except GenerateError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Workbook not created", str(exc))
            return
        QApplication.restoreOverrideCursor()
        note = "" if payments or not run["payments_path"] else \
            " (payments export no longer found; payment modes from invoices only)"
        self.toast(f"{result.path.name} regenerated{note}.")
        self.refresh()
        self.regenerated.emit(year, month)
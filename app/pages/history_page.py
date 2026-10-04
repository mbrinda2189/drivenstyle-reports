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
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 90), (2, 90), (3, 150), (4, 150), (5, 170), (6, 280)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            t.setColumnWidth(col, width)
        card.body.addWidget(t)
        self.note = label("", "Muted")
        card.body.addWidget(self.note)
        self.content.addWidget(card)
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
            lay.addWidget(open_btn)
            lay.addWidget(pdf_btn)
            lay.addWidget(regen)
            lay.addStretch(1)
            t.setCellWidget(r, 6, actions)
        t.setFixedHeight(t.horizontalHeader().height() + ROW * max(1, len(runs)) + 6)
        self.note.setText("" if runs else
                          "No workbooks yet. Scan a month and generate it on Generate reports.")

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
"""
generate_page.py - "Generate reports" screen (the main screen)
==============================================================

WHAT THIS SCREEN DOES
---------------------
This is where the monthly work happens. The user moves through a real
sequence, so the steps are numbered:

    1  Choose the report month          (defaults to last month, because
                                         reports are prepared before the 7th
                                         for the month just ended)
    2  Choose the invoice folder        (folder of Zoho invoice PDFs)
    3  Add the payments export          (optional - Zoho "Payments Received"
                                         export, needed only for the payment
                                         mode report)
    4  Choose where to save the Excel file

Below the steps, the user ticks which of the 12 reports to include.

On the right, a "Run" panel shows which master sheets are in use, the
"Scan invoices" and "Generate Excel" buttons, a progress bar and a log.

CURRENT BEHAVIOUR (v0.1.0 - UI preview)
---------------------------------------
* Folder and file choosers are real. After choosing the invoice folder, the
  page counts the actual PDF files in it.
* "Scan invoices" is SIMULATED: it steps through the real PDF file names with
  an animated progress bar but does not read them yet. When done it emits
  `scanFinished` so the Scan review page can show the sample issues.
* "Generate Excel" is SIMULATED: it animates through the selected reports and
  then shows a message. No file is written yet.

SIGNALS
-------
    scanFinished(int)   - emitted when a scan completes (number of PDFs)
    reviewRequested()   - user clicked "Review issues"
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDate, QEasingCurve, QPropertyAnimation, QTimer, Qt, Signal,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QProgressBar, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QColor

from app.pages.base import ScrollPage
from app.sample_data import REPORTS, SCAN_ISSUES
from app.theme import Colors
from app.widgets.common import Card, PathPicker, StepHeader, button, label

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def divider() -> QFrame:
    """A thin horizontal line used to separate steps inside a card."""
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {Colors.LINE};")
    return line


class GeneratePage(ScrollPage):
    """The main screen: choose inputs, scan invoices, generate the workbook."""

    scanFinished = Signal(int)
    reviewRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Generate reports",
            "Read the month's invoices and build the Excel workbook with the 12 reports.",
            parent,
        )
        self._scanned = False          # True once a scan has completed
        self._pdf_files: list[str] = []

        # Two columns: steps on the left (wider), run panel on the right.
        columns = QHBoxLayout()
        columns.setSpacing(20)
        self.content.addLayout(columns, 1)

        left = QVBoxLayout()
        left.setSpacing(20)
        left.addWidget(self._build_steps_card())
        left.addWidget(self._build_reports_card())
        left.addStretch(1)
        columns.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(20)
        right.addWidget(self._build_run_card())
        right.addStretch(1)
        columns.addLayout(right, 2)

        # Timers that drive the simulated scan / generate animations.
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._scan_step)
        self._gen_timer = QTimer(self)
        self._gen_timer.timeout.connect(self._generate_step)

        # Smoothly animates the progress bar value instead of jumping.
        self._bar_anim = QPropertyAnimation(self.progress, b"value", self)
        self._bar_anim.setDuration(180)
        self._bar_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._refresh_buttons()

    # ------------------------------------------------------------------
    # Building the cards
    # ------------------------------------------------------------------
    def _build_steps_card(self) -> Card:
        """Card with the four numbered input steps."""
        card = Card()
        card.body.setSpacing(16)

        # Step 1 - month (defaults to the previous month)
        self.step_month = StepHeader(1, "Report month",
                                     "Reports are prepared for the month just ended.")
        card.body.addWidget(self.step_month)
        last_month = QDate.currentDate().addMonths(-1)
        row = QHBoxLayout()
        row.setContentsMargins(36, 0, 0, 0)
        self.month_combo = QComboBox()
        self.month_combo.addItems(MONTHS)
        self.month_combo.setCurrentIndex(last_month.month() - 1)
        self.month_combo.setMinimumWidth(160)
        self.year_combo = QComboBox()
        years = [str(y) for y in range(2024, QDate.currentDate().year() + 2)]
        self.year_combo.addItems(years)
        self.year_combo.setCurrentText(str(last_month.year()))
        row.addWidget(self.month_combo)
        row.addWidget(self.year_combo)
        row.addStretch(1)
        card.body.addLayout(row)
        self.step_month.set_done(True)   # a month is always selected

        card.body.addWidget(divider())

        # Step 2 - invoice folder
        self.step_folder = StepHeader(2, "Invoice folder",
                                      "The folder of Zoho invoice PDFs for the month.")
        card.body.addWidget(self.step_folder)
        self.folder_picker = PathPicker("No folder chosen", mode="folder")
        self.folder_picker.layout().setContentsMargins(36, 0, 0, 0)
        self.folder_picker.pathChanged.connect(self._on_folder_chosen)
        card.body.addWidget(self.folder_picker)
        self.folder_info = label("", "Muted")
        self.folder_info.setContentsMargins(36, 0, 0, 0)
        self.folder_info.hide()
        card.body.addWidget(self.folder_info)

        card.body.addWidget(divider())

        # Step 3 - payments export (optional)
        self.step_payments = StepHeader(
            3, "Payments export (optional)",
            "Zoho ‘Payments Received’ export. Needed only for the payment mode report.")
        card.body.addWidget(self.step_payments)
        self.payments_picker = PathPicker(
            "No file chosen", mode="file",
            file_filter="Excel or CSV (*.xlsx *.xls *.csv)")
        self.payments_picker.layout().setContentsMargins(36, 0, 0, 0)
        self.payments_picker.pathChanged.connect(
            lambda p: self.step_payments.set_done(bool(p)))
        card.body.addWidget(self.payments_picker)

        card.body.addWidget(divider())

        # Step 4 - output folder
        self.step_output = StepHeader(4, "Save to",
                                      "Folder where the Excel workbook will be saved.")
        card.body.addWidget(self.step_output)
        self.output_picker = PathPicker("No folder chosen", mode="folder")
        self.output_picker.layout().setContentsMargins(36, 0, 0, 0)
        self.output_picker.pathChanged.connect(self._on_output_chosen)
        card.body.addWidget(self.output_picker)

        return card

    def _build_reports_card(self) -> Card:
        """Card with a checkbox for each of the 12 reports, in two columns."""
        card = Card()
        head = QHBoxLayout()
        head.addWidget(label("Reports to include", "SectionTitle"))
        head.addStretch(1)
        self.select_all_btn = button("Clear all", "Ghost")
        self.select_all_btn.clicked.connect(self._toggle_all_reports)
        head.addWidget(self.select_all_btn)
        card.body.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        self.report_checks: list[QCheckBox] = []
        half = (len(REPORTS) + 1) // 2
        for i, name in enumerate(REPORTS):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.setCursor(Qt.PointingHandCursor)
            cb.toggled.connect(self._on_report_toggled)
            self.report_checks.append(cb)
            grid.addWidget(cb, i % half, i // half)
        card.body.addLayout(grid)

        # Warning shown when the payment report is ticked without the export.
        self.payment_warning = label(
            "Payment mode analysis needs the payments export (step 3). "
            "Without it, that sheet will be marked incomplete.", wrap=True)
        self.payment_warning.setStyleSheet(
            f"background: {Colors.AMBER_TINT}; color: {Colors.AMBER};"
            "border-radius: 6px; padding: 8px 10px;")
        card.body.addWidget(self.payment_warning)
        self.payments_picker.pathChanged.connect(lambda _: self._on_report_toggled())
        return card

    def _build_run_card(self) -> Card:
        """Right-hand panel: masters in use, action buttons, progress and log."""
        card = Card()
        card.body.setSpacing(14)
        card.body.addWidget(label("Run", "SectionTitle"))

        # Masters in use (placeholder versions until real masters arrive).
        masters = QFrame()
        masters.setStyleSheet(
            f"background: {Colors.BLUE_TINT}; border-radius: 8px;")
        m_lay = QVBoxLayout(masters)
        m_lay.setContentsMargins(14, 10, 14, 10)
        m_lay.setSpacing(2)
        m_lay.addWidget(label("Masters in use", "Muted"))
        m_lay.addWidget(label("Cost sheet – sample data"))
        m_lay.addWidget(label("Labour charges – sample data"))
        card.body.addWidget(masters)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.scan_btn = button("Scan invoices", "Secondary")
        self.scan_btn.clicked.connect(self._start_scan)
        self.generate_btn = button("Generate Excel", "Primary")
        self.generate_btn.clicked.connect(self._start_generate)
        btn_row.addWidget(self.scan_btn, 1)
        btn_row.addWidget(self.generate_btn, 1)
        card.body.addLayout(btn_row)

        self.hint = label("", "Muted", wrap=True)
        card.body.addWidget(self.hint)

        # Progress
        self.status = label("Ready", "Muted")
        card.body.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(10)
        self.progress.setValue(0)
        card.body.addWidget(self.progress)

        # Result summary + review link (hidden until a scan completes)
        self.summary_row = QWidget()
        s_lay = QHBoxLayout(self.summary_row)
        s_lay.setContentsMargins(0, 0, 0, 0)
        self.summary = label("", wrap=True)
        s_lay.addWidget(self.summary, 1)
        self.review_btn = button("Review issues", "Ghost")
        self.review_btn.clicked.connect(self.reviewRequested.emit)
        s_lay.addWidget(self.review_btn)
        self.summary_row.hide()
        card.body.addWidget(self.summary_row)

        # Log of what happened, newest at the bottom.
        self.log = QListWidget()
        self.log.setMinimumHeight(230)
        self.log.setSelectionMode(QListWidget.NoSelection)
        self.log.setWordWrap(True)
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        card.body.addWidget(self.log)
        return card

    # ------------------------------------------------------------------
    # Reacting to user choices
    # ------------------------------------------------------------------
    def _on_folder_chosen(self, path: str) -> None:
        """Count the PDFs in the chosen folder and mark step 2 done."""
        folder = Path(path)
        self._pdf_files = sorted(p.name for p in folder.glob("*.pdf")) + \
            sorted(p.name for p in folder.glob("*.PDF"))
        count = len(self._pdf_files)
        self.folder_info.setText(
            f"{count} PDF file{'s' if count != 1 else ''} found in this folder."
            if count else "No PDF files found in this folder.")
        self.folder_info.show()
        self.step_folder.set_done(count > 0)
        self._scanned = False       # a new folder needs a fresh scan
        self.summary_row.hide()
        self._refresh_buttons()

    def _on_output_chosen(self, path: str) -> None:
        self.step_output.set_done(bool(path))
        self._refresh_buttons()

    def _toggle_all_reports(self) -> None:
        """Tick all reports if any is unticked, otherwise untick all."""
        any_unchecked = any(not cb.isChecked() for cb in self.report_checks)
        for cb in self.report_checks:
            cb.setChecked(any_unchecked)

    def _on_report_toggled(self, *_):
        """Keep the 'Select all / Clear all' label and warning in step."""
        all_checked = all(cb.isChecked() for cb in self.report_checks)
        self.select_all_btn.setText("Clear all" if all_checked else "Select all")
        payment_report = self.report_checks[REPORTS.index("Payment mode analysis")]
        self.payment_warning.setVisible(
            payment_report.isChecked() and not self.payments_picker.path())
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        """
        Enable buttons only when their inputs are ready, and explain what is
        missing in the hint line so the user is never stuck guessing.
        """
        busy = self._scan_timer.isActive() or self._gen_timer.isActive()
        has_folder = bool(self._pdf_files)
        has_output = bool(self.output_picker.path())
        any_report = any(cb.isChecked() for cb in self.report_checks)

        self.scan_btn.setEnabled(has_folder and not busy)
        self.generate_btn.setEnabled(
            self._scanned and has_output and any_report and not busy)

        if busy:
            self.hint.setText("")
        elif not has_folder:
            self.hint.setText("Choose the invoice folder to start.")
        elif not self._scanned:
            self.hint.setText("Scan the invoices to check them before generating.")
        elif not has_output:
            self.hint.setText("Choose where to save the workbook.")
        elif not any_report:
            self.hint.setText("Tick at least one report.")
        else:
            self.hint.setText("Ready to generate.")

    # ------------------------------------------------------------------
    # Simulated scan
    # ------------------------------------------------------------------
    def _set_progress(self, value: int) -> None:
        """Animate the progress bar to `value` (0-100)."""
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self.progress.value())
        self._bar_anim.setEndValue(value)
        self._bar_anim.start()

    def _add_log(self, text: str, color: str = Colors.INK) -> None:
        item = QListWidgetItem(text)
        item.setForeground(QColor(color))
        self.log.addItem(item)
        self.log.scrollToBottom()

    def _start_scan(self) -> None:
        """Begin the simulated scan: one PDF every 45 ms."""
        self.log.clear()
        self.summary_row.hide()
        self.progress.setValue(0)
        self._scan_index = 0
        self._add_log(f"Scanning {len(self._pdf_files)} files…", Colors.SLATE)
        self._scan_timer.start(45)
        self._refresh_buttons()

    def _scan_step(self) -> None:
        """Advance the simulated scan by one file."""
        total = len(self._pdf_files)
        if self._scan_index >= total:
            self._scan_timer.stop()
            self._finish_scan()
            return
        name = self._pdf_files[self._scan_index]
        self._scan_index += 1
        self.status.setText(f"Reading {self._scan_index} of {total}  ·  {name}")
        self._set_progress(int(self._scan_index * 100 / total))
        self._add_log(f"✓  {name}", Colors.GREEN)

    def _finish_scan(self) -> None:
        """Show the (sample) scan result and notify the Scan review page."""
        self._scanned = True
        open_issues = sum(1 for i in SCAN_ISSUES if i[2] not in ("skip", "open"))
        skipped = sum(1 for i in SCAN_ISSUES if i[2] in ("skip", "open"))
        self.status.setText("Scan complete")
        self._add_log(f"⚠  {open_issues} invoices need attention (sample)", Colors.AMBER)
        self.summary.setText(
            f"{len(self._pdf_files)} files scanned  ·  "
            f"{open_issues} need attention  ·  {skipped} skipped")
        self.summary_row.show()
        self.scanFinished.emit(len(self._pdf_files))
        self._refresh_buttons()
        self.toast("Scan complete. Review the issues before generating.")

    # ------------------------------------------------------------------
    # Simulated generate
    # ------------------------------------------------------------------
    def _start_generate(self) -> None:
        """Begin the simulated generation: one report sheet every 180 ms."""
        self._gen_reports = [cb.text() for cb in self.report_checks if cb.isChecked()]
        self._gen_index = 0
        self.progress.setValue(0)
        self._add_log("Building workbook…", Colors.SLATE)
        self._gen_timer.start(180)
        self._refresh_buttons()

    def _generate_step(self) -> None:
        total = len(self._gen_reports)
        if self._gen_index >= total:
            self._gen_timer.stop()
            month = f"{self.month_combo.currentText()[:3]}-{self.year_combo.currentText()}"
            self.status.setText("Workbook ready (preview)")
            self._add_log(f"Preview only: DriveNStyle_{month}_Reports.xlsx "
                          "will be written once the reports are built.", Colors.BLUE)
            self._refresh_buttons()
            self.toast("Preview only – the Excel file will be created once "
                       "the master sheets and report logic are added.")
            return
        name = self._gen_reports[self._gen_index]
        self._gen_index += 1
        self.status.setText(f"Building sheet {self._gen_index} of {total}  ·  {name}")
        self._set_progress(int(self._gen_index * 100 / total))
        self._add_log(f"✓  {name}", Colors.GREEN)

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

On the right, a "Run" panel shows how many products, sales executives,
cars and incentive groups are loaded (amber if a master is still empty), the
"Scan invoices" and "Generate Excel" buttons, a progress bar and a log.

SCANNING (v0.4.0)
-----------------
"Scan invoices" reads every PDF in the invoice folder in a background
thread (app/scan_worker.py), so the window stays responsive:
    * each file is logged as it is read: ✓ read, – skipped (another month,
      another firm, repeated invoice number), ✗ could not be read
    * the results are saved in the database for the chosen month
      (invoices_repo.store_scan), replacing any earlier scan of that month;
      fixes already made on Scan review are kept
    * the summary shows invoices read, issues open and files skipped, and
      the Scan review page is refreshed
"Cancel" stops after the current file; nothing is saved then.

When a month that has already been scanned is selected, its last scan is
shown (date, counts) and Generate is available without scanning again.

CURRENT BEHAVIOUR
-----------------
* "Generate Excel" is still SIMULATED: the reports are built in v0.5.0.
* "Masters in use" shows real counts from the masters database.

SIGNALS
-------
    scanFinished(int, int)  - a scan was saved (year, month)
    reviewRequested()       - user clicked "Review issues"
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDate, QEasingCurve, QPropertyAnimation, QThread, QTimer, Qt, Signal,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QProgressBar, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QColor

from app.data.invoices_repo import InvoicesRepo, month_label
from app.pages.base import ScrollPage
from app.sample_data import REPORTS
from app.scan_worker import ScanWorker
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

    scanFinished = Signal(int, int)
    reviewRequested = Signal()

    def __init__(self, invoices: InvoicesRepo, parent: QWidget | None = None):
        super().__init__(
            "Generate reports",
            "Read the month's invoices and build the Excel workbook with the 12 reports.",
            parent,
        )
        self.invoices = invoices
        self._scanned = False          # True once the chosen month is scanned
        self._pdf_files: list[Path] = []
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None

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

        # Timer that drives the simulated generate animation (until v0.5.0).
        self._gen_timer = QTimer(self)
        self._gen_timer.timeout.connect(self._generate_step)

        # Smoothly animates the progress bar value instead of jumping.
        self._bar_anim = QPropertyAnimation(self.progress, b"value", self)
        self._bar_anim.setDuration(180)
        self._bar_anim.setEasingCurve(QEasingCurve.OutCubic)

        self.month_combo.currentIndexChanged.connect(self._on_month_changed)
        self.year_combo.currentIndexChanged.connect(self._on_month_changed)
        self._on_month_changed()

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
            "Payment mode analysis uses the payment mode printed on the "
            "invoice, or the payments export (step 3) where it is not printed.", wrap=True)
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

        # Masters in use: how many active rows each master holds. Filled by
        # set_master_counts(), called by the main window at start-up and
        # whenever a master is saved or imported.
        masters = QFrame()
        masters.setStyleSheet(
            f"background: {Colors.BLUE_TINT}; border-radius: 8px;")
        m_lay = QVBoxLayout(masters)
        m_lay.setContentsMargins(14, 10, 14, 10)
        m_lay.setSpacing(2)
        m_lay.addWidget(label("Masters in use", "Muted"))
        self.master_labels: dict[str, QLabel] = {}
        for key in ("products", "executives", "cars", "incentives"):
            self.master_labels[key] = label("")
            m_lay.addWidget(self.master_labels[key])
        self.masters_hint = label("Load them on the Masters screen.", "Muted")
        self.masters_hint.hide()
        m_lay.addWidget(self.masters_hint)
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
    # Masters in use
    # ------------------------------------------------------------------
    def set_master_counts(self, counts: dict[str, int]) -> None:
        """
        Show how many active products / executives / cars are loaded.
        An empty master is shown in amber with a pointer to the Masters
        screen, since the reports cannot be calculated without it.
        """
        names = {"products": ("product", "Products"),
                 "executives": ("sales executive", "Sales executives"),
                 "cars": ("car", "Cars"),
                 "incentives": ("incentive group", "Incentives")}
        any_empty = False
        for key, lbl in self.master_labels.items():
            singular, title = names[key]
            n = counts.get(key, 0)
            if n:
                lbl.setText(f"{n} {singular}{'s' if n != 1 else ''}")
                lbl.setStyleSheet("")
            else:
                lbl.setText(f"{title} – not loaded yet")
                lbl.setStyleSheet(f"color: {Colors.AMBER};")
                any_empty = True
        self.masters_hint.setVisible(any_empty)

    # ------------------------------------------------------------------
    # Reacting to user choices
    # ------------------------------------------------------------------
    def selected_month(self) -> tuple[int, int]:
        return int(self.year_combo.currentText()), self.month_combo.currentIndex() + 1

    def _on_month_changed(self, *_) -> None:
        """Show the chosen month's last scan, if there is one."""
        if self._thread is not None:
            return
        year, month = self.selected_month()
        run = self.invoices.scan_run(year, month)
        self._scanned = run is not None
        self.log.clear()
        self.progress.setValue(0)
        if run:
            self._show_summary(year, month)
            when = run["scanned_at"].replace("T", " ")[:16]
            self.status.setText(f"{month_label(year, month)} last scanned {when}.")
        else:
            self.summary_row.hide()
            self.status.setText("Ready")
        self._refresh_buttons()

    def _on_folder_chosen(self, path: str) -> None:
        """Count the PDFs in the chosen folder and mark step 2 done."""
        folder = Path(path)
        # One list, compared in lower case: on Windows "*.pdf" and "*.PDF"
        # find the same files, so two separate searches counted each twice.
        self._pdf_files = sorted((p for p in folder.iterdir()
                                  if p.is_file() and p.suffix.lower() == ".pdf"),
                                 key=lambda p: p.name.lower()) if folder.is_dir() else []
        count = len(self._pdf_files)
        self.folder_info.setText(
            f"{count} PDF file{'s' if count != 1 else ''} found in this folder."
            if count else "No PDF files found in this folder.")
        self.folder_info.show()
        self.step_folder.set_done(count > 0)
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
        busy = self._thread is not None or self._gen_timer.isActive()
        has_folder = bool(self._pdf_files)
        has_output = bool(self.output_picker.path())
        any_report = any(cb.isChecked() for cb in self.report_checks)

        self.scan_btn.setEnabled(has_folder and self._gen_timer.isActive() is False)
        self.scan_btn.setText("Cancel scan" if self._thread is not None
                              else "Scan invoices")
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
    # Scanning (background thread)
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
        """Start reading the folder in the background (or cancel a running scan)."""
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Stopping after the current file…")
            return
        year, month = self.selected_month()
        self.log.clear()
        self.summary_row.hide()
        self.progress.setValue(0)
        self._add_log(f"Reading {len(self._pdf_files)} files for "
                      f"{month_label(year, month)}…", Colors.SLATE)

        self._thread = QThread(self)
        self._worker = ScanWorker(list(self._pdf_files), year, month)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_scan_progress)
        self._worker.finished.connect(self._on_scan_finished)
        self._thread.start()
        self._refresh_buttons()

    def _on_scan_progress(self, done: int, total: int, name: str,
                          status: str, reason: str) -> None:
        """One file read: log it and move the progress bar."""
        self.status.setText(f"Reading {done} of {total}  ·  {name}")
        self._set_progress(int(done * 100 / max(total, 1)))
        if status == "read":
            self._add_log(f"✓  {name}", Colors.GREEN)
        elif status == "skipped":
            self._add_log(f"–  {name}: {reason}", Colors.SLATE)
        else:
            self._add_log(f"✗  {name}: {reason}", Colors.RED)

    def _on_scan_finished(self, results: list) -> None:
        """Save the results (unless cancelled) and update the summary."""
        cancelled = self._worker.is_cancelled if self._worker else False
        self._thread.quit()
        self._thread.wait()
        self._thread, self._worker = None, None
        year, month = self.selected_month()
        if cancelled:
            self.status.setText("Scan cancelled. Nothing was saved.")
            self._add_log("Scan cancelled – nothing was saved.", Colors.AMBER)
            self._refresh_buttons()
            return
        counts = self.invoices.store_scan(
            year, month, str(Path(self.folder_picker.path())), results)
        self._scanned = True
        self._bar_anim.stop()
        self.progress.setValue(100)
        self.status.setText("Scan complete")
        self._show_summary(year, month)
        open_n = sum(1 for i in self.invoices.issues(year, month) if i.status == "open")
        self._add_log(f"{counts['read']} invoices read, {open_n} issue"
                      f"{'s' if open_n != 1 else ''} to review.",
                      Colors.AMBER if open_n else Colors.GREEN)
        self.scanFinished.emit(year, month)
        self._refresh_buttons()
        self.toast("Scan complete. Review the issues before generating."
                   if open_n else "Scan complete. No issues found.")

    def _show_summary(self, year: int, month: int) -> None:
        """'34 invoices read · 5 need attention · 2 skipped' + Review link."""
        files = self.invoices.scan_files(year, month)
        read = sum(f["status"] == "read" for f in files)
        skipped = len(files) - read
        open_n = sum(1 for i in self.invoices.issues(year, month) if i.status == "open")
        self.summary.setText(
            f"{read} invoice{'s' if read != 1 else ''} read  ·  "
            f"{open_n} need{'s' if open_n == 1 else ''} attention  ·  {skipped} skipped")
        self.summary_row.show()

    def refresh_summary(self) -> None:
        """Called when masters change or an issue is fixed elsewhere."""
        if self._scanned and self._thread is None:
            self._show_summary(*self.selected_month())

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
                       "the invoice reader and report logic are added.")
            return
        name = self._gen_reports[self._gen_index]
        self._gen_index += 1
        self.status.setText(f"Building sheet {self._gen_index} of {total}  ·  {name}")
        self._set_progress(int(self._gen_index * 100 / total))
        self._add_log(f"✓  {name}", Colors.GREEN)
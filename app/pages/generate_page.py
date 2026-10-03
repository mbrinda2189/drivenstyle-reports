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
    2  Choose the invoice export        (Zoho Books invoice export,
                                         Invoice.csv or .xlsx - v0.6.0)
    3  Add the payments export          (optional - Zoho "Payments Received"
                                         export, needed only for the payment
                                         mode report)
    4  Add the delivery (RTO) list      (optional - the dealership's list of
                                         cars delivered in the month; adds
                                         the new-car sheets 13-17 and the
                                         new-car part of the Summary, v0.9.0)
    5  Choose where to save the Excel file

Below the steps, the user ticks which of the 12 reports to include.

On the right, a "Run" panel shows how many products, sales executives,
cars and incentive groups are loaded (amber if a master is still empty), the
"Scan invoices" and "Generate Excel" buttons, a progress bar and a log.

READING THE INVOICES (v0.6.0: from Zoho's invoice export)
--------------------------------------------------------
"Read invoices" reads the export chosen in step 2 (invoice_export.py). It
takes under a second, so it runs directly (the PDF reader and its
background thread, app/scan_worker.py, stay in the code but are no longer
used on this screen):
    * the chosen month's invoices are kept; invoices dated in other months
      are counted in the log and ignored (an export may cover a quarter)
    * Void / Draft invoices and another firm's invoices are listed as
      skipped
    * the results are saved in the database for the chosen month
      (invoices_repo.store_scan), replacing any earlier reading of that
      month; fixes already made on Scan review are kept
    * the summary shows invoices read, issues open and invoices skipped,
      and the Scan review page is refreshed
    * products whose Category was never set by hand take Zoho's Item Type
      (goods / service) - the log says how many changed

When a month that has already been scanned is selected, its last scan is
shown (date, counts) and Generate is available without scanning again.

GENERATING (v0.5.0)
-------------------
"Generate Excel" writes DriveNStyle_<Mon>-<YYYY>_Reports.xlsx in the "Save
to" folder with the ticked reports (app/reports). Before writing it asks
for confirmation if:
    * issues are still open on Scan review - those invoices are left out
      of every report and listed on the workbook's "Not included" sheet
    * no indirect costs were entered on Monthly inputs for the month - the
      P&L and cost % reports then show them as zero
The payments export (step 3) is used for the payment mode report when
chosen. Afterwards "Open workbook" opens the file, and the run is listed on
the History screen. If the file is open in Excel, a message asks to close
it and try again.

"Masters in use" shows real counts from the masters database.

SIGNALS
-------
    scanFinished(int, int)  - a scan was saved (year, month)
    reviewRequested()       - user clicked "Review issues"
    generated(int, int)     - a workbook was written (year, month)
    inputsRequested()       - user chose to enter Monthly inputs first
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDate, QEasingCurve, QPropertyAnimation, QUrl, Qt, Signal,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QColor, QDesktopServices

from app.data.inputs_repo import InputsRepo
from app.data.invoice_export import ExportFileError, classify_export
from app.data.invoices_repo import (
    FIRM_GSTIN, ZOHO_CATEGORY_SOURCE, InvoicesRepo, month_label)
from app.data.masters_repo import MastersRepo
from app.reports.generate import GenerateError, generate
from app.pages.base import ScrollPage
from app.sample_data import REPORTS
from app.theme import Colors
from app.utils import format_inr
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
    generated = Signal(int, int)
    inputsRequested = Signal()

    def __init__(self, invoices: InvoicesRepo, masters: MastersRepo,
                 inputs: InputsRepo, parent: QWidget | None = None):
        super().__init__(
            "Generate reports",
            "Read the month's invoices and build the Excel workbook with the 12 reports.",
            parent,
        )
        self.invoices = invoices
        self.masters = masters
        self.inputs = inputs
        self._last_workbook: Path | None = None
        self._scanned = False          # True once the chosen month is read
        self._busy = False             # reading or generating right now

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

        # Step 2 - invoice export (v0.6.0; replaces the folder of PDFs)
        self.step_folder = StepHeader(
            2, "Invoice export",
            "Zoho Books › Sales › Invoices › Export (CSV or XLSX) covering the month.")
        card.body.addWidget(self.step_folder)
        self.folder_picker = PathPicker(
            "No file chosen", mode="file",
            file_filter="Zoho invoice export (*.csv *.xlsx *.xlsm)")
        self.folder_picker.layout().setContentsMargins(36, 0, 0, 0)
        self.folder_picker.pathChanged.connect(self._on_export_chosen)
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

        # Step 4 - delivery (RTO) list (optional, v0.9.0)
        self.step_rto = StepHeader(
            4, "Delivery (RTO) list (optional)",
            "The dealership's list of cars delivered in the month. Adds the new-car "
            "sheets (penetration, missed opportunity, list vs invoices, scorecard).")
        card.body.addWidget(self.step_rto)
        self.rto_picker = PathPicker(
            "No file chosen", mode="file", file_filter="Excel workbook (*.xlsx)")
        self.rto_picker.layout().setContentsMargins(36, 0, 0, 0)
        self.rto_picker.pathChanged.connect(lambda p: self.step_rto.set_done(bool(p)))
        card.body.addWidget(self.rto_picker)

        card.body.addWidget(divider())

        # Step 5 - output folder
        self.step_output = StepHeader(5, "Save to",
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
        self.scan_btn = button("Read invoices", "Secondary")
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

        # Shown after a workbook is written.
        self.open_btn = button("Open workbook", "Secondary")
        self.open_btn.clicked.connect(self._open_workbook)
        self.open_btn.hide()
        card.body.addWidget(self.open_btn)

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
        if self._busy:
            return
        year, month = self.selected_month()
        run = self.invoices.scan_run(year, month)
        self._scanned = run is not None
        # "Open workbook" for the month's latest workbook, if it still exists.
        last = next((r for r in self.inputs.runs() if r["month"] == f"{year:04d}-{month:02d}"), None)
        self._last_workbook = Path(last["file_path"]) if last else None
        self.open_btn.setVisible(bool(self._last_workbook and self._last_workbook.exists()))
        self.log.clear()
        self.progress.setValue(0)
        if run:
            self._show_summary(year, month)
            when = run["scanned_at"].replace("T", " ")[:16]
            self.status.setText(f"{month_label(year, month)} invoices last read {when}.")
        else:
            self.summary_row.hide()
            self.status.setText("Ready")
        self._refresh_buttons()

    def _export_path(self) -> Path | None:
        """The chosen export file, if it (still) exists."""
        path = self.folder_picker.path()
        return Path(path) if path and Path(path).is_file() else None

    def _on_export_chosen(self, path: str) -> None:
        """Mark step 2 done when a file is chosen (it is read on "Read invoices")."""
        ok = self._export_path() is not None
        self.folder_info.setText(f"{Path(path).name} chosen. Click “Read invoices”."
                                 if ok else "The file was not found.")
        self.folder_info.show()
        self.step_folder.set_done(ok)
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
        busy = self._busy
        has_folder = self._export_path() is not None
        has_output = bool(self.output_picker.path())
        any_report = any(cb.isChecked() for cb in self.report_checks)

        self.scan_btn.setEnabled(has_folder and not busy)
        self.generate_btn.setEnabled(
            self._scanned and has_output and any_report and not busy)

        if busy:
            self.hint.setText("")
        elif not has_folder and not self._scanned:
            self.hint.setText("Choose the invoice export to start.")
        elif not self._scanned:
            self.hint.setText("Read the invoices to check them before generating.")
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
        """Read the chosen export for the chosen month and save the result."""
        path = self._export_path()
        if path is None:
            self.toast("Choose the invoice export first.")
            return
        year, month = self.selected_month()
        label_ = month_label(year, month)
        self.log.clear()
        self.summary_row.hide()
        self.progress.setValue(0)
        self._add_log(f"Reading {path.name} for {label_}…", Colors.SLATE)
        self._busy = True
        self._refresh_buttons()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            scan = classify_export(path, year, month, FIRM_GSTIN)
        except ExportFileError as exc:
            QApplication.restoreOverrideCursor()
            self._busy = False
            self.status.setText("The export could not be read.")
            self._add_log(f"✗  {exc}", Colors.RED)
            QMessageBox.warning(self, "Invoice export", str(exc))
            self._refresh_buttons()
            return
        if not scan.results:
            QApplication.restoreOverrideCursor()
            self._busy = False
            self.status.setText(f"No {label_} invoices in this export.")
            self._add_log(f"✗  No invoice in {path.name} is dated in {label_} "
                          f"({scan.other_months} invoices from other months). "
                          "Nothing was saved.", Colors.RED)
            self._refresh_buttons()
            return
        before = self._category_changes()
        counts = self.invoices.store_scan(year, month, str(path), scan.results)
        changed = self._category_changes() - before
        QApplication.restoreOverrideCursor()
        self._busy = False
        self._scanned = True

        for r in scan.results:
            if r.status == "skipped":
                self._add_log(f"–  {r.file_name}: {r.reason}", Colors.SLATE)
            elif r.status == "error":
                self._add_log(f"✗  {r.file_name}: {r.reason}", Colors.RED)
        self._add_log(f"✓  {counts['read']} invoices ({scan.rows} lines in the file) "
                      f"read for {label_}.", Colors.GREEN)
        if scan.other_months:
            self._add_log(f"–  {scan.other_months} invoice{'s' if scan.other_months != 1 else ''}"
                          " dated in other months ignored.", Colors.SLATE)
        if changed:
            self._add_log(f"–  Category set from Zoho's item type for {changed} "
                          f"product{'s' if changed != 1 else ''} (see the audit log).",
                          Colors.SLATE)
        self._set_progress(100)
        self.status.setText("Invoices read")
        self._show_summary(year, month)
        open_n = sum(1 for i in self.invoices.issues(year, month) if i.status == "open")
        self._add_log(f"{open_n} issue{'s' if open_n != 1 else ''} to review.",
                      Colors.AMBER if open_n else Colors.GREEN)
        self.scanFinished.emit(year, month)
        self._refresh_buttons()
        self.toast("Invoices read. Review the issues before generating."
                   if open_n else "Invoices read. No issues found.")

    def _category_changes(self) -> int:
        """How many Category changes Zoho's item type has made so far."""
        return self.invoices.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE source = ?",
            (ZOHO_CATEGORY_SOURCE,)).fetchone()[0]

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
        if self._scanned and not self._busy:
            self._show_summary(*self.selected_month())

    # ------------------------------------------------------------------
    # Generating the workbook
    # ------------------------------------------------------------------
    def _start_generate(self) -> None:
        """Check open issues and monthly inputs, then write the workbook."""
        year, month = self.selected_month()
        label = month_label(year, month)
        reports = [cb.text() for cb in self.report_checks if cb.isChecked()]

        open_issues = [i for i in self.invoices.issues(year, month) if i.status == "open"]
        if open_issues:
            left = len({n for i in open_issues for n in i.invoices})
            if QMessageBox.question(
                    self, "Open issues",
                    f"{len(open_issues)} issue{'s are' if len(open_issues) != 1 else ' is'} "
                    f"still open on Scan review. {left} invoice{'s' if left != 1 else ''} "
                    "will be left out of the reports and listed on the "
                    "“Not included” sheet.\n\nGenerate anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        needs_costs = {"Indirect vs direct cost %", "Profit & loss"} & set(reports)
        if needs_costs and not self.inputs.has_inputs(year, month):
            box = QMessageBox(self)
            box.setWindowTitle("Monthly inputs")
            box.setText(f"No indirect costs have been entered for {label}.")
            box.setInformativeText("The profit & loss and cost % reports will show "
                                   "indirect costs as zero.")
            enter = box.addButton("Enter them first", QMessageBox.RejectRole)
            box.addButton("Generate anyway", QMessageBox.AcceptRole)
            box.exec()
            if box.clickedButton() is enter:
                self.inputsRequested.emit()
                return

        self.progress.setValue(0)
        self.status.setText("Building the workbook…")
        self._add_log(f"Building the {label} workbook ({len(reports)} reports)…", Colors.SLATE)
        self.generate_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = generate(self.masters, self.invoices, self.inputs, year, month,
                              self.output_picker.path(), reports,
                              self.payments_picker.path(), self.rto_picker.path())
        except GenerateError as exc:
            QApplication.restoreOverrideCursor()
            self.status.setText("Workbook not created.")
            self._add_log(f"✗  {exc}", Colors.RED)
            QMessageBox.warning(self, "Workbook not created", str(exc))
            self._refresh_buttons()
            return
        QApplication.restoreOverrideCursor()
        self._set_progress(100)
        self._last_workbook = result.path
        self.open_btn.show()
        self.status.setText("Workbook ready")
        self._add_log(f"✓  {result.path.name}: {result.invoices} invoices, sales "
                      f"₹{format_inr(result.sales)}, gross profit ₹{format_inr(result.gross_profit)}",
                      Colors.GREEN)
        if result.left_out:
            self._add_log(f"–  {result.left_out} invoice{'s' if result.left_out != 1 else ''} "
                          "left out (see the “Not included” sheet).", Colors.AMBER)
        self._refresh_buttons()
        self.generated.emit(year, month)
        self.toast(f"{result.path.name} saved.")

    def _open_workbook(self) -> None:
        if self._last_workbook and self._last_workbook.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_workbook)))
        else:
            self.toast("The workbook is no longer in the Save to folder.")
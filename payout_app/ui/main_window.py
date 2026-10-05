"""
main_window.py - The payout app's window
========================================

WHAT THIS MODULE DOES
---------------------
Builds the window - the navy sidebar on the left, the pages on the right -
and connects the pages:

    Scan     the daily run and its result
    Review   names that hold invoices up; fixing one scans again
    Set-up   Google sign-in, the two sheets, the invoice folder

HOW SLOW WORK IS RUN
--------------------
Every page asks the window to run its slow actions: `run(what, function,
on_done)`. The window runs ONE at a time on a background thread
(workers.py), shows "what" in the status line at the bottom while it
works, and shows a failure as a message box. A page asking while
something is already running is told to wait - the Google connection
cannot be shared by two actions at once.

The Session (who is signed in + the Google connection + the PDFs already
read) is made once here and handed to the pages.

On first start, when no sheet is set on this PC yet, the window opens on
Set-up instead of Scan.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QVBoxLayout, QWidget)

from app import __version__
from app.widgets.animated_stack import AnimatedStack
from app.widgets.common import Toast
from app.widgets.sidebar import Sidebar
from payout_app import service, settings
from payout_app.ui import workers
from payout_app.ui.review_page import ReviewPage
from payout_app.ui.scan_page import ScanPage
from payout_app.ui.setup_page import SetupPage

APP_NAME = "Drive N Style Payouts"
PAGE_SCAN, PAGE_REVIEW, PAGE_SETUP = range(3)


class MainWindow(QMainWindow):
    """Sidebar + pages + status line + toast."""

    busyChanged = Signal(bool)

    def __init__(self, session: service.Session | None = None):
        super().__init__()
        self.session = session or service.Session()
        self._busy = False
        self.setWindowTitle(f"{APP_NAME}  –  v{__version__}")
        self.resize(1240, 800)
        self.setMinimumSize(1040, 660)

        central = QWidget()
        central.setObjectName("ContentArea")
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.sidebar = Sidebar(["Scan", "Review", "Set-up"], subtitle="Daily payouts")
        lay.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = AnimatedStack()
        self.scan_page = ScanPage(self)
        self.review_page = ReviewPage(self)
        self.setup_page = SetupPage(self)
        for page in (self.scan_page, self.review_page, self.setup_page):
            self.stack.addWidget(page)
        right.addWidget(self.stack, 1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setContentsMargins(36, 6, 36, 8)
        right.addWidget(self.status)
        lay.addLayout(right, 1)

        self._toast = Toast(central)

        self.sidebar.pageRequested.connect(self.go_to)
        self.scan_page.scanned.connect(self._after_scan)
        self.scan_page.reviewRequested.connect(lambda: self.go_to(PAGE_REVIEW))
        self.review_page.rescanRequested.connect(self.scan_page.scan_again)
        self.setup_page.changed.connect(self.scan_page.refresh_folder)

        if not (settings.get("masters_sheet_id") and settings.get("register_sheet_id")
                and settings.get("invoice_folder")):
            self.go_to(PAGE_SETUP)

    # ------------------------------------------------------------------
    def _after_scan(self, report) -> None:
        self.review_page.show_report(report)
        count = len(report.issues)
        self.sidebar.set_badge(PAGE_REVIEW, str(count) if count else "")

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, what: str, function, on_done, on_progress=None) -> bool:
        """
        Run `function(progress)` in the background (see module notes).
        Returns False - and shows a short message - if something else is
        still running.
        """
        if self._busy:
            self.toast("Please wait - the app is still working.")
            return False
        self._busy = True
        self.status.setText(what)
        self.busyChanged.emit(True)

        def finished() -> None:
            self._busy = False
            self.status.setText("")
            self.busyChanged.emit(False)

        def failed(message: str) -> None:
            finished()
            QMessageBox.warning(self, APP_NAME, message)

        def done(result) -> None:
            finished()
            on_done(result)

        workers.start(self, function, done, failed, on_progress)
        return True

    def go_to(self, index: int) -> None:
        self.sidebar.set_active(index)
        self.stack.slide_to(index)

    def toast(self, text: str) -> None:
        self._toast.show_message(text)

    def closeEvent(self, event) -> None:
        """Do not close in the middle of a write to the register."""
        if self._busy:
            QMessageBox.information(
                self, APP_NAME, "The app is still working. Please close it when "
                                "the current step has finished.")
            event.ignore()
            return
        event.accept()

"""
main_window.py - The application window
=======================================

WHAT THIS MODULE DOES
---------------------
Builds the main window and wires the pages together:

    +-----------+------------------------------------------+
    |  Sidebar  |  AnimatedStack (one page visible)        |
    |  (navy)   |                                          |
    |           |                              [ toast ]   |
    +-----------+------------------------------------------+

Page order (same order as the sidebar buttons):
    0 Generate reports   1 Scan review   2 Masters
    3 Monthly inputs     4 History

Connections between pages:
    * Sidebar click                 -> animated switch to that page
    * Generate: scan finished       -> Scan review loads that month's issues
                                       and the sidebar shows the open count
    * Generate: "Review issues"     -> switch to Scan review
    * Scan review: issue fixed      -> sidebar badge count updates
    * Scan review: "Continue..."    -> switch back to Generate reports
    * Masters: saved or imported    -> Generate page's "Masters in use"
                                       counts refresh, and Scan review
                                       re-checks (a product added to the
                                       master clears its issue at once)
    * Scan review: issue fixed      -> Generate page summary updates
    * Generate: workbook written    -> History lists it
    * Generate: "Enter them first"  -> Monthly inputs opens on that month

The masters database (MastersRepo) is created in main.py and passed in, so
the window itself never opens files. The scanned invoices (InvoicesRepo)
share the same database connection. Closing the window with unsaved edits
on the Masters screen asks before discarding them.

`toast(text)` shows a fading message; every page calls it through
ScrollPage.toast().
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QWidget

from app import __app_name__, __version__
from app.data.inputs_repo import InputsRepo
from app.data.invoices_repo import InvoicesRepo
from app.data.masters_repo import MastersRepo
from app.pages.generate_page import GeneratePage
from app.pages.history_page import HistoryPage
from app.pages.inputs_page import InputsPage
from app.pages.masters_page import MastersPage
from app.pages.review_page import ReviewPage
from app.widgets.animated_stack import AnimatedStack
from app.widgets.common import Toast
from app.widgets.sidebar import Sidebar

PAGE_GENERATE, PAGE_REVIEW, PAGE_MASTERS, PAGE_INPUTS, PAGE_HISTORY = range(5)


class MainWindow(QMainWindow):
    """Top-level window: sidebar + animated pages + toast."""

    def __init__(self, repo: MastersRepo):
        super().__init__()
        self.repo = repo
        self.invoices = InvoicesRepo(repo)
        self.inputs = InputsRepo(repo)
        self.setWindowTitle(f"{__app_name__}  –  v{__version__}")
        self.resize(1320, 840)
        self.setMinimumSize(1120, 700)

        central = QWidget()
        central.setObjectName("ContentArea")
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # --- Sidebar -----------------------------------------------------
        self.sidebar = Sidebar(["Generate reports", "Scan review", "Masters",
                                "Monthly inputs", "History"])
        lay.addWidget(self.sidebar)

        # --- Pages ---------------------------------------------------------
        self.stack = AnimatedStack()
        self.generate_page = GeneratePage(self.invoices, repo, self.inputs)
        self.review_page = ReviewPage(self.invoices, repo)
        self.masters_page = MastersPage(repo)
        self.inputs_page = InputsPage(self.inputs)
        self.history_page = HistoryPage(repo, self.invoices, self.inputs)
        for page in (self.generate_page, self.review_page, self.masters_page,
                     self.inputs_page, self.history_page):
            self.stack.addWidget(page)
        lay.addWidget(self.stack, 1)

        # --- Toast (floats above everything, bottom-right) ----------------
        self._toast = Toast(central)

        # --- Wiring --------------------------------------------------------
        self.sidebar.pageRequested.connect(self.go_to)
        self.generate_page.scanFinished.connect(self.review_page.load)
        self.review_page.openIssuesChanged.connect(
            lambda _: self.generate_page.refresh_summary())
        self.generate_page.reviewRequested.connect(lambda: self.go_to(PAGE_REVIEW))
        self.review_page.openIssuesChanged.connect(
            lambda n: self.sidebar.set_badge(PAGE_REVIEW, str(n) if n else ""))
        self.review_page.backRequested.connect(lambda: self.go_to(PAGE_GENERATE))
        self.generate_page.generated.connect(self.history_page.refresh)
        self.generate_page.inputsRequested.connect(self._go_to_inputs)
        self.masters_page.mastersChanged.connect(self._refresh_master_counts)
        self.masters_page.mastersChanged.connect(self.review_page.refresh)
        self._refresh_master_counts()
        # Start on the month selected on the Generate page (last month), so a
        # month already scanned shows its issues and badge straight away.
        self.review_page.load(*self.generate_page.selected_month())

    def _go_to_inputs(self) -> None:
        """Generate asked for the month's Monthly inputs first."""
        self.inputs_page.show_month(*self.generate_page.selected_month())
        self.go_to(PAGE_INPUTS)

    def _refresh_master_counts(self) -> None:
        """Update the Generate page's 'Masters in use' panel."""
        self.generate_page.set_master_counts(self.repo.counts())

    def closeEvent(self, event) -> None:
        """Ask before closing if the Masters screen has unsaved edits, and
        stop a running scan cleanly."""
        if self.masters_page.has_unsaved_changes() or self.inputs_page.has_unsaved_changes():
            answer = QMessageBox.question(
                self, "Unsaved changes",
                "Some master changes or monthly inputs are not saved. Close without saving?",
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Discard:
                event.ignore()
                return
        worker, thread = self.generate_page._worker, self.generate_page._thread
        if worker is not None and thread is not None:
            worker.cancel()
            thread.quit()
            thread.wait(5000)
        event.accept()

    def go_to(self, index: int) -> None:
        """Show page `index` with the slide animation and sync the sidebar."""
        self.sidebar.set_active(index)
        self.stack.slide_to(index)

    def toast(self, text: str) -> None:
        """Show a short fading confirmation message."""
        self._toast.show_message(text)
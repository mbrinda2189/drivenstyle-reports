"""
scan_page.py - The Scan screen: the daily run and what it did
=============================================================

WHAT THE STAFF DO HERE
----------------------
Press "Scan now". The app reads the masters sheet, reads the invoice PDFs
in the folder chosen on Set-up, works out labour and incentive and posts
the new lines to the payout register (service.scan). The screen then
shows:

    tiles      Posted now / Already posted / In review / Re-issued / Not used
               - they add up to the number of PDF files, so no invoice can
               go missing unnoticed
    messages   anything that needs attention: a problem that stopped the
               run (a mistake in the masters sheet, a register line that
               cannot be verified), calculated cells that had been changed
               by hand and were put back, payments recorded without
               reference or proof, files that are not invoices
    lines      the payout lines just posted, with the working of each

TRIAL RUN
---------
With "Trial run" ticked the same is done and shown, but NOTHING is written
to the register - for trying a folder out.

A scan asked for by the Review screen (after a match was saved or an
invoice cancelled) runs the same way as the last one and does not read
the unchanged PDFs again.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QProgressBar

from app.pages.base import ScrollPage
from app.theme import Colors
from app.utils import format_inr
from app.widgets.common import Card, StatTile, button, label
from payout_app import service, settings
from payout_app.masters_sheet import parse_sheet_date
from payout_app.ui.tables import fill, make_table


class ScanPage(ScrollPage):
    scanned = Signal(object)            # the ScanReport
    reviewRequested = Signal()

    def __init__(self, window):
        super().__init__("Scan", "Read the new invoices and post labour and "
                                 "incentive to the payout register.")
        self.win = window
        self.report: service.ScanReport | None = None

        # --- the run -------------------------------------------------------
        card = Card()
        card.body.addWidget(label("Invoice folder", "SectionTitle"))
        self.folder_label = label("", "Muted", wrap=True)
        card.body.addWidget(self.folder_label)
        row = QHBoxLayout()
        self.scan_button = button("Scan now", "Primary")
        self.scan_button.clicked.connect(lambda: self.scan())
        row.addWidget(self.scan_button)
        self.trial = QCheckBox("Trial run (nothing is written to the register)")
        row.addWidget(self.trial)
        row.addStretch(1)
        card.body.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        card.body.addWidget(self.progress)
        self.progress_label = label("", "Muted")
        self.progress_label.hide()
        card.body.addWidget(self.progress_label)
        self.content.addWidget(card)

        # --- tiles ---------------------------------------------------------
        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        self.tiles = {
            "posted": StatTile("Posted now", "–", Colors.GREEN),
            "already posted": StatTile("Already posted", "–"),
            "in review": StatTile("In review", "–", Colors.AMBER),
            "re-issued": StatTile("Re-issued", "–", Colors.BLUE),
            "not used": StatTile("Not used", "–", Colors.SLATE),
        }
        for tile in self.tiles.values():
            tiles.addWidget(tile)
        self.content.addLayout(tiles)

        # --- messages --------------------------------------------------------
        self.message_card = Card()
        self.message_title = label("", "SectionTitle")
        self.message_card.body.addWidget(self.message_title)
        self.messages = label("", wrap=True)
        self.messages.setTextFormat(self.messages.textFormat().RichText)
        self.message_card.body.addWidget(self.messages)
        self.review_button = button("Open Review", "Secondary")
        self.review_button.clicked.connect(self.reviewRequested.emit)
        row = QHBoxLayout()
        row.addWidget(self.review_button)
        row.addStretch(1)
        self.message_card.body.addLayout(row)
        self.message_card.hide()
        self.content.addWidget(self.message_card)

        # --- lines posted ------------------------------------------------------
        card = Card()
        self.lines_title = label("Lines posted", "SectionTitle")
        card.body.addWidget(self.lines_title)
        self.table = make_table(["Line", "Type", "Payee", "Amount", "Working"], 4,
                                {0: 210, 1: 120, 2: 200, 3: 110})
        self.table.setMinimumHeight(260)
        card.body.addWidget(self.table)
        self.content.addWidget(card)
        self.content.addStretch(1)

        window.busyChanged.connect(lambda busy: self.scan_button.setEnabled(not busy))
        self.refresh_folder()

    # ------------------------------------------------------------------
    def refresh_folder(self) -> None:
        folder = settings.get("invoice_folder")
        start = settings.get("start_date")
        text = folder or "No folder chosen yet - choose it on Set-up."
        if folder and start:
            text += f"\nInvoices dated before {start} are left alone."
        self.folder_label.setText(text)

    def scan_again(self) -> None:
        """Asked by Review: the same kind of run as the last one."""
        self.scan(quiet=True)

    def scan(self, quiet: bool = False) -> None:
        folder = settings.get("invoice_folder")
        if not folder:
            self.win.toast("Choose the invoice folder on Set-up first.")
            return
        start = None
        if settings.get("start_date"):
            try:
                start = parse_sheet_date(settings.get("start_date"))
            except Exception:
                start = None
        dry = self.trial.isChecked()

        def work(progress):
            return service.scan(self.win.session, folder, dry, start, progress)

        if self.win.run("Scanning…", work, self._done, self._progress):
            self.progress.setRange(0, 0)               # busy until the first file
            self.progress.show()
            self.progress_label.setText("Reading the masters sheet…")
            self.progress_label.show()
            self._quiet = quiet

    def _progress(self, done: int, total: int, name: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress_label.setText(
            f"Reading invoice {done} of {total}…" if done < total
            else "Calculating and posting…")

    def _done(self, report: service.ScanReport) -> None:
        self.report = report
        self.progress.hide()
        self.progress_label.hide()
        tally = report.tally
        for key, tile in self.tiles.items():
            tile.set_value(str(tally.get(key, 0)) if tally else "–")
        self._show_messages(report)
        dry = " (trial run - not written)" if report.dry_run else ""
        self.lines_title.setText(
            f"Lines posted{dry}: {len(report.posted)}   ·   "
            f"{format_inr(report.posted_total)}")
        fill(self.table, [[l["line_id"], l["type"], l["payee"] or "–",
                           float(l["amount"]), l["working"]] for l in report.posted])
        self.scanned.emit(report)
        if report.stopped:
            self.win.toast("Nothing was posted - see the message.")
        elif not getattr(self, "_quiet", False):
            self.win.toast(f"{len(report.posted)} line(s) posted{dry}.")

    def _show_messages(self, report: service.ScanReport) -> None:
        def block(title: str, items: list[str], colour: str) -> str:
            if not items:
                return ""
            rows = "".join(f"<li>{escape(i)}</li>" for i in items)
            return (f"<p style='color:{colour}; margin-bottom:2px;'><b>{escape(title)}</b></p>"
                    f"<ul style='margin-top:0;'>{rows}</ul>")

        html = ""
        if report.stopped:
            html += block(report.stopped, report.problems or [""], Colors.RED)
        html += block("Calculated cells had been changed by hand and were put back"
                      + (" (trial run: not written)" if report.dry_run else ""),
                      report.restored, Colors.AMBER)
        html += block("Please check", report.warnings, Colors.AMBER)
        html += block("Notes", report.notes, Colors.SLATE)
        html += block("Files not used",
                      [f"{r.file_name}: {' '.join(r.reasons)}" for r in report.not_used],
                      Colors.SLATE)
        waiting = len(report.review)
        if waiting:
            html += (f"<p style='color:{Colors.AMBER};'><b>{waiting} invoice(s) are in "
                     f"review</b> ({len(report.issues)} thing(s) to decide) and are not "
                     "posted until fixed.</p>")
        tally = report.tally
        if tally and not report.stopped:
            parts = [f"{tally[k]} {k}" for k in
                     ("posted", "already posted", "re-issued", "in review", "cancelled",
                      "not used", "before start date") if tally.get(k)]
            html += (f"<p style='color:{Colors.SLATE};'>{tally['files']} PDF file(s) = "
                     + escape(" + ".join(parts) or "0") + "</p>")
        self.message_title.setText("Stopped" if report.stopped else "Result")
        self.messages.setText(html)
        self.review_button.setVisible(bool(waiting))
        self.message_card.setVisible(bool(html))

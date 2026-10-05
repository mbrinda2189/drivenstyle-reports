"""
history_page.py - The History screen: everything the app has done
=================================================================

WHAT IS SHOWN
-------------
The register's Log tab, newest first: every invoice posted, every match
saved, every payment recorded, reopened or held, every invoice cancelled
or re-issued, and every calculated cell that had been changed by hand and
was put back - with when and who.

    When | Who | What | Record | Old value | New value

The search box filters on any of the columns ("DNS-226", "Kumaran",
"reopened", a person's e-mail, "05-10-2026"). The log is never edited
from the app; it is a record.

The screen reads the register when it is opened after something has
changed, and with "Refresh".
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit

from app.pages.base import ScrollPage
from app.widgets.common import Card, button, label
from payout_app import register, service
from payout_app.ui.tables import fill, make_table


class HistoryPage(ScrollPage):
    def __init__(self, window):
        super().__init__("History", "Every change made through the app, newest first.")
        self.win = window
        self.entries: list[list] = []
        self._stale = True

        card = Card()
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search invoice, payee, person, date or action")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self._show())
        row.addWidget(self.search, 1)
        self.refresh_button = button("Refresh", "Secondary")
        self.refresh_button.clicked.connect(self.reload)
        row.addWidget(self.refresh_button)
        card.body.addLayout(row)
        self.count = label("", "Muted")
        card.body.addWidget(self.count)
        self.table = make_table(list(register.LOG_HEADERS), 5,
                                {0: 130, 1: 170, 2: 180, 3: 190, 4: 130})
        self.table.setMinimumHeight(460)
        card.body.addWidget(self.table)
        self.content.addWidget(card)
        self.content.addStretch(1)
        window.busyChanged.connect(lambda busy: self.refresh_button.setEnabled(not busy))

    def mark_stale(self) -> None:
        self._stale = True
        if self.isVisible():
            self.reload()

    def showEvent(self, event) -> None:                 # noqa: N802 (Qt name)
        super().showEvent(event)
        if self._stale and not self.win.busy:
            self.reload()

    def reload(self) -> None:
        self.win.run("Reading the register…",
                     lambda _p: service.read_register(self.win.session), self.show_view)

    def show_view(self, view: service.RegisterView) -> None:
        self.entries, self._stale = view.log, False
        self._show()

    def _show(self) -> None:
        words = self.search.text().strip().lower()
        rows = [e for e in self.entries
                if not words or words in " ".join(str(c) for c in e).lower()]
        self.count.setText(f"{len(rows)} of {len(self.entries)} entries"
                           if words else f"{len(self.entries)} entries")
        fill(self.table, [[str(c) for c in e[:len(register.LOG_HEADERS)]] for e in rows])

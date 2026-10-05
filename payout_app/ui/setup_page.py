"""
setup_page.py - Set-up: Google sign-in, the two sheets, the invoice folder
==========================================================================

WHAT IS SET HERE (once per PC)
------------------------------
    Google account   "Sign in" opens the browser (Microsoft Edge when it is
                     installed); the person signs in with their own Google
                     account and allows the app. Their name is then written
                     beside every scan and payment. "Sign out" forgets the
                     sign-in on this PC.
    Masters sheet    the link of "Drive N Style Masters"
    Payout register  the link of "Drive N Style Payout Register". The
                     owner's PC can also create a new, empty register here.
    Invoice folder   where the staff save the invoice PDFs
    Start date       optional: invoices dated earlier are left alone (the
                     register starts at go-live, with no back-posting)

"Save and check" stores the links and then really opens both sheets: it
reports the masters sheet's check result (or its mistakes, by tab and row)
and whether the register has its tabs. So a wrong link, or a sheet that
was not shared with this person, shows up here and not in the middle of
the day's work.

Everything is kept in payout_settings.json in the PC's data folder
(payout_app/settings.py) - nothing here is written to Google except
creating a new register when asked.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QMessageBox

from app.pages.base import ScrollPage
from app.theme import Colors
from app.widgets.common import Card, PathPicker, button, label
from payout_app import google_api, masters_sheet, register, settings
from payout_app.google_api import GoogleError
from payout_app.masters_sheet import parse_sheet_date


class SetupPage(ScrollPage):
    changed = Signal()

    def __init__(self, window):
        super().__init__("Set-up", "Done once on each PC: the Google account, the "
                                   "two sheets and the invoice folder.")
        self.win = window

        # --- Google account ---------------------------------------------------
        card = Card()
        card.body.addWidget(label("Google account", "SectionTitle"))
        self.account = label("", wrap=True)
        card.body.addWidget(self.account)
        row = QHBoxLayout()
        self.sign_in_button = button("Sign in", "Primary")
        self.sign_in_button.clicked.connect(self._sign_in)
        row.addWidget(self.sign_in_button)
        self.sign_out_button = button("Sign out", "Secondary")
        self.sign_out_button.clicked.connect(self._sign_out)
        row.addWidget(self.sign_out_button)
        row.addStretch(1)
        card.body.addLayout(row)
        self.content.addWidget(card)

        # --- sheets -------------------------------------------------------------
        card = Card()
        card.body.addWidget(label("Google Sheets", "SectionTitle"))
        card.body.addWidget(label("Masters sheet - link", "Muted"))
        self.masters_link = QLineEdit(settings.get("masters_sheet_url"))
        self.masters_link.setPlaceholderText("https://docs.google.com/spreadsheets/d/…")
        card.body.addWidget(self.masters_link)
        card.body.addWidget(label("Payout register - link", "Muted"))
        self.register_link = QLineEdit(settings.get("register_sheet_url"))
        self.register_link.setPlaceholderText("https://docs.google.com/spreadsheets/d/…")
        card.body.addWidget(self.register_link)
        row = QHBoxLayout()
        self.check_button = button("Save and check", "Primary")
        self.check_button.clicked.connect(self._save_and_check)
        row.addWidget(self.check_button)
        self.create_button = button("Create a new register…", "Secondary")
        self.create_button.clicked.connect(self._create_register)
        row.addWidget(self.create_button)
        row.addStretch(1)
        card.body.addLayout(row)
        self.check_result = label("", wrap=True)
        self.check_result.setTextFormat(self.check_result.textFormat().RichText)
        card.body.addWidget(self.check_result)
        self.content.addWidget(card)

        # --- folder -------------------------------------------------------------
        card = Card()
        card.body.addWidget(label("Invoices", "SectionTitle"))
        card.body.addWidget(label("Folder where the invoice PDFs are saved", "Muted"))
        self.folder = PathPicker("Choose the invoice folder")
        self.folder.edit.setText(settings.get("invoice_folder"))
        self.folder.pathChanged.connect(self._folder_changed)
        card.body.addWidget(self.folder)
        card.body.addWidget(label("Leave invoices dated before (dd-mm-yyyy, optional)",
                                  "Muted"))
        row = QHBoxLayout()
        self.start = QLineEdit(settings.get("start_date"))
        self.start.setPlaceholderText("e.g. 01-11-2026")
        self.start.setMaximumWidth(180)
        self.start.editingFinished.connect(self._start_changed)
        row.addWidget(self.start)
        self.start_note = label("", "Muted")
        row.addWidget(self.start_note, 1)
        card.body.addLayout(row)
        self.content.addWidget(card)
        self.content.addStretch(1)

        window.busyChanged.connect(self._set_busy)
        self._show_account()

    def _set_busy(self, busy: bool) -> None:
        for control in (self.sign_in_button, self.sign_out_button, self.check_button,
                        self.create_button):
            control.setEnabled(not busy)

    # ------------------------------------------------------------------
    def _show_account(self, name: str = "") -> None:
        signed_in = google_api.is_signed_in()
        if signed_in:
            self.account.setText(f"Signed in{' as ' + name if name else ''} on this PC.")
        else:
            self.account.setText("Not signed in on this PC yet.")
        self.sign_in_button.setVisible(not signed_in)
        self.sign_out_button.setVisible(signed_in)

    def _sign_in(self) -> None:
        self.account.setText("The browser has opened - sign in there with your Google "
                             "account and allow the app. This screen waits.")
        self.win.run("Waiting for the Google sign-in in the browser…",
                     lambda _p: self.win.session.user, self._signed_in)

    def _signed_in(self, name: str) -> None:
        self._show_account(name)
        self.win.toast("Signed in.")

    def _sign_out(self) -> None:
        google_api.sign_out()
        self.win.session.forget()
        self._show_account()
        self.win.toast("Signed out on this PC.")

    # ------------------------------------------------------------------
    def _save_and_check(self) -> None:
        masters_id = settings.sheet_id_from(self.masters_link.text())
        register_id = settings.sheet_id_from(self.register_link.text())
        if not masters_id or not register_id:
            self.win.toast("Paste both links first.")
            return

        def work(_progress):
            client = self.win.session.client
            lines: list[tuple[bool, str]] = []
            try:
                title = client.title(masters_id)
                result = masters_sheet.refresh(lambda: client.read_tabs(masters_id))
                if result.ok and not result.from_cache:
                    count = ", ".join(f"{n} {t.lower()}" for t, n in result.counts.items())
                    lines.append((True, f"Masters sheet “{title}” is fine: {count}."))
                else:
                    lines.append((False, f"Masters sheet “{title}” has "
                                         f"{len(result.problems)} problem(s):"))
                    lines += [(False, "   " + p) for p in result.problems[:12]]
            except GoogleError as exc:
                lines.append((False, f"Masters sheet: {exc}"))
            try:
                title = client.title(register_id)
                tabs = client.tab_names(register_id)
                missing = [t for t in (register.PAYOUTS, register.INVOICES,
                                       register.MATCHES, register.LOG) if t not in tabs]
                if missing:
                    lines.append((False, f"“{title}” is not a payout register: it has "
                                         f"no tab {', '.join(missing)}."))
                else:
                    lines.append((True, f"Payout register “{title}” is fine."))
            except GoogleError as exc:
                lines.append((False, f"Payout register: {exc}"))
            return lines

        def done(lines) -> None:
            link = "https://docs.google.com/spreadsheets/d/{}/edit"
            settings.save(masters_sheet_id=masters_id,
                          masters_sheet_url=link.format(masters_id),
                          register_sheet_id=register_id,
                          register_sheet_url=link.format(register_id))
            self.check_result.setText("<br>".join(
                f"<span style='color:{Colors.GREEN if ok else Colors.RED};'>"
                f"{escape(text)}</span>" for ok, text in lines))
            self._show_account(self.win.session.user)
            self.changed.emit()

        self.win.run("Opening the sheets…", work, done)

    def _create_register(self) -> None:
        if settings.get("register_sheet_id"):
            answer = QMessageBox.question(
                self, "Create a new register",
                "This PC already uses a payout register. Create another, EMPTY one "
                "and use that instead?\n\nThe present register is not changed or "
                "deleted.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return

        def work(_progress):
            client = self.win.session.client
            sheet_id, url = client.create(register.SHEET_TITLE,
                                          register.new_register_tabs(),
                                          register.register_layout())
            client.write_formulas(sheet_id, register.SUMMARY, register.summary_formulas())
            return sheet_id, url

        def done(result) -> None:
            sheet_id, url = result
            settings.save(register_sheet_id=sheet_id, register_sheet_url=url)
            self.register_link.setText(url)
            self.check_result.setText(
                f"<span style='color:{Colors.GREEN};'>Created “"
                f"{escape(register.SHEET_TITLE)}”. Share it with the staff as Editor "
                "in Google Sheets.</span>")
            self.changed.emit()

        self.win.run("Creating the register…", work, done)

    # ------------------------------------------------------------------
    def _folder_changed(self, path: str) -> None:
        settings.save(invoice_folder=path)
        self.changed.emit()

    def _start_changed(self) -> None:
        text = self.start.text().strip()
        if text:
            try:
                day = parse_sheet_date(text)
            except Exception:
                day = None
            if day is None:
                self.start_note.setText("Not a date - use dd-mm-yyyy. Not saved.")
                return
            text = day.strftime("%d-%m-%Y")
            self.start.setText(text)
        self.start_note.setText("")
        settings.save(start_date=text)
        self.changed.emit()

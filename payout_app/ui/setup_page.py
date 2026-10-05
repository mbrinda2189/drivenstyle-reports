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
    Proofs folder    the ONE Google Drive folder the payment proofs are
                     uploaded to. The owner creates it here once ("Create
                     the proofs folder", signed in as the owner account) and
                     shares it with the staff as Editor in Google Drive. It
                     is noted in the register, so the other PCs find it by
                     themselves - nothing to set there.
    Housekeeping     for the OWNER, before go-live (v0.17.1):
                     "Clear the register…" empties the trial lines, the
                     invoices read and the log after making a backup copy
                     (the word CLEAR must be typed; only the register's
                     owner can do it); "Find duplicate sheets…" lists extra
                     copies of the sheets made while testing and moves the
                     ticked ones to Google Drive's trash - never one this
                     PC uses.
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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox, QTableWidgetItem,
    QVBoxLayout)

from app.pages.base import ScrollPage
from app.theme import Colors
from app.widgets.common import Card, PathPicker, button, fit_to_screen, label
from payout_app import google_api, masters_sheet, register, service, settings
from payout_app.google_api import GoogleError
from payout_app.masters_sheet import parse_sheet_date
from payout_app.ui.tables import fill, make_table


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

        # --- proofs folder --------------------------------------------------------
        card = Card()
        card.body.addWidget(label("Payment proofs", "SectionTitle"))
        self.proofs = label("One shared Google Drive folder holds every proof. The "
                            "owner creates it once; “Save and check” shows whether "
                            "this register has one.", "Muted", wrap=True)
        self.proofs.setOpenExternalLinks(True)
        card.body.addWidget(self.proofs)
        row = QHBoxLayout()
        self.proofs_button = button("Create the proofs folder", "Secondary")
        self.proofs_button.clicked.connect(self._create_proofs_folder)
        row.addWidget(self.proofs_button)
        row.addStretch(1)
        card.body.addLayout(row)
        self.content.addWidget(card)

        # --- housekeeping (owner) -------------------------------------------------
        card = Card()
        card.body.addWidget(label("Housekeeping (owner only)", "SectionTitle"))
        self.housekeeping = label(
            "Before go-live: clear the trial postings from the register (a backup "
            "copy is made first), and remove extra copies of the sheets made while "
            "testing.", "Muted", wrap=True)
        self.housekeeping.setOpenExternalLinks(True)
        card.body.addWidget(self.housekeeping)
        row = QHBoxLayout()
        self.clear_button = button("Clear the register…", "Danger")
        self.clear_button.clicked.connect(self._clear_register)
        row.addWidget(self.clear_button)
        self.duplicates_button = button("Find duplicate sheets…", "Secondary")
        self.duplicates_button.clicked.connect(self._find_duplicates)
        row.addWidget(self.duplicates_button)
        row.addStretch(1)
        card.body.addLayout(row)
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
                        self.create_button, self.proofs_button, self.clear_button,
                        self.duplicates_button):
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
                    folder = register.setup_value(
                        client.read_tabs(register_id).get(register.SETUP),
                        register.PROOFS_KEY)
                    if folder:
                        name = self.win.session.drive.folder_name(folder)
                        lines.append((True, f"Proofs folder “{name}” can be opened."))
                    else:
                        lines.append((False, "No proofs folder yet - the owner creates "
                                             "it below. Until then payments need a "
                                             "reference."))
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

    def _create_proofs_folder(self) -> None:
        if not settings.get("register_sheet_id"):
            self.win.toast("Set the payout register first.")
            return
        answer = QMessageBox.question(
            self, "Create the proofs folder",
            "The folder is made in the Google Drive of the account signed in on this "
            "PC, which then OWNS every proof. Do this signed in as the owner account "
            "(automation.drivenstyle@gmail.com).\n\nCreate it now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return

        def done(result) -> None:
            name, url = result
            self.proofs.setText(
                f"Proofs folder: <a href='{escape(url)}'>{escape(name)}</a>. Share it "
                "with the staff as Editor in Google Drive.")
            self.changed.emit()

        self.win.run("Creating the proofs folder…",
                     lambda _p: service.create_proofs_folder(self.win.session), done)

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    def _clear_register(self) -> None:
        if not settings.get("register_sheet_id"):
            self.win.toast("Set the payout register first.")
            return
        typed, ok = QInputDialog.getText(
            self, "Clear the register",
            "This empties the register's Payouts, Invoices and Log tabs - every "
            "payout line, every recorded payment and every invoice read.\n"
            "Matches and the proofs folder are kept. A backup copy of the register "
            "is made first.\n\n"
            f"Type {service.CLEAR_WORD} to go ahead:")
        if ok:
            self.clear_register(typed)

    def clear_register(self, typed: str) -> None:
        def done(result) -> None:
            backup, removed = result
            self.housekeeping.setText(
                f"Register cleared: {removed[register.PAYOUTS]} payout line(s), "
                f"{removed[register.INVOICES]} invoice(s) and {removed[register.LOG]} "
                f"log entries removed. <a href='{escape(backup)}'>Open the backup "
                "copy</a>. Set the start date below to the go-live date before the "
                "next scan.")
            self.win.toast("Register cleared.")
            self.changed.emit()

        self.win.run("Making a backup and clearing the register…",
                     lambda _p: service.clear_register(self.win.session, typed), done)

    def _find_duplicates(self) -> None:
        def done(files: list[dict]) -> None:
            extras = [f for f in files if not f["in_use"]]
            if not extras:
                self.housekeeping.setText(
                    f"No duplicates: {len(files)} file(s) with these names, all in use.")
                self.win.toast("No duplicate sheets found.")
                return
            dialog = DuplicatesDialog(files, self)
            if dialog.exec() == QDialog.Accepted and dialog.chosen():
                self.trash(dialog.chosen())

        self.win.run("Looking in Google Drive…",
                     lambda _p: service.find_duplicates(self.win.session), done)

    def trash(self, files: list[dict]) -> None:
        def done(count: int) -> None:
            self.housekeeping.setText(
                f"{count} duplicate(s) moved to Google Drive's trash, where they stay "
                "for 30 days.")
            self.win.toast(f"{count} file(s) moved to the trash.")
            self.changed.emit()

        self.win.run("Moving the files to the trash…",
                     lambda _p: service.trash_duplicates(self.win.session, files), done)

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


class DuplicatesDialog(QDialog):
    """Tick the extra copies that should go to Google Drive's trash."""

    def __init__(self, files: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate sheets")
        self.files = files
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(label(
            "Files in this Google Drive with the names the app uses. The ones marked "
            "“in use” are the sheets this PC works with and cannot be ticked. Ticked "
            "files go to Drive's trash and can be restored from there for 30 days.",
            "Muted", wrap=True))
        self.table = make_table(["Trash", "Name", "Kind", "Created", "Status"], 1,
                                {0: 60, 2: 80, 3: 150, 4: 90})
        fill(self.table, [["", f["name"], f["kind"], f["created"],
                           "in use" if f["in_use"] else "extra"] for f in files])
        for row, f in enumerate(files):
            box = QTableWidgetItem()
            if f["in_use"]:
                box.setFlags(Qt.ItemIsSelectable)             # cannot be ticked
            else:
                box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                box.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, box)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = button("Close", "Secondary")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        move = button("Move ticked files to the trash", "Danger")
        move.clicked.connect(self.accept)
        row.addWidget(move)
        lay.addLayout(row)
        fit_to_screen(self, 820, 480)

    def chosen(self) -> list[dict]:
        return [f for row, f in enumerate(self.files)
                if not f["in_use"] and self.table.item(row, 0).checkState() == Qt.Checked]

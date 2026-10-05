"""
payouts_page.py - The Payouts screen: record what was paid, with proof
======================================================================

WHAT THE STAFF DO HERE
----------------------
The screen lists the payout lines of the register. By default it shows
what is waiting to be paid (Status "Pending"); the filters at the top
show Paid, Hold or Cancelled lines, one type, one payee, or search an
invoice number / customer.

    Tick the lines that were paid together -> "Record payment…"
        paid date, mode (Cash, GPay ...), reference number, proof file,
        remarks. ONE reference and ONE proof can cover many lines - a
        person is often paid for several invoices in one transfer.
        A payment needs a reference or a proof.
    "Hold…"       keep ticked pending lines out of the to-pay list, with a
                  reason (e.g. the customer has not paid yet); "Release"
                  brings them back.
    "Reopen…"     undo a recorded payment, with a reason. The line is
                  Pending again and can be recorded afresh; what it held
                  stays in the Log. This is how a payment is corrected.
    "Open proof"  opens the selected line's proof in the browser.
    "Payout slip…" one sheet per payee: what is to be paid, or what was
                  paid on a day - to show on screen or save as a PDF.

The three tiles show the money waiting, the money on hold and what was
paid today. Below the table the selected line's working is shown, so a
figure can be checked without opening the register.

HOW IT STAYS RIGHT WITH TWO PCs
-------------------------------
The list is a copy read from the register; it is read again when the
screen is opened after a scan, after every action and with "Refresh".
Every action re-reads the lines itself before writing (service.py), so a
line the other PC has just paid can never be paid twice - the action is
refused and names the line.

KEEPING IT FAST
---------------
Plain text cells only; the tick is a checkable cell, not a widget. The
buttons act on the ticked rows.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit,
    QTableWidgetItem, QTextBrowser)

from app.pages.base import ScrollPage
from app.theme import Colors
from app.utils import format_inr
from app.widgets.common import (
    Card, NoWheelComboBox, NoWheelDateEdit, PathPicker, StatTile, button, fit_to_screen,
    label, scroll_body)
from payout_app import register, service, slip
from payout_app.ui.tables import make_table, money_item, text_item

ALL = "All"
COL_TICK, COL_INVOICE, COL_TYPE, COL_PAYEE, COL_AMOUNT, COL_STATUS, COL_PAID, \
    COL_HOW = range(8)


def _day(value: date | None) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


class PayoutsPage(ScrollPage):
    def __init__(self, window):
        super().__init__("Payouts", "Record labour and incentive payments, with their "
                                    "reference and proof.")
        self.win = window
        self.view = service.RegisterView()
        self.shown: list[dict] = []
        self._stale, self._filling = True, False

        # --- tiles ---------------------------------------------------------
        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        self.tile_pending = StatTile("Waiting to be paid", "–", Colors.AMBER)
        self.tile_hold = StatTile("On hold", "–", Colors.SLATE)
        self.tile_today = StatTile("Paid today", "–", Colors.GREEN)
        for tile in (self.tile_pending, self.tile_hold, self.tile_today):
            tiles.addWidget(tile)
        self.content.addLayout(tiles)

        # --- filters + table ---------------------------------------------------
        card = Card()
        row = QHBoxLayout()
        self.status = NoWheelComboBox()
        for name in (register.PENDING, register.PAID, register.HOLD, register.CANCELLED, ALL):
            self.status.addItem(name, name)
        self.kind = NoWheelComboBox()
        self.kind.addItem("All types", ALL)
        for name in ("Labour", "Spot incentive", "Internal team"):
            self.kind.addItem(name, name)
        self.payee = NoWheelComboBox()
        self.payee.setMinimumWidth(190)
        self.payee.addItem("All payees", ALL)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search invoice no or customer")
        self.search.setClearButtonEnabled(True)
        for widget in (self.status, self.kind, self.payee):
            widget.currentIndexChanged.connect(lambda *_: self._apply_filters())
            row.addWidget(widget)
        self.search.textChanged.connect(lambda *_: self._apply_filters())
        row.addWidget(self.search, 1)
        self.refresh_button = button("Refresh", "Secondary")
        self.refresh_button.clicked.connect(self.reload)
        row.addWidget(self.refresh_button)
        card.body.addLayout(row)

        self.table = make_table(
            ["", "Invoice", "Type", "Payee", "Amount", "Status", "Paid on",
             "Mode / reference"], COL_PAYEE,
            # The widths add up to fit Brinda's laptop (about 1330 px wide at
            # 150 % zoom) without a sideways scroll bar; Payee takes the rest.
            # (The invoice date is in the line of detail under the table.)
            {COL_TICK: 34, COL_INVOICE: 150, COL_TYPE: 118, COL_AMOUNT: 96,
             COL_STATUS: 82, COL_PAID: 104, COL_HOW: 160})
        self.table.setMinimumHeight(330)
        self.table.itemChanged.connect(self._tick_changed)
        self.table.currentCellChanged.connect(lambda *_: self._show_detail())
        card.body.addWidget(self.table)

        row = QHBoxLayout()
        self.tick_all = QCheckBox("Tick all shown")
        self.tick_all.clicked.connect(self._tick_all)
        row.addWidget(self.tick_all)
        self.selected = label("", "Muted")
        row.addWidget(self.selected, 1)
        card.body.addLayout(row)
        self.detail = label("", "Muted", wrap=True)
        card.body.addWidget(self.detail)

        row = QHBoxLayout()
        self.pay_button = button("Record payment…", "Primary")
        self.pay_button.clicked.connect(self._record)
        self.hold_button = button("Hold…", "Secondary")
        self.hold_button.clicked.connect(lambda: self._hold(True))
        self.release_button = button("Release", "Secondary")
        self.release_button.clicked.connect(lambda: self._hold(False))
        self.reopen_button = button("Reopen…", "Secondary")
        self.reopen_button.clicked.connect(self._reopen)
        self.proof_button = button("Open proof", "Secondary")
        self.proof_button.clicked.connect(self._open_proof)
        self.slip_button = button("Payout slip…", "Secondary")
        self.slip_button.clicked.connect(self._slip)
        for control in (self.pay_button, self.hold_button, self.release_button,
                        self.reopen_button):
            row.addWidget(control)
        row.addStretch(1)
        row.addWidget(self.proof_button)
        row.addWidget(self.slip_button)
        card.body.addLayout(row)
        self.content.addWidget(card)
        self.content.addStretch(1)

        self._actions = (self.pay_button, self.hold_button, self.release_button,
                         self.reopen_button, self.refresh_button)
        window.busyChanged.connect(
            lambda busy: [c.setEnabled(not busy) for c in self._actions])

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def mark_stale(self) -> None:
        """The register has changed (a scan): read it again when next shown."""
        self._stale = True
        if self.isVisible():
            self.reload()

    def showEvent(self, event) -> None:                 # noqa: N802 (Qt name)
        super().showEvent(event)
        if self._stale and not self.win.busy:
            self.reload()

    def reload(self) -> None:
        self.win.run("Reading the register…",
                     lambda _p: service.read_register(self.win.session), self._loaded)

    def _loaded(self, view: service.RegisterView) -> None:
        self.view, self._stale = view, False
        lines = view.lines
        total = lambda status: sum(l["amount"] for l in lines if l["status"] == status)
        self.tile_pending.set_value(format_inr(total(register.PENDING)))
        self.tile_hold.set_value(format_inr(total(register.HOLD)))
        today = date.today()
        self.tile_today.set_value(format_inr(sum(
            l["amount"] for l in lines
            if l["status"] == register.PAID and l["paid_date"] == today)))
        chosen = self.payee.currentData()
        self.payee.blockSignals(True)
        self.payee.clear()
        self.payee.addItem("All payees", ALL)
        for name in sorted({l["payee"] for l in lines if l["payee"]}, key=str.lower):
            self.payee.addItem(name, name)
        at = self.payee.findData(chosen)
        self.payee.setCurrentIndex(at if at >= 0 else 0)
        self.payee.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self) -> None:
        status, kind, payee = (self.status.currentData(), self.kind.currentData(),
                               self.payee.currentData())
        words = self.search.text().strip().lower()
        self.shown = [
            l for l in self.view.lines
            if status in (ALL, l["status"]) and kind in (ALL, l["type"])
            and payee in (ALL, l["payee"])
            and (not words or words in l["invoice_no"].lower()
                 or words in l["customer"].lower())]
        self._filling = True
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.shown))
        for r, l in enumerate(self.shown):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            tick.setCheckState(Qt.Unchecked)
            self.table.setItem(r, COL_TICK, tick)
            how = " · ".join(p for p in (l["mode"], l["reference"],
                                         "proof" if l["proof"] else "") if p) \
                or l["remarks"]
            for c, text in ((COL_INVOICE, l["invoice_no"]),
                            (COL_TYPE, l["type"]), (COL_PAYEE, l["payee"] or "–"),
                            (COL_STATUS, l["status"]), (COL_PAID, _day(l["paid_date"])),
                            (COL_HOW, how)):
                self.table.setItem(r, c, text_item(text))
            self.table.setItem(r, COL_AMOUNT, money_item(l["amount"]))
        self.table.resizeRowsToContents()
        self._filling = False
        self.tick_all.setChecked(False)
        self._tick_changed()
        self._show_detail()

    # ------------------------------------------------------------------
    # Ticks and the selected line
    # ------------------------------------------------------------------
    def ticked(self) -> list[dict]:
        return [l for r, l in enumerate(self.shown)
                if self.table.item(r, COL_TICK)
                and self.table.item(r, COL_TICK).checkState() == Qt.Checked]

    def tick(self, line_ids: list[str]) -> None:
        """Tick the rows of these lines (used by "Tick all" and the tests)."""
        self._filling = True
        for r, l in enumerate(self.shown):
            self.table.item(r, COL_TICK).setCheckState(
                Qt.Checked if l["line_id"] in line_ids else Qt.Unchecked)
        self._filling = False
        self._tick_changed()

    def _tick_all(self) -> None:
        self.tick([l["line_id"] for l in self.shown] if self.tick_all.isChecked() else [])

    def _tick_changed(self, *_args) -> None:
        if self._filling:
            return
        lines = self.ticked()
        if lines:
            self.selected.setText(f"{len(lines)} line(s) ticked  ·  "
                                  f"{format_inr(sum(l['amount'] for l in lines))}")
        else:
            self.selected.setText(f"{len(self.shown)} line(s) shown  ·  "
                                  f"{format_inr(sum(l['amount'] for l in self.shown))}")

    def _current(self) -> dict | None:
        row = self.table.currentRow()
        return self.shown[row] if 0 <= row < len(self.shown) else None

    def _show_detail(self) -> None:
        line = self._current()
        if line is None:
            self.detail.setText("")
            return
        parts = ["  ·  ".join(p for p in (
            line["line_id"], "invoice of " + _day(line["invoice_date"]),
            line["customer"], line["car"]) if p),
                 f"Working: {line['working']}"]
        if line["remarks"]:
            parts.append(f"Remarks: {line['remarks']}")
        if line["entered_by"]:
            parts.append(f"Entered by {line['entered_by']} on {line['entered_at']}")
        self.detail.setText("\n".join(parts))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _need(self, statuses: tuple[str, ...], doing: str) -> list[dict] | None:
        """The ticked lines, if there are some and all have one of `statuses`."""
        lines = self.ticked()
        if not lines:
            self.win.toast("Tick the lines first.")
            return None
        wrong = [l for l in lines if l["status"] not in statuses]
        if wrong:
            self.win.toast(f"Only {' or '.join(s.lower() for s in statuses)} lines can be "
                           f"{doing}. Untick {wrong[0]['line_id']}"
                           + (f" and {len(wrong) - 1} more." if len(wrong) > 1 else "."))
            return None
        return lines

    def _after(self, message: str):
        def done(_result) -> None:
            self.win.toast(message)
            self.win.register_changed()
            self.reload()
        return done

    def _record(self) -> None:
        lines = self._need((register.PENDING, register.HOLD), "paid")
        if not lines:
            return
        dialog = PaymentDialog(lines, bool(self.view.proofs_folder), self)
        if dialog.exec() == QDialog.Accepted:
            self.record(lines, **dialog.values())

    def record(self, lines: list[dict], paid_date: date, mode: str, reference: str = "",
               proof_path: str = "", remarks: str = "") -> None:
        ids = [l["line_id"] for l in lines]
        self.win.run(
            "Recording the payment…",
            lambda _p: service.record_payment(self.win.session, ids, paid_date, mode,
                                              reference, proof_path, remarks),
            self._after(f"Payment recorded for {len(ids)} line(s)."))

    def _hold(self, hold: bool) -> None:
        lines = self._need((register.PENDING,) if hold else (register.HOLD,),
                           "put on hold" if hold else "released")
        if not lines:
            return
        reason = ""
        if hold:
            reason, ok = QInputDialog.getText(self, "Hold", "Reason for holding the payment:")
            if not ok:
                return
        self.hold(lines, hold, reason)

    def hold(self, lines: list[dict], hold: bool, reason: str = "") -> None:
        ids = [l["line_id"] for l in lines]
        self.win.run("Updating the register…",
                     lambda _p: service.set_hold(self.win.session, ids, hold, reason),
                     self._after(f"{len(ids)} line(s) {'on hold' if hold else 'released'}."))

    def _reopen(self) -> None:
        lines = self._need((register.PAID,), "reopened")
        if not lines:
            return
        reason, ok = QInputDialog.getText(
            self, "Reopen payment",
            f"{len(lines)} paid line(s) will be Pending again; what they held is kept "
            "in the Log.\n\nReason:")
        if ok:
            self.reopen(lines, reason)

    def reopen(self, lines: list[dict], reason: str) -> None:
        ids = [l["line_id"] for l in lines]
        self.win.run("Reopening the payment…",
                     lambda _p: service.reopen_payment(self.win.session, ids, reason),
                     self._after(f"{len(ids)} payment(s) reopened."))

    def _open_proof(self) -> None:
        line = self._current()
        if line is None or not line["proof"]:
            self.win.toast("The selected line has no proof.")
            return
        QDesktopServices.openUrl(QUrl(line["proof"]))

    def _slip(self) -> None:
        SlipDialog(self.view.lines, self).exec()


class PaymentDialog(QDialog):
    """Paid date, mode, reference, proof and remarks for the ticked lines."""

    def __init__(self, lines: list[dict], proofs_ready: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record payment")
        body, buttons = scroll_body(self)
        total = sum(l["amount"] for l in lines)
        payees = sorted({l["payee"] or l["type"] for l in lines})
        body.addWidget(label(f"{len(lines)} line(s)  ·  {format_inr(total)}", "SectionTitle"))
        body.addWidget(label("To: " + ", ".join(payees), "Muted", wrap=True))

        body.addWidget(label("Paid on", "Muted"))
        self.day = NoWheelDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd-MM-yyyy")
        self.day.setMaximumDate(QDate.currentDate())
        body.addWidget(self.day)
        body.addWidget(label("Mode", "Muted"))
        self.mode = NoWheelComboBox()
        self.mode.setEditable(True)
        self.mode.addItems(list(register.MODES))
        body.addWidget(self.mode)
        body.addWidget(label("Reference (UTR / transaction / voucher no)", "Muted"))
        self.reference = QLineEdit()
        body.addWidget(self.reference)
        body.addWidget(label("Proof - a screenshot, photo or PDF (up to 10 MB)", "Muted"))
        self.proof = PathPicker(
            "Choose the proof file", "file",
            "Pictures and PDF (*.jpg *.jpeg *.png *.webp *.heic *.pdf)")
        body.addWidget(self.proof)
        if not proofs_ready:
            self.proof.setEnabled(False)
            body.addWidget(label("The proofs folder is not set up yet (Set-up, on the "
                                 "owner's PC). Until then give a reference.", "Muted",
                                 wrap=True))
        body.addWidget(label("Remarks (optional)", "Muted"))
        self.remarks = QLineEdit()
        body.addWidget(self.remarks)
        self.problem = label("", wrap=True)
        self.problem.setStyleSheet(f"color: {Colors.RED};")
        body.addWidget(self.problem)
        body.addStretch(1)

        buttons.addStretch(1)
        cancel = button("Cancel", "Secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = button("Record payment", "Primary")
        save.clicked.connect(self._accept)
        buttons.addWidget(save)
        fit_to_screen(self, 560, 600)

    def _accept(self) -> None:
        if not self.mode.currentText().strip():
            self.problem.setText("Choose how it was paid.")
        elif not self.reference.text().strip() and not self.proof.path():
            self.problem.setText("A payment needs a reference number or a proof.")
        else:
            self.accept()

    def values(self) -> dict:
        day = self.day.date()
        return dict(paid_date=date(day.year(), day.month(), day.day()),
                    mode=self.mode.currentText().strip(),
                    reference=self.reference.text().strip(),
                    proof_path=self.proof.path(), remarks=self.remarks.text().strip())


class SlipDialog(QDialog):
    """The payout slip on screen, with "Save as PDF"."""

    def __init__(self, lines: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Payout slip")
        self.lines = lines
        body, buttons = scroll_body(self, (20, 16, 20, 8))
        row = QHBoxLayout()
        self.which = NoWheelComboBox()
        self.which.addItem("To pay (everything pending)", "pending")
        self.which.addItem("Paid on", "paid")
        row.addWidget(self.which)
        self.day = NoWheelDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd-MM-yyyy")
        row.addWidget(self.day)
        row.addStretch(1)
        body.addLayout(row)
        self.page = QTextBrowser()
        self.page.setMinimumHeight(380)
        body.addWidget(self.page, 1)
        self.which.currentIndexChanged.connect(lambda *_: self._show())
        self.day.dateChanged.connect(lambda *_: self._show())

        buttons.addStretch(1)
        close = button("Close", "Secondary")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        save = button("Save as PDF…", "Primary")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        fit_to_screen(self, 820, 680)
        self._show()

    def current(self) -> slip.Slip:
        if self.which.currentData() == "pending":
            return slip.build(self.lines)
        day = self.day.date()
        return slip.build(self.lines, date(day.year(), day.month(), day.day()))

    def _show(self) -> None:
        self.day.setEnabled(self.which.currentData() == "paid")
        self.page.setHtml(slip.to_html(self.current()))

    def _save(self) -> None:
        made = self.current()
        name = "Payout slip - " + made.title.replace(" - ", " ").replace("/", "-") + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save the payout slip", name,
                                              "PDF (*.pdf)")
        if path:
            self.save_pdf(path)

    def save_pdf(self, path: str) -> None:
        """Write the slip as an A4 PDF (Qt's own PDF writer - no other program)."""
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
        writer = QPdfWriter(path)
        writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                         QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter))
        document = QTextDocument()
        document.setHtml(slip.to_html(self.current()))
        document.print_(writer)

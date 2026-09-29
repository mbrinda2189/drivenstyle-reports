"""
review_page.py - "Scan review" screen
=====================================

WHAT THIS SCREEN DOES
---------------------
After a month's invoices are scanned, everything the tool could not settle
on its own is listed here, so it can be fixed BEFORE the reports are
generated. Nothing is guessed silently.

    [ Invoices read ]  [ Need attention ]  [ Skipped ]        <- tiles

    Issues | Invoices read                                    <- tabs

ISSUES TAB (one row per issue; open issues first)
-------------------------------------------------
    Item not in the Product master    choose the product (type to search)
                                      -> Save. Remembered for every
                                      invoice printing that item name. An
                                      item on several invoices is listed
                                      once, with its invoice count.
    Salesperson not found             choose the executive -> Save. Listed
                                      ONCE per printed name with all its
                                      invoices ("Mano Vikram", 29 invoices);
                                      the choice applies to all of them and
                                      is remembered for later months.
    Salesperson matches several       one row per invoice (must be decided
    executives / not printed          invoice by invoice); "All invoices"
                                      can still be ticked.
    Vehicle not found / not printed   choose the car, same as above
    Labour line without a labour item Accept (or fix the Product master:
                                      tick Labour involved)
    Totals do not add up              Open file to check, then Accept
    File skipped / could not be read  shown for information; Open file

KEEPING IT FAST (v0.6.1)
------------------------
The Fix controls (a searchable list of every product / executive / car,
Save, Accept ...) are built only for the row that is clicked; every other
row is plain text. Before v0.6.1 each of ~95 rows carried its own copy of
the full list, which made scrolling and every refresh slow. The table
scrolls on its own (about 10 rows visible).
When a master is saved elsewhere the page is only marked "out of date"
(mark_stale) and rebuilt the next time it is shown, instead of being
rebuilt in the background after every save.

Each fix is saved straight away, logged in the audit log (Masters > Audit
log, "Scan review"), and kept when the month is scanned again. A fix can
resolve other rows too (e.g. one remembered salesperson name): those rows
turn "Fixed" at the same time. Adding a missing product or car on the
Masters screen also clears its issues here immediately.

EXPORT ISSUES (v0.6.2)
----------------------
"Export issues" saves the OPEN issues to Excel (sheet "Issues" with "What
we need" and a blank "Client's reply" column, and sheet "Invoices
affected") - see app/reports/issues_export.py. It can be sent to the client
as a question list.

INVOICES READ TAB
-----------------
Every invoice read for the month with what the tool understood: date,
customer, salesperson and car as matched to the masters (amber when not
matched yet, showing what was printed), number of items, GST or no GST,
total, and payment mode if printed. This is for checking the reader.

SIGNALS
-------
    openIssuesChanged(int)  number of open issues (sidebar badge)
    backRequested()         "Continue to generate" / "Go to Generate reports"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QFileDialog, QHBoxLayout,
    QMessageBox,
    QHeaderView, QLabel, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from app.data.invoices_repo import InvoicesRepo, Issue, month_label
from app.data.masters_repo import MastersRepo
from app.pages.base import ScrollPage
from app.reports.issues_export import default_file_name, export_issues
from app.theme import Colors
from app.utils import format_inr
from app.widgets.common import Card, StatTile, button, label

# Status pill styles: (text, text colour, background colour)
PILLS = {
    "open": ("Open", Colors.AMBER, Colors.AMBER_TINT),
    "fixed": ("Fixed", Colors.GREEN, Colors.GREEN_TINT),
    "skipped": ("Skipped", Colors.SLATE, "#EEF2F7"),
}
KIND_ORDER = {"product": 0, "salesperson": 1, "car": 2, "labour": 3,
              "totals": 4, "file": 5}
ROW_HEIGHT = 50
VISIBLE_ROWS = 10          # issues table height; more rows scroll inside it


def status_item(kind: str) -> QTableWidgetItem:
    """
    Status as plain coloured text (Open / Fixed / Skipped). v0.6.1: a text
    item instead of a small widget per row, so long lists scroll smoothly.
    """
    text, fg, bg = PILLS[kind]
    item = QTableWidgetItem(text)
    item.setForeground(QBrush(QColor(fg)))
    item.setBackground(QBrush(QColor(bg)))
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    item.setTextAlignment(Qt.AlignCenter)
    return item


def cell(*widgets: QWidget) -> QWidget:
    """Put controls side by side inside a table cell."""
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(6, 3, 6, 3)
    lay.setSpacing(6)
    for w in widgets:
        lay.addWidget(w)
    lay.addStretch(1)
    return holder


def search_combo(placeholder: str, items: list[tuple[str, int]],
                 first_ids: list[int] | None = None) -> QComboBox:
    """
    A drop-down that can also be typed into to find an entry quickly
    (e.g. one of 300 products). `first_ids` are listed at the top
    (suggestions). Each entry carries its database id.
    """
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.lineEdit().setPlaceholderText(placeholder)
    first_ids = first_ids or []
    ordered = sorted(items, key=lambda t: (t[1] not in first_ids, t[0].lower()))
    for text, item_id in ordered:
        combo.addItem(text, item_id)
    combo.setCurrentIndex(-1)
    completer = QCompleter([t for t, _ in ordered], combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    combo.setCompleter(completer)
    combo.setFixedWidth(270)          # same width in every row, so Save lines up
    if len(first_ids) == 1:
        combo.setCurrentIndex(0)
    return combo


def chosen_id(combo: QComboBox) -> int | None:
    """Id of the typed / chosen entry, or None if the text matches nothing."""
    i = combo.findText(combo.currentText(), Qt.MatchFixedString)
    return combo.itemData(i) if i >= 0 else None


class ReviewPage(ScrollPage):
    """Lists the month's scan issues and lets the user fix each one."""

    openIssuesChanged = Signal(int)
    backRequested = Signal()

    COL_INVOICE, COL_ISSUE, COL_FIX, COL_STATUS = range(4)

    def __init__(self, invoices: InvoicesRepo, masters: MastersRepo,
                 parent: QWidget | None = None):
        super().__init__(
            "Scan review",
            "Fix anything the tool could not read or match before generating the reports.",
            parent,
        )
        self.invoices = invoices
        self.masters = masters
        self.year = self.month = None
        self._rows: list[tuple[Issue, str]] = []     # (issue, status) per table row
        self._stale = False        # masters changed while this page was hidden
        self._fix_row = -1         # the row currently showing Fix controls

        self.states = QStackedWidget()
        self.states.addWidget(self._build_empty_state())
        self.states.addWidget(self._build_results())
        self.content.addWidget(self.states, 1)

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------
    def _build_empty_state(self) -> QWidget:
        card = Card(padding=40)
        card.body.setAlignment(Qt.AlignCenter)
        title = label("No scan yet", "SectionTitle")
        title.setAlignment(Qt.AlignCenter)
        text = label("Choose the month and Zoho's invoice export on the Generate "
                     "reports page and read the invoices. Anything that needs "
                     "attention will be listed here.", "Muted", wrap=True)
        text.setAlignment(Qt.AlignCenter)
        text.setMaximumWidth(460)
        go = button("Go to Generate reports", "Primary")
        go.clicked.connect(self.backRequested.emit)
        card.body.addWidget(title, 0, Qt.AlignCenter)
        card.body.addWidget(text, 0, Qt.AlignCenter)
        card.body.addSpacing(8)
        card.body.addWidget(go, 0, Qt.AlignCenter)
        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(card)
        lay.addStretch(1)
        return wrapper

    def _build_results(self) -> QWidget:
        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)

        tiles = QHBoxLayout()
        tiles.setSpacing(20)
        self.tile_read = StatTile("Invoices read", "0", Colors.INK)
        self.tile_open = StatTile("Need attention", "0", Colors.AMBER)
        self.tile_skip = StatTile("Files skipped", "0", Colors.SLATE)
        for t in (self.tile_read, self.tile_open, self.tile_skip):
            tiles.addWidget(t, 1)
        lay.addLayout(tiles)

        card = Card()
        self.month_title = label("", "SectionTitle")
        card.body.addWidget(self.month_title)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_issues_tab(), "Issues")
        self.tabs.addTab(self._build_invoices_tab(), "Invoices read")
        card.body.addWidget(self.tabs)

        foot = QHBoxLayout()
        self.footer_note = label("", "Muted")
        foot.addWidget(self.footer_note, 1)
        self.export_btn = button("Export issues", "Secondary")
        self.export_btn.setToolTip("Save the open issues as an Excel file, e.g. to "
                                   "send to the client as a question list.")
        self.export_btn.clicked.connect(self._export_issues)
        foot.addWidget(self.export_btn)
        cont = button("Continue to generate", "Primary")
        cont.clicked.connect(self.backRequested.emit)
        foot.addWidget(cont)
        card.body.addLayout(foot)
        lay.addWidget(card)
        lay.addStretch(1)
        return wrapper

    def _build_issues_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 0)
        self.issues_table = QTableWidget(0, 4)
        self.issues_table.setHorizontalHeaderLabels(["Invoice", "Issue", "Fix", "Status"])
        t = self.issues_table
        t.verticalHeader().hide()
        t.setAlternatingRowColors(True)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setWordWrap(True)
        t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Fix controls only on the clicked row (see KEEPING IT FAST).
        t.currentCellChanged.connect(self._on_row_changed)
        hdr = t.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setSectionResizeMode(self.COL_INVOICE, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_ISSUE, QHeaderView.Stretch)
        hdr.setSectionResizeMode(self.COL_FIX, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_STATUS, QHeaderView.Fixed)
        t.setColumnWidth(self.COL_INVOICE, 170)
        t.setColumnWidth(self.COL_FIX, 470)
        t.setColumnWidth(self.COL_STATUS, 96)
        t.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        t.setFixedHeight(t.horizontalHeader().sizeHint().height()
                         + ROW_HEIGHT * VISIBLE_ROWS + 4)
        lay.addWidget(t)
        return page

    def _build_invoices_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 0)
        heads = ["Invoice", "Date", "Customer", "Salesperson", "Car", "Items",
                 "Total (₹)", "GST", "Payment mode"]
        self.inv_table = QTableWidget(0, len(heads))
        t = self.inv_table
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().hide()
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.verticalHeader().setDefaultSectionSize(36)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        hdr = t.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i, w in enumerate((165, 100, 175, 170, 145, 55, 110, 75, 120)):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
            t.setColumnWidth(i, w)
        hdr.setStretchLastSection(True)
        t.setMinimumHeight(360)
        lay.addWidget(t)
        return page

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self, year: int, month: int) -> None:
        """Show the issues of a month (called after a scan)."""
        self.year, self.month = year, month
        self.refresh()

    def mark_stale(self) -> None:
        """
        A master was saved: rebuild when this page is next shown, not now
        (rebuilding on every save made the Masters screen lag). Only the
        open-issue count is worked out now, for the sidebar badge and the
        Generate page summary - that takes a tenth of a second.
        """
        if self.isVisible():
            self.refresh()
            return
        self._stale = True
        if self.year is not None and self.invoices.scan_run(self.year, self.month):
            self.openIssuesChanged.emit(sum(
                1 for i in self.invoices.issues(self.year, self.month)
                if i.status == "open"))

    def showEvent(self, event) -> None:
        """Bring the page up to date if masters changed while it was hidden."""
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self) -> None:
        """Rebuild both tabs from the database (e.g. after masters change)."""
        self._stale = False
        if self.year is None or self.invoices.scan_run(self.year, self.month) is None:
            self.states.setCurrentIndex(0)
            self.openIssuesChanged.emit(0)
            return
        self.states.setCurrentIndex(1)
        self.month_title.setText(month_label(self.year, self.month))
        issues = sorted(self.invoices.issues(self.year, self.month),
                        key=lambda i: (i.status != "open", KIND_ORDER[i.kind]))
        self._rows = [(i, i.status) for i in issues]
        self._fill_issues()
        self._fill_invoices()
        self._update_counts()

    def _fill_issues(self) -> None:
        t = self.issues_table
        self._fix_row = -1
        t.blockSignals(True)               # no Fix controls while filling
        t.clearSelection()
        t.setRowCount(0)
        for row, (issue, status) in enumerate(self._rows):
            t.insertRow(row)
            inv = issue.invoices[0] if issue.invoices else issue.file_name
            if len(issue.invoices) > 1:
                inv += f"  (+{len(issue.invoices) - 1} more)"
            item = QTableWidgetItem(inv)
            item.setToolTip("\n".join(issue.invoices) or issue.file_name)
            t.setItem(row, self.COL_INVOICE, item)
            msg = QTableWidgetItem(issue.message)
            msg.setToolTip(issue.message)
            t.setItem(row, self.COL_ISSUE, msg)
            t.setItem(row, self.COL_FIX, self._fix_hint(issue, status))
            t.setItem(row, self.COL_STATUS, status_item(status))
        t.blockSignals(False)

    @staticmethod
    def _fix_hint(issue: Issue, status: str) -> QTableWidgetItem:
        """Plain text shown in the Fix column of rows that are not clicked."""
        if status == "fixed":
            text = "Fixed"
        elif issue.kind == "file":
            text = "Click to open the file"
        elif issue.kind in ("labour", "totals"):
            text = "Click to check or accept"
        else:
            what = {"product": "product", "salesperson": "executive",
                    "car": "car"}[issue.kind]
            text = f"Click to choose the {what}"
            if issue.grouped:
                text += f" (all {len(issue.invoices)} invoices)" \
                    if len(issue.invoices) > 1 else ""
        item = QTableWidgetItem(text)
        item.setForeground(QBrush(QColor(Colors.SLATE)))
        return item

    def _on_row_changed(self, row: int, _col: int, prev: int, _prev_col: int) -> None:
        """Move the Fix controls to the clicked row."""
        t = self.issues_table
        if prev >= 0 and prev == self._fix_row:
            t.removeCellWidget(prev, self.COL_FIX)
            self._fix_row = -1
        if 0 <= row < len(self._rows) and row != self._fix_row:
            issue, status = self._rows[row]
            if status != "fixed":
                t.setCellWidget(row, self.COL_FIX, self._fix_control(row, issue))
                self._fix_row = row

    def _fill_invoices(self) -> None:
        rows = self.invoices.invoices(self.year, self.month)
        t = self.inv_table
        t.setRowCount(len(rows))
        amber = QBrush(QColor(Colors.AMBER))
        for r, inv in enumerate(rows):
            items = [l for l in inv["lines"] if not l["is_labour_marker"]]
            gst = ("No GST" if inv["tax_rate"] == 0 else
                   "Mixed" if inv["tax_rate"] < 0 else f"{inv['tax_rate']:g}%")
            values = [
                inv["invoice_no"],
                date.fromisoformat(inv["invoice_date"]).strftime("%d-%m-%Y"),
                inv["customer"],
                inv["executive"] or f"— {inv['salesperson'] or 'not printed'}",
                inv["car"] or f"— {inv['vehicle'] or 'not printed'}",
                str(len(items)), format_inr(inv["total"]), gst,
                inv["payment_mode"] or "Not printed"]
            for c, v in enumerate(values):
                it = QTableWidgetItem(v)
                if c in (5, 6):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if (c == 3 and not inv["executive"]) or (c == 4 and not inv["car"]):
                    it.setForeground(amber)
                    it.setToolTip("Not matched to the master yet - see Issues.")
                if c == 0:
                    it.setToolTip("\n".join(
                        f"{l['line_no']}. {l['description']}  ₹{format_inr(l['amount'])}"
                        + (f"  → {l['product']}" if l["product"] else
                           "  (labour marker)" if l["is_labour_marker"] else "  (not matched)")
                        for l in inv["lines"]))
                t.setItem(r, c, it)

    # ------------------------------------------------------------------
    # Fix controls
    # ------------------------------------------------------------------
    def _fix_control(self, row: int, issue: Issue) -> QWidget:
        """Build the control shown in the Fix column for one issue."""
        if issue.kind == "product":
            combo = search_combo(
                "Type to find the product…",
                [(p["name"] + ("" if p["active"] else "  (inactive)"), p["id"])
                 for p in self.masters.list_rows("products")])
            save = button("Save", "Ghost")
            save.clicked.connect(lambda: self._save_product(row, combo))
            return cell(combo, save)

        if issue.kind in ("salesperson", "car"):
            if issue.kind == "salesperson":
                items = [(f"{e['name']} ({e['phone']})"
                          + (f" – {e['branch']}" if e["branch"] else ""), e["id"])
                         for e in self.masters.list_rows("executives")]
                placeholder = "Type to find the executive…"
            else:
                items = [(MastersRepo.display_name("cars", c), c["id"])
                         for c in self.masters.list_rows("cars")]
                placeholder = "Type to find the car…"
            combo = search_combo(placeholder, items, issue.options)
            every = QCheckBox("All invoices")
            if issue.grouped:
                # One row for every invoice showing this name: the choice
                # always applies to all of them (agreed for v0.6.1).
                every.setChecked(True)
                every.setVisible(False)
                combo.setToolTip(f"Applies to all {len(issue.invoices)} invoice(s) showing "
                                 f"“{issue.printed}”, now and in later months.")
            elif issue.printed:
                every.setToolTip(f"Use this for every invoice showing “{issue.printed}”, "
                                 "now and in later months.")
                # An ambiguous name must be decided invoice by invoice.
                every.setChecked(len(issue.options) <= 1)
            else:
                every.setVisible(False)
            save = button("Save", "Ghost")
            save.clicked.connect(lambda: self._save_target(row, combo, every))
            return cell(combo, every, save)

        if issue.kind in ("labour", "totals"):
            open_btn = button("Open file", "Ghost")
            open_btn.clicked.connect(lambda: self._open_file(issue.file_name))
            accept = button("Accept", "Ghost")
            accept.setToolTip("Accept this invoice as it is.")
            accept.clicked.connect(lambda: self._accept(row))
            return cell(open_btn, accept)

        # Skipped files: information only.
        open_btn = button("Open file", "Ghost")
        open_btn.clicked.connect(lambda: self._open_file(issue.file_name))
        return cell(open_btn)

    def _save_product(self, row: int, combo: QComboBox) -> None:
        pid = chosen_id(combo)
        if pid is None:
            self.toast("Choose a product from the list.")
            return
        issue = self._rows[row][0]
        self.invoices.map_product(issue.printed, pid)
        self._after_fix(f"“{issue.printed}” will be read as {combo.currentText()}.")

    def _save_target(self, row: int, combo: QComboBox, every: QCheckBox) -> None:
        target = chosen_id(combo)
        issue = self._rows[row][0]
        if target is None:
            self.toast(f"Choose a {'sales executive' if issue.kind == 'salesperson' else 'car'} "
                       "from the list.")
            return
        all_invoices = issue.grouped or (every.isVisible() and every.isChecked())
        if issue.kind == "salesperson":
            self.invoices.set_salesperson(issue.key, issue.printed, target, all_invoices)
        else:
            self.invoices.set_car(issue.key, issue.printed, target, all_invoices)
        scope = f"all invoices showing “{issue.printed}”" if all_invoices \
            else f"invoice {issue.key}"
        self._after_fix(f"{combo.currentText()} set for {scope}.")

    def _accept(self, row: int) -> None:
        issue = self._rows[row][0]
        self.invoices.acknowledge(issue.key, issue.kind)
        self._after_fix(f"Invoice {issue.key} accepted.")

    def _after_fix(self, message: str) -> None:
        """Mark every row the fix resolved as Fixed and update the counts."""
        still_open = {(i.kind, i.key) for i in self.invoices.issues(self.year, self.month)
                      if i.status == "open"}
        for row, (issue, status) in enumerate(self._rows):
            if status == "open" and (issue.kind, issue.key) not in still_open:
                self._rows[row] = (issue, "fixed")
                self.issues_table.setItem(row, self.COL_STATUS, status_item("fixed"))
                if row == self._fix_row:
                    self.issues_table.removeCellWidget(row, self.COL_FIX)
                    self._fix_row = -1
                self.issues_table.setItem(row, self.COL_FIX,
                                          self._fix_hint(issue, "fixed"))
        self._fill_invoices()
        self._update_counts()
        self.toast(message)

    def _open_file(self, file_name: str) -> None:
        run = self.invoices.scan_run(self.year, self.month)
        path = None
        if run:
            # v0.6.0: "folder" is the export file itself (every invoice is in
            # it); for months read from PDFs it is the folder of PDFs.
            source = Path(run["folder"])
            path = source if source.is_file() else source / file_name
        if path is None or not path.exists():
            self.toast("The file is no longer where it was read from.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _export_issues(self) -> None:
        """Save the open issues to Excel (app/reports/issues_export.py)."""
        start = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export issues",
            str(Path(start) / default_file_name(self.year, self.month)),
            "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            n = export_issues(self.invoices, self.year, self.month, path)
        except PermissionError:
            QMessageBox.warning(self, "Export issues",
                                f"“{Path(path).name}” could not be saved. If it is open "
                                "in Excel, close it and export again.")
            return
        except OSError as exc:
            QMessageBox.warning(self, "Export issues", f"The file could not be saved: {exc}")
            return
        if QMessageBox.question(
                self, "Export issues",
                f"{n} open issue{'s' if n != 1 else ''} saved to “{Path(path).name}”.\n\n"
                "Open it now?", QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes) == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _update_counts(self) -> None:
        files = self.invoices.scan_files(self.year, self.month)
        read = sum(f["status"] == "read" for f in files)
        open_n = sum(1 for _, s in self._rows if s == "open")
        self.tile_read.set_value(str(read))
        self.tile_open.set_value(str(open_n))
        self.tile_skip.set_value(str(len(files) - read))
        self.export_btn.setEnabled(open_n > 0)
        self.footer_note.setText(
            "All issues resolved." if open_n == 0 else
            f"{open_n} issue{'s' if open_n != 1 else ''} still open. Invoices "
            "with open issues are left out of the affected reports.")
        self.openIssuesChanged.emit(open_n)
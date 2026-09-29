"""
edit_dialog.py - Edit one master row in a form
==============================================

WHAT THIS DIALOG DOES
---------------------
Opened by the "Edit" button on any Masters tab (Products, Sales
executives, Cars, Incentives) for the selected row. It shows every field of
that master as a labelled input, built from the master's definition in
app/data/master_defs.py:

    text     a text box                  (Name, Contact no, Branch, SKU...)
    money    a text box, right-aligned   (accepts 2400, 2,400.00, ₹ 2,400)
    bool     a tick box                  (Active, Labour involved)
    choice   a drop-down                 (Category; car Segment also
                                          accepts a typed value)
    lookup   a drop-down of the other    (a product's Incentive group,
             master's names, or "None"    from the Incentive master)
    date     shown, not editable         (Effective from)

"Apply" checks the form first: required fields filled in, amounts valid and
not negative. Problems are listed at the bottom of the form, and the dialog
stays open until they are fixed.

Applied values go back into the table row, exactly as if they had been
typed into the cells: the row turns blue, a changed rate asks for its
effective date, and nothing reaches the database until "Save changes"
(which also writes the audit log). Duplicate checks happen on save, where
all rows can be compared.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QVBoxLayout, QWidget,
)

from app.data.master_defs import FieldDef, MasterDef
from app.theme import Colors
from app.utils import format_inr, parse_inr
from app.widgets.common import (
    NoWheelComboBox, button, fit_to_screen, label, scroll_body)

NONE_TEXT = "— None —"


class EditDialog(QDialog):
    """Form for one row. After exec() == Accepted, read `values()`."""

    def __init__(self, mdef: MasterDef, values: dict, title: str,
                 lookup_names, parent: QWidget | None = None):
        """
        mdef          the master's definition
        values        current values of the row (field key -> value)
        title         shown at the top, e.g. "Arun (98765 43210)"
        lookup_names  function(master_key) -> list of names, used to fill
                      lookup drop-downs (e.g. incentive groups)
        """
        super().__init__(parent)
        self.mdef = mdef
        self.setWindowTitle(f"Edit {mdef.singular}")
        self.setModal(True)
        self.setMinimumWidth(480)

        # Scrolling body + fixed buttons, never taller than the screen (v0.6.4).
        lay, btns = scroll_body(self)
        lay.setSpacing(14)
        lay.addWidget(label(title or f"New {mdef.singular}", "SectionTitle"))

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.inputs: dict[str, QWidget] = {}
        for f in mdef.fields:
            widget = self._make_input(f, values.get(f.key), lookup_names)
            self.inputs[f.key] = widget
            form.addRow(label(f.label + ("  *" if f.required else "")), widget)
        lay.addLayout(form)

        if mdef.has_rates:
            lay.addWidget(label("Changing an amount asks from which date the "
                                "new amount applies.", "Muted", wrap=True))

        self.error = label("", wrap=True)
        self.error.setStyleSheet(
            f"background: {Colors.RED_TINT}; color: {Colors.RED};"
            "border-radius: 6px; padding: 8px 10px;")
        self.error.hide()
        lay.addWidget(self.error)

        lay.addStretch(1)
        btns.addStretch(1)
        cancel = button("Cancel", "Secondary")
        cancel.clicked.connect(self.reject)
        ok = button("Apply", "Primary")
        ok.clicked.connect(self._apply)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        # Tall enough for every field (+ the button row), capped at the screen.
        fit_to_screen(self, 560, lay.parentWidget().sizeHint().height() + 80)

    # ------------------------------------------------------------------
    def _make_input(self, f: FieldDef, value, lookup_names) -> QWidget:
        """The input widget for one field, showing its current value."""
        if f.kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            return box
        if f.kind in ("choice", "lookup"):
            combo = NoWheelComboBox()
            if f.kind == "lookup":
                names = list(lookup_names(f.lookup))
                if value and value not in names:      # e.g. an inactive group
                    names.append(value)
                combo.addItems([NONE_TEXT, *names])
                combo.setCurrentText(value or NONE_TEXT)
            else:
                combo.addItems(list(f.choices))
                if f.open_choice:
                    combo.setEditable(True)
                    combo.setInsertPolicy(QComboBox.NoInsert)
                combo.setCurrentText(str(value or ""))
            return combo
        edit = QLineEdit()
        if f.kind == "money":
            edit.setText(format_inr(float(value or 0)))
            edit.setAlignment(Qt.AlignRight)
        elif f.kind == "date":
            edit.setText(value.strftime("%d-%m-%Y") if value else "")
            edit.setReadOnly(True)
            edit.setToolTip("Set when an amount is changed.")
        else:
            edit.setText(str(value or ""))
        return edit

    def values(self) -> dict:
        """The form's values (money as numbers; invalid money as None)."""
        out = {}
        for f in self.mdef.fields:
            w = self.inputs[f.key]
            if f.kind == "bool":
                out[f.key] = w.isChecked()
            elif f.kind == "lookup":
                out[f.key] = "" if w.currentIndex() == 0 else w.currentText()
            elif f.kind == "choice":
                out[f.key] = " ".join(w.currentText().split())
            elif f.kind == "money":
                out[f.key] = parse_inr(w.text())
            elif f.kind == "date":
                continue
            else:
                out[f.key] = " ".join(w.text().split())
        return out

    def _apply(self) -> None:
        """Check the form; close only if everything is valid."""
        v = self.values()
        problems = []
        for f in self.mdef.fields:
            if f.required and not str(v.get(f.key) or "").strip():
                problems.append(f"{f.label} is required.")
            if f.kind == "money" and (v.get(f.key) is None or v[f.key] < 0):
                problems.append(f"{f.label}: enter an amount of zero or more, "
                                "e.g. 2400 or 2,400.00.")
        if problems:
            self.error.setText("\n".join(problems))
            self.error.show()
            return
        self.accept()
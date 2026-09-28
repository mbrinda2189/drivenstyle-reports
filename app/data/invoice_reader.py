"""
invoice_reader.py - Read one Carkrafts (Zoho) invoice PDF
========================================================

WHAT THIS MODULE DOES
---------------------
`read_invoice(path)` opens one invoice PDF and returns a `ParsedInvoice`
with everything printed on it. It only READS; matching the lines to the
masters and saving happen in invoices_repo.py.

The invoices are Zoho "text" PDFs (not scans), so the words and their exact
positions on the page can be read directly - no OCR. The reader works from
POSITIONS, not just the text order, because the page has two columns side by
side (e.g. "Invoice Date" on the left and "Sales person" on the right share a
line) and item descriptions can wrap onto a second line.

THE LAYOUT IT EXPECTS (Carkrafts format)
----------------------------------------
    Carkrafts - CBE                                      TAX INVOICE
    ... address ... GSTIN 33AAOFD7793F1Z2
    #            : DNS-226-2627      Place Of Supply            : Tamil Nadu (33)
    Invoice Date : 04/09/2026        Sales person               : Nandha Kumar
    Terms        : Due on Receipt    Customer Type              : Walk-In
    Due Date     : 04/09/2026        Vehicle                    : PUNCH.EV
    P.O.#        : E-226             VIN / Registration Number  : TN99 AK2054
    Bill To
    RITHICK TN99 AK2054
    # | Item & Description | HSN/SAC | Qty | Rate | Amount
    1 | Sunfilm - Nano Ceramic - Front (SK) | 39206929 | 1.00 | 7,000.00 | 7,000.00
    ...
                                  Sub Total (Tax Inclusive)   21,903.00
                                  Discount (Applied on ...)  (-) 1,903.00
                                  CGST9 (9%)                    ...     (GST invoices)
                                  Rounding                      ...     (sometimes)
                                  Total                     ₹20,000.00
                                  Payment Made             (-) 20,000.00
                                  Balance Due                   ₹0.00

HOW EACH PART IS FOUND
----------------------
Header     every "Label : value" line above "Bill To". The page is split
           into a left and a right half at the "Place Of Supply" label, so
           two pairs on one line are kept apart. Known labels are mapped to
           fields (see HEADER_FIELDS); unknown labels are kept in `extra`.
           A "Payment Mode" label is read if Zoho ever prints one.
Customer   the line(s) under "Bill To".
Items      the item table. Column edges are taken from the table's own
           heading row (#, Item & Description, HSN/SAC, Qty, Rate, Amount),
           so small layout shifts do not matter. A new item starts where the
           "#" column has a number; any further words in the description
           column belong to the same item (wrapped descriptions), and a word
           under the quantity (e.g. "no") is the unit. Items may continue on
           following pages.
Totals     the block right of the page centre below the items. Amounts are
           paired with the nearest label on (about) the same line; bracketed
           notes like "(Applied on 7,034.72)" belong to the label above.

AMOUNTS
-------
"7,000.00", "₹8,300.00" and "(-) 1,903.00" are all read as positive numbers;
the label says whether they are added or taken off.

ERRORS
------
`InvoiceReadError` is raised with a plain reason if the file is not a PDF,
has no text (a scan), or has no item table / invoice number. The scan then
lists the file as "could not be read".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pdfplumber

# Header labels (compared in lower case, spaces squeezed) -> field name.
HEADER_FIELDS = {
    "#": "invoice_no",
    "invoice no": "invoice_no",
    "invoice#": "invoice_no",
    "invoice date": "invoice_date",
    "terms": "terms",
    "due date": "due_date",
    "p.o.#": "po_no",
    "place of supply": "place_of_supply",
    "sales person": "salesperson",
    "salesperson": "salesperson",
    "customer type": "customer_type",
    "vehicle": "vehicle",
    "car": "vehicle",
    "vin / registration number": "vin",
    "vin#": "vin",
    "payment mode": "payment_mode",
    "mode of payment": "payment_mode",
}

AMOUNT_RE = re.compile(r"^₹?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?$|^₹?\d+(?:\.\d+)?$")
GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
TAX_LABEL_RE = re.compile(r"^(CGST|SGST|IGST|UTGST)\s*\d*(?:\.\d+)?\s*\((\d+(?:\.\d+)?)%\)",
                          re.IGNORECASE)
FOOTER_WORDS = ("Chennai | Coimbatore | Erode", "This is a computer generated")


class InvoiceReadError(Exception):
    """The file cannot be read as a Carkrafts invoice."""


@dataclass
class InvoiceLine:
    """One row of the item table, as printed."""
    line_no: int
    description: str
    hsn_sac: str = ""
    qty: float = 0.0
    unit: str = ""
    rate: float = 0.0
    amount: float = 0.0
    sku: str = ""                 # only if an "SKU : ..." line is printed


@dataclass
class ParsedInvoice:
    """Everything read from one invoice PDF."""
    file_name: str
    seller: str = ""               # first line, e.g. "Carkrafts - CBE"
    gstin: str = ""
    invoice_no: str = ""
    invoice_date: date | None = None
    terms: str = ""
    due_date: date | None = None
    po_no: str = ""
    place_of_supply: str = ""
    salesperson: str = ""          # as printed, e.g. "Kumaran - HO"
    customer_type: str = ""        # e.g. "Referral", "Walk-In"
    vehicle: str = ""              # as printed, e.g. "PUNCH.EV"
    vin: str = ""
    payment_mode: str = ""         # only if printed
    customer: str = ""
    lines: list[InvoiceLine] = field(default_factory=list)
    sub_total: float = 0.0         # tax inclusive, before discount
    discount: float = 0.0
    discount_base: float = 0.0     # "(Applied on ...)"
    taxes: dict[str, float] = field(default_factory=dict)   # "CGST 9%" -> amount
    tax_rate: float = 0.0          # total GST % (e.g. 18.0); 0 = no GST shown
    rounding: float = 0.0          # signed
    total: float = 0.0
    payment_made: float = 0.0
    balance_due: float = 0.0
    extra: dict[str, str] = field(default_factory=dict)     # unknown labels
    pages: int = 0

    @property
    def tax_total(self) -> float:
        return round(sum(self.taxes.values()), 2)

    @property
    def is_gst(self) -> bool:
        return bool(self.taxes)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def parse_amount(text: str) -> float | None:
    """'₹8,300.00' / '(-) 1,903.00' / '0.20' -> float; None if not a number."""
    cleaned = str(text).replace("₹", "").replace(",", "").replace("(-)", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date(text: str) -> date | None:
    """'04/09/2026' (dd/mm/yyyy) -> date; None if not a date."""
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _is_amount(text: str) -> bool:
    return bool(AMOUNT_RE.match(text.replace("(-)", "").strip()))


def _lines(words: list[dict], tolerance: float = 3.0) -> list[list[dict]]:
    """Group words into lines by their top position, left to right."""
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= tolerance:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def _text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


def _find(words: list[dict], *sequence: str) -> dict | None:
    """First word starting the given word sequence (case-insensitive)."""
    for row in _lines(words):
        texts = [w["text"].lower() for w in row]
        for i in range(len(texts) - len(sequence) + 1):
            if texts[i:i + len(sequence)] == [s.lower() for s in sequence]:
                return row[i]
    return None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def read_invoice(path: str | Path) -> ParsedInvoice:
    """Read one invoice PDF. Raises InvoiceReadError if it cannot be used."""
    path = Path(path)
    try:
        pdf = pdfplumber.open(path)
    except Exception as exc:
        raise InvoiceReadError(f"not a readable PDF ({exc.__class__.__name__})") from exc
    with pdf:
        pages = [p.extract_words(keep_blank_chars=False) for p in pdf.pages]
        heights = [p.height for p in pdf.pages]
        widths = [p.width for p in pdf.pages]
    inv = ParsedInvoice(file_name=path.name, pages=len(pages))
    if not pages or not any(pages):
        raise InvoiceReadError("the PDF has no text (it may be a scanned image)")

    first = pages[0]
    _read_top(inv, first, widths[0])
    for i, words in enumerate(pages):
        words = [w for w in words if w["top"] < heights[i] - 45]   # drop footer
        _read_items(inv, words, widths[i])
    _read_totals(inv, pages, widths, heights)

    if not inv.invoice_no:
        raise InvoiceReadError("no invoice number found - not a Carkrafts invoice?")
    if not inv.lines:
        raise InvoiceReadError("no item table found")
    return inv


def _read_top(inv: ParsedInvoice, words: list[dict], width: float) -> None:
    """Seller, GSTIN, header label/value pairs and the Bill To customer."""
    bill_to = _find(words, "Bill", "To")
    table = _find(words, "Item", "&", "Description")
    header_bottom = bill_to["top"] if bill_to else (table["top"] if table else 260)

    top_words = [w for w in words if w["top"] < header_bottom - 1]
    rows = _lines(top_words)
    if rows:
        inv.seller = _text([w for w in rows[0] if w["x0"] < width * 0.6])
    m = GSTIN_RE.search(" ".join(_text(r) for r in rows))
    inv.gstin = m.group(1) if m else ""

    # Split label/value lines into the left and right halves.
    place = _find(top_words, "Place", "Of", "Supply")
    split_x = place["x0"] - 2 if place else width * 0.5
    for row in rows:
        for half in ([w for w in row if w["x0"] < split_x],
                     [w for w in row if w["x0"] >= split_x]):
            text = _text(half)
            if ":" not in text:
                continue
            label, _, value = text.partition(":")
            label = " ".join(label.split()).lower()
            value = " ".join(value.split()).lstrip(": ").strip()
            key = HEADER_FIELDS.get(label)
            if key is None:
                if label and value:
                    inv.extra[label] = value
                continue
            if key in ("invoice_date", "due_date"):
                setattr(inv, key, parse_date(value))
            elif not getattr(inv, key):
                setattr(inv, key, value)

    # Customer: text between "Bill To" and the item table (left side).
    if bill_to:
        bottom = table["top"] if table else bill_to["top"] + 40
        cust = [w for w in words
                if bill_to["top"] + 5 < w["top"] < bottom - 3 and w["x0"] < width * 0.6]
        inv.customer = " ".join(_text(r) for r in _lines(cust))


def _read_items(inv: ParsedInvoice, words: list[dict], width: float) -> None:
    """Read the item table on one page (if the page has one)."""
    head = _find(words, "Item", "&", "Description")
    if head is None:
        return
    head_row = [w for w in words if abs(w["top"] - head["top"]) <= 3]

    def col(name: str) -> dict | None:
        return next((w for w in head_row if w["text"].lower() == name.lower()), None)

    hsn, qty, rate, amount = col("HSN/SAC"), col("Qty"), col("Rate"), col("Amount")
    if not (qty and rate and amount):
        return
    desc_start = head["x0"] - 4
    b_hsn = (hsn["x0"] - 6) if hsn else (qty["x0"] - 40)
    b_qty = ((hsn["x1"] if hsn else b_hsn) + qty["x0"]) / 2
    b_rate = (qty["x1"] + rate["x0"]) / 2
    b_amount = (rate["x1"] + amount["x0"]) / 2

    # The table ends at the totals / "Total In Words" / "Items in Total".
    enders = [w for w in (_find(words, "Sub", "Total"), _find(words, "Total", "In", "Words"),
                          _find(words, "Items", "in", "Total")) if w]
    end_y = min((w["top"] for w in enders if w["top"] > head["top"]), default=10_000)
    body = [w for w in words if head["top"] + 4 < w["top"] < end_y - 2]

    current: InvoiceLine | None = None
    desc_parts: list[str] = []

    def close() -> None:
        if current is not None:
            text = " ".join(desc_parts)
            sku = re.search(r"\bSKU\s*:\s*(\S+)", text)
            if sku:
                current.sku = sku.group(1)
                text = text[:sku.start()].strip()
            current.description = " ".join(text.split())
            inv.lines.append(current)

    for row in _lines(body):
        first = row[0]
        starts_item = first["x1"] < desc_start and first["text"].isdigit()
        if starts_item:
            close()
            current = InvoiceLine(line_no=int(first["text"]), description="")
            desc_parts = []
            row = row[1:]
        if current is None:
            continue
        for w in row:
            cx = (w["x0"] + w["x1"]) / 2
            t = w["text"]
            if cx < b_hsn:
                desc_parts.append(t)
            elif cx < b_qty:
                current.hsn_sac = (current.hsn_sac + " " + t).strip()
            elif cx < b_rate:
                value = parse_amount(t)
                if value is not None and not current.qty:
                    current.qty = value
                else:
                    current.unit = (current.unit + " " + t).strip()
            elif cx < b_amount:
                value = parse_amount(t)
                if value is not None:
                    current.rate = value
            else:
                value = parse_amount(t)
                if value is not None:
                    current.amount = value
    close()


def _read_totals(inv: ParsedInvoice, pages: list[list[dict]],
                 widths: list[float], heights: list[float]) -> None:
    """Read the totals block (on the last page that has one)."""
    for i in range(len(pages) - 1, -1, -1):
        words = pages[i]
        sub = _find(words, "Sub", "Total")
        if sub is None:
            continue
        stop = _find(words, "Authorized", "Signature")
        bottom = stop["top"] if stop and stop["top"] > sub["top"] else heights[i] - 45
        block = [w for w in words if w["x0"] > widths[i] * 0.55
                 and sub["top"] - 12 < w["top"] < bottom]
        # Amounts are right-aligned at the far right; labels sit left of them.
        amount_edge = max(w["x1"] for w in block) - 60
        labels = [w for w in block if w["x1"] < amount_edge]
        amounts = [w for w in block if w["x1"] >= amount_edge]
        label_rows = [(r[0]["top"], _text(r)) for r in _lines(labels)]
        for row in _lines(amounts):
            raw = _text(row)
            value = parse_amount(raw)
            if value is None:
                continue
            top = row[0]["top"]
            # nearest label that is not a bracketed note
            candidates = [(abs(t - top), text) for t, text in label_rows
                          if not text.startswith("(") and abs(t - top) < 12]
            if not candidates:
                continue
            label = min(candidates)[1]
            # "(-)" is expected on Discount / Payment Made (always taken
            # off); on Rounding it means the rounding is negative.
            if "(-)" in raw and label.lower().startswith("rounding"):
                value = -value
            _assign_total(inv, label, value)
        for _, text in label_rows:
            m = re.search(r"Applied on\s*([\d,]+\.\d+)", text)
            if m:
                inv.discount_base = parse_amount(m.group(1)) or 0.0
        break
    inv.tax_rate = _gst_rate(inv.taxes)


def _gst_rate(taxes: dict[str, float]) -> float:
    """
    Total GST % from the tax lines: CGST 9% + SGST 9% -> 18.0, IGST 18% ->
    18.0, none -> 0.0. If more than one rate is present (e.g. CGST 6% and
    CGST 9%) there is no single rate: -1.0 is returned and amounts are then
    split in proportion (see invoices_repo.allocate_lines).
    """
    igst = {float(k.split()[1][:-1]) for k in taxes if k.startswith("IGST")}
    intra = {float(k.split()[1][:-1]) for k in taxes
             if k.startswith(("CGST", "SGST", "UTGST"))}
    if not taxes:
        return 0.0
    if igst and not intra and len(igst) == 1:
        return igst.pop()
    if intra and not igst and len(intra) == 1:
        return intra.pop() * 2
    return -1.0


def _assign_total(inv: ParsedInvoice, label: str, value: float) -> None:
    """Put one totals-block amount into the right field."""
    low = label.lower()
    tax = TAX_LABEL_RE.match(label)
    if tax:
        key = f"{tax.group(1).upper()} {float(tax.group(2)):g}%"
        inv.taxes[key] = round(inv.taxes.get(key, 0.0) + value, 2)
    elif low.startswith("sub total"):
        inv.sub_total = value
    elif low.startswith("discount"):
        inv.discount = value
    elif low.startswith("rounding"):
        inv.rounding = value
    elif low.startswith("total"):
        inv.total = value
    elif low.startswith("payment made"):
        inv.payment_made = value
    elif low.startswith("balance due"):
        inv.balance_due = value
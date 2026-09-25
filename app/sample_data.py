"""
sample_data.py - Placeholder data for screens not yet connected
===============================================================

WHAT THIS MODULE DOES
---------------------
Holds the sample rows shown by the parts of the tool that are still being
built. Nothing here is used for calculations.

    REPORTS           - the 12 reports offered on the Generate screen
                        (this list is permanent, not sample data)
    PACKAGES          - rows for Masters > Packages (package definitions are
                        not in the client's master sheets yet)
    INDIRECT_COSTS    - default indirect cost heads for Monthly inputs
    SCAN_ISSUES       - issues shown on the Scan review screen (until the
                        invoice reader arrives in v0.3)
    HISTORY           - months shown on the History screen

Since v0.2.0 the Product, Sales executive and Car masters come from the
database (app/data), not from here. To try the Masters screen with sample
sheets, run:  python scripts/make_sample_masters.py

IMPORTANT
---------
Item names and SKUs are taken from a real Drive N Style invoice (DNS26-0777)
so the screens look realistic, but ALL package and cost figures are
invented placeholders.
"""

# The 12 reports, in the order the client listed them.
REPORTS = [
    "Invoice-wise profitability",
    "Service vs product profitability",
    "Labour calculation",
    "Trend analysis (month on month)",
    "Basic package analysis",
    "Vehicle-wise average per car",
    "Spot incentive calculation",
    "Executive-wise sales",
    "High-profit product sales",
    "Indirect vs direct cost %",
    "Payment mode analysis",
    "Profit & loss",
]

# (Package name, Items included, Package price in Rs.)
PACKAGES = [
    ("Basic Package", "Sunfilm Front, Sunfilm Side & Rear, Noodles Mat", 14000.00),
    ("Premium Package", "Basic Package + Seat Cover Premium + 7D Mat", 24500.00),
]

# (Head of expense, Amount in Rs.)
INDIRECT_COSTS = [
    ("Rent", 45000.00),
    ("Salaries", 120000.00),
    ("Electricity", 8500.00),
    ("Internet & phone", 2200.00),
    ("Marketing", 10000.00),
]

# (Invoice no, Issue, Fix type, Fix options)
#   Fix type decides which control appears in the "Fix" column:
#     "confirm" -> a Confirm button
#     "choose"  -> a drop-down with the given options
#     "add"     -> an "Add to master" button
#     "skip"    -> a greyed "Skipped" label
#     "open"    -> an "Open file" button
SCAN_ISSUES = [
    ("DNS26-0777", "“Noodles Mat Role - PVC” has no SKU – matched by name", "confirm", []),
    ("DNS26-0781", "Car model missing", "choose", ["Select car model…", "Nexon", "Creta", "Seltos", "Brezza", "XUV700"]),
    ("DNS26-0790", "Salesperson missing", "choose", ["Select salesperson…", "Arun", "Karthik", "Priya", "Selvam"]),
    ("DNS26-0795", "Item “Sunfilm XYZ” not in cost sheet", "add", []),
    ("DNS26-0802", "Payment mode not found in payments export", "choose", ["Select mode…", "UPI", "Cash", "Card", "Cheque", "Bank transfer"]),
    ("DNSE26-1242", "DNS Enterprises invoice – not included", "skip", []),
    ("scan_03.pdf", "Not a Zoho text PDF – could not be read", "open", []),
]

# (Month, Invoices, Sales in Rs., Generated on)
HISTORY = [
    ("August 2026", 126, 1845200.00, "05-09-2026 11:42"),
    ("July 2026", 131, 1912750.00, "04-08-2026 16:05"),
    ("June 2026", 109, 1528900.00, "06-07-2026 10:18"),
    ("May 2026", 117, 1664300.00, "05-06-2026 12:47"),
]

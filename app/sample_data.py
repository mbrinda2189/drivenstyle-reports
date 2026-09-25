"""
sample_data.py - Placeholder data for the UI preview (v0.1.x)
=============================================================

WHAT THIS MODULE DOES
---------------------
Holds the sample rows that the screens display while the real pieces are
still being built. Nothing here is used for calculations.

    COST_SHEET        - rows for Masters > Cost Sheet
    LABOUR_CHARGES    - rows for Masters > Labour Charges (labour is per item,
                        linked to the item's SKU, as confirmed by the client)
    PACKAGES          - rows for Masters > Packages
    EXECUTIVES        - rows for Masters > Executives & Incentive
    INDIRECT_COSTS    - default indirect cost heads for Monthly Inputs
    SCAN_ISSUES       - issues shown on the Scan Review screen
    HISTORY           - months shown on the History screen
    REPORTS           - the 12 reports offered on the Generate screen

IMPORTANT
---------
Item names and SKUs are taken from a real Drive N Style invoice (DNS26-0777)
so the screens look realistic, but ALL cost, labour, package and incentive
figures are invented placeholders. They will be replaced by the client's
cost sheet and labour charges sheet once received, and this module will then
be removed in favour of the SQLite masters database.
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

# (SKU, Item name, Category, Cost in Rs., Effective from)
COST_SHEET = [
    ("SNC-FSK", "Sunfilm - Nano Ceramic - Front (SK)", "Service", 2400.00, "01-07-2026"),
    ("SNC-SRSK", "Sunfilm - Nano Ceramic - Side and Rear (SK)", "Service", 3100.00, "01-07-2026"),
    ("", "Noodles Mat Role - PVC", "Product", 850.00, "01-04-2026"),
    ("SC-STD", "Seat Cover - Standard", "Product", 1850.00, "01-07-2026"),
    ("SC-PRM", "Seat Cover - Premium Leatherette", "Product", 4200.00, "01-07-2026"),
    ("PPF-FB", "PPF - Full Body", "Service", 38000.00, "01-04-2026"),
    ("CC-9H", "Ceramic Coating - 9H", "Service", 6500.00, "01-04-2026"),
    ("DC-4K", "Dash Camera - 4K", "Product", 5200.00, "01-06-2026"),
    ("AMB-LT", "Ambient Lighting Kit", "Product", 1450.00, "01-06-2026"),
    ("MAT-7D", "7D Floor Mat", "Product", 2100.00, "01-04-2026"),
]

# (SKU, Item name, Labour charge in Rs., Effective from)
LABOUR_CHARGES = [
    ("SNC-FSK", "Sunfilm - Nano Ceramic - Front (SK)", 300.00, "01-07-2026"),
    ("SNC-SRSK", "Sunfilm - Nano Ceramic - Side and Rear (SK)", 500.00, "01-07-2026"),
    ("", "Noodles Mat Role - PVC", 100.00, "01-04-2026"),
    ("SC-STD", "Seat Cover - Standard", 350.00, "01-07-2026"),
    ("SC-PRM", "Seat Cover - Premium Leatherette", 450.00, "01-07-2026"),
    ("PPF-FB", "PPF - Full Body", 6000.00, "01-04-2026"),
    ("CC-9H", "Ceramic Coating - 9H", 1500.00, "01-04-2026"),
    ("DC-4K", "Dash Camera - 4K", 400.00, "01-06-2026"),
]

# (Package name, Items included, Package price in Rs.)
PACKAGES = [
    ("Basic Package", "Sunfilm Front, Sunfilm Side & Rear, Noodles Mat", 14000.00),
    ("Premium Package", "Basic Package + Seat Cover Premium + 7D Mat", 24500.00),
]

# (Executive, Incentive type, Rate, Effective from)
EXECUTIVES = [
    ("Arun", "% of sale value", 1.0, "01-04-2026"),
    ("Karthik", "% of sale value", 1.0, "01-04-2026"),
    ("Priya", "Flat per package", 250.0, "01-04-2026"),
    ("Selvam", "Flat per package", 250.0, "01-04-2026"),
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

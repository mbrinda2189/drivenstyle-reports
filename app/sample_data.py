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

The masters (v0.2.0), scanned invoices and Scan review issues (v0.4.0),
monthly inputs and report history (v0.5.0) come from the database
(app/data), not from here. To try the Masters screen with sample
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
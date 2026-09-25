"""
make_sample_masters.py - Create sample master sheets for trying the import
==========================================================================

WHAT THIS SCRIPT DOES
---------------------
Writes three Excel files that look like typical client master sheets, so
the Masters > Import Excel feature can be tried before the client's real
sheets arrive:

    sample_product_master.xlsx     title row, then headings such as
                                   "Item Name", "HSN Code", "Rate",
                                   "Cost", "Labour (Y/N)", "Labour Charges"
    sample_executive_master.xlsx   "Executive Name", "Mobile No", "City"
    sample_car_master.xlsx         "Brand", "Car Model", "Body Type"

The headings are deliberately NOT the tool's own labels, to show that the
import recognises common variations and lets the user confirm the matches.

Item names and SKUs come from a real Drive N Style invoice (DNS26-0777);
all prices, costs and labour charges are INVENTED placeholders.

Run from the project folder:
    python scripts/make_sample_masters.py            (writes to data/samples)
    python scripts/make_sample_masters.py <folder>   (writes to <folder>)

The data/ folder is excluded from Git, so these files are never committed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

PRODUCTS = [
    # SKU, Item name, HSN/SAC, Type, Rate, Cost, Labour (Y/N), Labour charges
    ("SNC-FSK", "Sunfilm - Nano Ceramic - Front (SK)", "998729", "Service", 4500, 2400, "Y", 300),
    ("SNC-SRSK", "Sunfilm - Nano Ceramic - Side and Rear (SK)", "998729", "Service", 6500, 3100, "Y", 500),
    ("", "Noodles Mat Role - PVC", "5705", "Goods", 1800, 850, "Y", 100),
    ("SC-STD", "Seat Cover - Standard", "8708", "Goods", 3500, 1850, "Y", 350),
    ("SC-PRM", "Seat Cover - Premium Leatherette", "8708", "Goods", 7500, 4200, "Y", 450),
    ("PPF-FB", "PPF - Full Body", "998729", "Service", 65000, 38000, "Y", 6000),
    ("CC-9H", "Ceramic Coating - 9H", "998729", "Service", 14000, 6500, "Y", 1500),
    ("DC-4K", "Dash Camera - 4K", "8525", "Goods", 8900, 5200, "Y", 400),
    ("AMB-LT", "Ambient Lighting Kit", "8512", "Goods", 2800, 1450, "N", 0),
    ("MAT-7D", "7D Floor Mat", "5705", "Goods", 3900, 2100, "N", 0),
]

EXECUTIVES = [
    ("Arun", 9876543210, "Tuticorin"),
    ("Karthik", 9876501234, "Tuticorin"),
    ("Priya", 9840012345, "Tirunelveli"),
    ("Selvam", 9790054321, "Tuticorin"),
]

CARS = [
    ("Tata", "Nexon", "Compact SUV"),
    ("Hyundai", "Creta", "SUV"),
    ("Kia", "Seltos", "SUV"),
    ("Maruti Suzuki", "Brezza", "Compact SUV"),
    ("Mahindra", "XUV700", "SUV"),
    ("Maruti Suzuki", "Swift", "Hatchback"),
    ("Honda", "City", "Sedan"),
    ("Toyota", "Innova Crysta", "MUV"),
]


def write(path: Path, title: str | None, headings: list[str], rows) -> None:
    """Write one sheet: optional title row, a blank row, headings, data."""
    wb = Workbook()
    ws = wb.active
    if title:
        ws.append([title])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([])
    ws.append(headings)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    print("Written", path)


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/samples")
    folder.mkdir(parents=True, exist_ok=True)
    write(folder / "sample_product_master.xlsx",
          "Drive N Style - Product Master",
          ["SKU", "Item Name", "HSN Code", "Type", "Rate", "Cost",
           "Labour (Y/N)", "Labour Charges"], PRODUCTS)
    write(folder / "sample_executive_master.xlsx", None,
          ["Executive Name", "Mobile No", "City"], EXECUTIVES)
    write(folder / "sample_car_master.xlsx", "Car Master",
          ["Brand", "Car Model", "Body Type"], CARS)


if __name__ == "__main__":
    main()

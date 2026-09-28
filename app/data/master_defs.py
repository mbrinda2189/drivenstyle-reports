"""
master_defs.py - The shape of each master
=========================================

WHAT THIS MODULE DOES
---------------------
Describes, in one place, the fields of the four masters the client
provides:

    Product          SKU | Product name | HSN/SAC | Category | Incentive group |
                     Selling price | Cost price | Labour involved |
                     Labour charge | Effective from | Active
    Sales executive  Name | Contact no | Branch | Active
    Car              Make | Model | Segment | Active
    Incentive        Product / Service | Incentive amount | Bill value |
                     Effective from | Active

The same definitions drive four things, so they can never drift apart:

    * the Masters screen      - which columns to show, how to edit them, and
                                which column the filter drop-down uses
    * the Edit form           - one input per field
    * the Excel import        - which fields to match to the sheet's columns,
                                and the column headings recognised
                                automatically (`synonyms`)
    * the Excel export        - the column headings written out

FIELD KINDS
-----------
    "text"   free text (SKU, names, HSN/SAC, contact no, branch)
    "money"  a rupee amount, shown with Indian grouping (12,34,567.00)
    "bool"   yes / no, shown as a tick box
    "choice" one value from a fixed list (`choices`). If `open_choice` is
             True the user may also type a new value (car segment).
    "lookup" one row of ANOTHER master, chosen by name (`lookup` = that
             master's key). Used for a product's Incentive group, which must
             be one of the rows of the Incentive master. May be left blank.
    "date"   the effective-from date of the current rates; set by the tool,
             never typed or imported

DATED FIELDS (RATE HISTORY)
---------------------------
Fields with `dated=True` keep a history: each change is stored with the
date it applies from, so re-running an earlier month uses the values that
applied then. Dated fields:
    Product    selling price, cost price, labour charge
    Incentive  incentive amount, bill value

WHAT MAKES A ROW UNIQUE (no duplicates)
---------------------------------------
    Product          product name, and SKU when given
    Sales executive  contact no (two people may share a name)
    Car              make + model
    Incentive        product / service name
Names and numbers are compared in a standard form (see masters_repo.py), so
"Seat Cover" / "seat  cover" and "+91 98765 43210" / "9876543210" count as
the same.

THE INCENTIVE MASTER AND SPOT INCENTIVE
---------------------------------------
The client's incentive sheet lists incentive groups ("PPF", "Dashcam",
"Basic Package") with an incentive amount and a bill value. Each product
is linked to its group through the Product master's Incentive group. The
spot incentive calculation (incentive reduced when a discount is given) is
NOT built yet - its rules are awaited from the client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def header_key(text: str) -> str:
    """
    Reduce a column heading to lower-case letters and digits only, so
    "Selling Price (Rs.)", "selling_price" and "SELLING PRICE" can be
    compared. Used when matching the client's headings to our fields.
    """
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


@dataclass(frozen=True)
class FieldDef:
    """One field (column) of a master."""

    key: str                        # internal name (also the database column)
    label: str                      # heading shown on screen and in exports
    kind: str = "text"              # text/money/bool/choice/lookup/date
    required: bool = False          # must be filled in (import and save)
    choices: tuple[str, ...] = ()   # allowed values for kind "choice"
    open_choice: bool = False       # "choice" that also accepts new values
    lookup: str = ""                # kind "lookup": key of the other master
    dated: bool = False             # value with effective-from history
    importable: bool = True         # can be matched to a column on import
    default: object = ""            # value used when the sheet lacks the field
    width: int = 0                  # screen column width in px (0 = stretch)
    synonyms: tuple[str, ...] = ()  # headings recognised automatically

    def matches_header(self, heading: str) -> bool:
        """True if `heading` is this field's label or one of its synonyms."""
        wanted = header_key(heading)
        return bool(wanted) and wanted in {
            header_key(s) for s in (self.label, self.key, *self.synonyms)}


@dataclass(frozen=True)
class MasterDef:
    """A whole master: its fields plus a few descriptive names."""

    key: str                        # "products" / "executives" / ...
    title: str                      # tab title, e.g. "Products"
    singular: str                   # e.g. "product" (used in messages)
    fields: tuple[FieldDef, ...] = field(default_factory=tuple)
    filter_field: str = ""          # field offered in the filter drop-down

    def get_field(self, key: str) -> FieldDef:
        """Return the field with internal name `key`."""
        for f in self.fields:
            if f.key == key:
                return f
        raise KeyError(key)

    @property
    def importable_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.importable]

    @property
    def dated_fields(self) -> list[FieldDef]:
        return [f for f in self.fields if f.dated]

    @property
    def has_rates(self) -> bool:
        return bool(self.dated_fields)


# ---------------------------------------------------------------------------
# Product master
# ---------------------------------------------------------------------------
PRODUCT_CATEGORIES = ("Product", "Service")

PRODUCTS = MasterDef(
    key="products", title="Products", singular="product",
    filter_field="category",
    fields=(
        FieldDef("sku", "SKU", width=100,
                 synonyms=("item code", "product code", "code", "item sku",
                           "sku code")),
        FieldDef("name", "Product name", required=True,
                 synonyms=("item name", "product", "item", "name",
                           "description", "particulars", "item description")),
        FieldDef("hsn_sac", "HSN/SAC", width=90,
                 synonyms=("hsn", "sac", "hsn code", "sac code", "hsn sac code",
                           "hsn/sac code")),
        # Category decides "service vs product" in the reports. If the sheet
        # has no category column, it is worked out from the HSN/SAC code
        # (see masters_repo.infer_category) and, from v0.6.0, replaced by
        # Zoho's Item Type once the product appears on the invoice export
        # (invoices_repo.apply_zoho_categories) unless set by hand.
        # A matched column holding other text (Items.xlsx "Product Type"
        # has notes such as "120 sqft purchased") is ignored for that row.
        FieldDef("category", "Category", kind="choice",
                 choices=PRODUCT_CATEGORIES, default="Product", width=100,
                 synonyms=("type", "product type", "item type",
                           "product/service", "goods/service")),
        # Links the product to a row of the Incentive master. Blank = the
        # product earns no incentive.
        FieldDef("incentive_group", "Incentive group", kind="lookup",
                 lookup="incentives", width=190,
                 synonyms=("incentive item", "incentive category",
                           "incentive head", "incentive product",
                           "incentive name")),
        FieldDef("selling_price", "Selling price (₹)", kind="money",
                 dated=True, default=0.0, width=130,
                 synonyms=("selling price", "sp", "sale price", "sales price",
                           "selling rate", "rate", "price", "mrp",
                           # client's Items.xlsx (v0.6.0)
                           "sale with gst", "selling price with gst",
                           "sale price with gst")),
        FieldDef("cost_price", "Cost price (₹)", kind="money",
                 dated=True, default=0.0, width=120,
                 synonyms=("cost price", "cp", "cost", "purchase price",
                           "purchase rate", "landing cost", "cost rate",
                           # client's Items.xlsx (v0.6.0)
                           "purchase without gst", "purchase price without gst",
                           "cost without gst")),
        FieldDef("has_labour", "Labour involved", kind="bool",
                 default=False, width=125,
                 synonyms=("labour involved", "labor involved",
                           "labour applicable", "involves labour",
                           "labour yes/no", "labour (yes/no)", "labour y/n",
                           "labour required")),
        # A heading of just "Labour" holds AMOUNTS in the client's
        # Items.xlsx, so it belongs to Labour charge, not to the yes/no
        # field above (fixed in v0.6.0). When no Labour involved column is
        # matched, Labour involved = Yes for a labour charge above zero.
        FieldDef("labour_charge", "Labour charge (₹)", kind="money",
                 dated=True, default=0.0, width=135,
                 synonyms=("labour charge", "labour charges", "labor charge",
                           "labor charges", "labour cost", "labour amount",
                           "labour rate", "fitting charge",
                           "installation charge", "labour")),
        FieldDef("effective_from", "Effective from", kind="date",
                 importable=False, width=115),
        FieldDef("active", "Active", kind="bool", importable=False,
                 default=True, width=70),
    ),
)

# ---------------------------------------------------------------------------
# Sales executive master
# ---------------------------------------------------------------------------
EXECUTIVES = MasterDef(
    key="executives", title="Sales executives", singular="sales executive",
    filter_field="branch",
    fields=(
        FieldDef("name", "Name", required=True,
                 synonyms=("executive", "executive name", "sales executive",
                           "salesperson", "sales person", "employee name",
                           "staff name", "employee")),
        # Contact no is what makes an executive unique: two people may share
        # a name, but not a phone number.
        FieldDef("phone", "Contact no", required=True, width=170,
                 synonyms=("contact number", "contact", "phone",
                           "phone number", "phone no", "mobile",
                           "mobile number", "mobile no", "cell")),
        FieldDef("branch", "Branch", width=200,
                 synonyms=("city", "location", "town", "place", "outlet",
                           "showroom")),
        # Staff who leave can be marked inactive rather than deleted, so their
        # past sales still appear correctly when earlier months are re-run.
        FieldDef("active", "Active", kind="bool", default=True, width=70,
                 synonyms=("status", "is active", "active (yes/no)")),
    ),
)

# ---------------------------------------------------------------------------
# Car master
# ---------------------------------------------------------------------------
CAR_SEGMENTS = ("Hatchback", "Sedan", "Compact SUV", "SUV", "MUV",
                "Pickup", "Luxury")

CARS = MasterDef(
    key="cars", title="Cars", singular="car", filter_field="segment",
    fields=(
        FieldDef("make", "Make", width=180,
                 synonyms=("brand", "manufacturer", "company", "car make",
                           "car brand")),
        FieldDef("model", "Model", required=True,
                 synonyms=("car model", "car", "vehicle", "vehicle model",
                           "model name", "car name")),
        # Segment lets the vehicle-wise report group cars as well as list
        # them. The list is a suggestion: other values can be typed in.
        FieldDef("segment", "Segment", kind="choice", choices=CAR_SEGMENTS,
                 open_choice=True, width=180,
                 synonyms=("car segment", "type", "body type", "car type",
                           "class", "category")),
        FieldDef("active", "Active", kind="bool", importable=False,
                 default=True, width=70),
    ),
)

# ---------------------------------------------------------------------------
# Incentive master
# ---------------------------------------------------------------------------
INCENTIVES = MasterDef(
    key="incentives", title="Incentives", singular="incentive item",
    fields=(
        FieldDef("name", "Product / Service", required=True,
                 synonyms=("products / service", "products/service",
                           "product/service", "products", "product",
                           "service", "item", "incentive item",
                           "incentive group", "description", "particulars")),
        FieldDef("incentive_amount", "Incentive amount (₹)", kind="money",
                 dated=True, default=0.0, width=160,
                 synonyms=("incentive amount", "incentive", "incentive rs",
                           "incentive value", "amount")),
        # The bill value the incentive amount is based on. How a lower bill
        # (discount) reduces the incentive is awaited from the client.
        FieldDef("bill_value", "Bill value (₹)", kind="money",
                 dated=True, default=0.0, width=140,
                 synonyms=("bill value", "bill amount", "base value",
                           "invoice value", "standard bill value",
                           "bill")),
        FieldDef("effective_from", "Effective from", kind="date",
                 importable=False, width=115),
        FieldDef("active", "Active", kind="bool", importable=False,
                 default=True, width=70),
    ),
)

ALL_MASTERS = (PRODUCTS, EXECUTIVES, CARS, INCENTIVES)
MASTERS_BY_KEY = {m.key: m for m in ALL_MASTERS}
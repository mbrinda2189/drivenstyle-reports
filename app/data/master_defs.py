"""
master_defs.py - The shape of each master
=========================================

WHAT THIS MODULE DOES
---------------------
Describes, in one place, the fields of the three masters the client
provides:

    Product          SKU | Product name | HSN/SAC | Category | Selling price |
                     Cost price | Labour involved | Labour charge |
                     Effective from | Active
    Sales executive  Name | Phone | City | Active
    Car              Make | Model | Segment | Active

The same definitions drive three things, so they can never drift apart:

    * the Masters screen      - which columns to show and how to edit them
    * the Excel import        - which fields to match to the sheet's columns,
                                and the column headings recognised
                                automatically (`synonyms`)
    * the Excel export        - the column headings written out

FIELD KINDS
-----------
    "text"   free text (SKU, names, HSN/SAC, phone, city)
    "money"  a rupee amount, shown with Indian grouping (12,34,567.00)
    "bool"   yes / no, shown as a tick box
    "choice" one value from a list (`choices`). If `open_choice` is True the
             user may also type a new value (used for car segment).
    "date"   the effective-from date of a product's current rates; set by
             the tool, never typed or imported

DATED FIELDS (RATE HISTORY)
---------------------------
Fields with `dated=True` (selling price, cost price, labour charge) keep a
history: each change is stored with the date it applies from, so re-running
an earlier month uses the rates that applied then. See masters_repo.py.

The Incentive master is not defined yet - its rules are still awaited from
the client.
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

    key: str                        # internal name, also the database column
    label: str                      # heading shown on screen and in exports
    kind: str = "text"              # text / money / bool / choice / date
    required: bool = False          # must be filled in (import and save)
    choices: tuple[str, ...] = ()   # allowed values for kind "choice"
    open_choice: bool = False       # "choice" that also accepts new values
    dated: bool = False             # rate with effective-from history
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

    key: str                        # "products" / "executives" / "cars"
    title: str                      # tab title, e.g. "Products"
    singular: str                   # e.g. "product" (used in messages)
    fields: tuple[FieldDef, ...] = field(default_factory=tuple)
    has_rates: bool = False         # True if some fields are dated rates

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


# ---------------------------------------------------------------------------
# Product master
# ---------------------------------------------------------------------------
PRODUCT_CATEGORIES = ("Product", "Service")

PRODUCTS = MasterDef(
    key="products", title="Products", singular="product", has_rates=True,
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
        # (see masters_repo.infer_category).
        FieldDef("category", "Category", kind="choice",
                 choices=PRODUCT_CATEGORIES, default="Product", width=100,
                 synonyms=("type", "product type", "item type",
                           "product/service", "goods/service")),
        FieldDef("selling_price", "Selling price (₹)", kind="money",
                 dated=True, default=0.0, width=130,
                 synonyms=("selling price", "sp", "sale price", "sales price",
                           "selling rate", "rate", "price", "mrp")),
        FieldDef("cost_price", "Cost price (₹)", kind="money",
                 dated=True, default=0.0, width=120,
                 synonyms=("cost price", "cp", "cost", "purchase price",
                           "purchase rate", "landing cost", "cost rate")),
        FieldDef("has_labour", "Labour involved", kind="bool",
                 default=False, width=125,
                 synonyms=("labour involved", "labor involved",
                           "labour applicable", "involves labour",
                           "labour yes/no", "labour (yes/no)", "labour y/n",
                           "labour required", "labour")),
        FieldDef("labour_charge", "Labour charge (₹)", kind="money",
                 dated=True, default=0.0, width=135,
                 synonyms=("labour charge", "labour charges", "labor charge",
                           "labor charges", "labour cost", "labour amount",
                           "labour rate", "fitting charge",
                           "installation charge")),
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
    fields=(
        FieldDef("name", "Name", required=True,
                 synonyms=("executive", "executive name", "sales executive",
                           "salesperson", "sales person", "employee name",
                           "staff name", "employee")),
        FieldDef("phone", "Phone", width=160,
                 synonyms=("phone number", "phone no", "mobile",
                           "mobile number", "mobile no", "contact",
                           "contact number", "contact no")),
        FieldDef("city", "City", width=180,
                 synonyms=("location", "town", "place", "branch")),
        # Staff who leave are marked inactive rather than deleted, so their
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
    key="cars", title="Cars", singular="car",
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

ALL_MASTERS = (PRODUCTS, EXECUTIVES, CARS)

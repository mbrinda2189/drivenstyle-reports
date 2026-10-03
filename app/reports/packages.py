"""
packages.py - Recognising package sales on an invoice (v0.8.0)
==============================================================

WHAT A PACKAGE IS
-----------------
Drive N Style sells packages printed on its coupon - Basic, Essential,
Premium, Ceramic Protection, Graphene Protection, PPF 5 year, PPF 8 year.
A package is a fixed list of items (e.g. Basic = PVC full mat + sunfilm
side/rear + sunfilm front + teflon + underbody + silencer + glass coating)
sold together at a reduced "final value".

HOW IT IS BILLED - AND WHY THE TOOL HAS TO WORK IT OUT
------------------------------------------------------
Zoho has no "package" item. The staff bill every item of the package as a
separate line and give the package discount as an invoice discount. So the
only way to know a package was sold is the rule Brinda gave (03-10-2026):

    an invoice is a package sale when EVERY item of the package is on it.

The coupon names an item generally ("PVC Full Mat") while Zoho has one item
per car ("I20 - PVC Full Floor Mat + Labour Extra", "Venue - ..."). The
Packages master (Masters screen > Packages) therefore lists, for every
package item, each Zoho item that counts for it:

    Package          Package item    Zoho item name
    Basic Package    PVC Full Mat    I20 - PVC Full Floor Mat + Labour Extra
    Basic Package    PVC Full Mat    Venue - PVC Full Floor Mat + Labour Extra
    Basic Package    Teflon Coating  Teflon Coating - All Cars
    ...

RULES
-----
* Every package item must be matched by a DIFFERENT invoice line.
* Matching is on the item, not on the price billed.
* If an invoice fits more than one package, the one with the higher coupon
  value is taken (then the one with more items).
* One package per invoice. Other lines on the invoice are normal sales.
* "Almost a package": no package fits, but exactly one item of a package
  (of three items or more) is missing - listed so the client can be asked.

The coupon's final value and the package incentive are NOT stored here:
they are the Bill value and Incentive amount of the row with the same name
in the Incentive master ("Basic Package", ...).

This module has no database and no Qt code: it only compares names.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.data.masters_repo import name_key


@dataclass
class PackageDef:
    """One package: its items, and the Zoho items that count for each."""
    name: str
    slots: dict[str, set[str]] = field(default_factory=dict)  # item -> product keys


@dataclass
class Match:
    package: PackageDef
    lines: list            # the invoice lines that make up the package
    missing: list[str]     # package items not found on the invoice


def build_defs(rows: list[dict]) -> list[PackageDef]:
    """Packages master rows (package, item, product, active) -> PackageDefs."""
    defs: dict[str, PackageDef] = {}
    for r in rows:
        if not r.get("active", True):
            continue
        d = defs.setdefault(name_key(r["package"]), PackageDef(r["package"].strip()))
        d.slots.setdefault(r["item"].strip(), set()).add(name_key(r["product"]))
    return list(defs.values())


def match(package: PackageDef, lines: list) -> Match:
    """Try to find a different line for every item of the package."""
    free = list(lines)
    used, missing = [], []
    # items with the fewest possible Zoho items first, so a line that fits
    # two items is not taken by the wrong one
    for item, products in sorted(package.slots.items(), key=lambda s: len(s[1])):
        fits = [l for l in free if name_key(l.product) in products]
        if not fits:
            missing.append(item)
            continue
        best = max(fits, key=lambda l: l.sales)
        free.remove(best)
        used.append(best)
    return Match(package, used, missing)


def detect(defs: list[PackageDef], lines: list,
           value_of) -> tuple[Match | None, Match | None]:
    """
    (package sold, almost-a-package) for one invoice's lines.
    `value_of(name)` gives the coupon value used to choose between two
    packages that both fit. At most one of the two results is set.
    """
    matches = [match(d, lines) for d in defs if d.slots]
    full = [m for m in matches if not m.missing]
    rank = lambda m: (value_of(m.package.name), len(m.package.slots))
    if full:
        return max(full, key=rank), None
    near = [m for m in matches
            if len(m.missing) == 1 and len(m.package.slots) >= 3]
    # the package with the most items found is the likeliest one meant
    return None, (max(near, key=lambda m: (len(m.lines), *rank(m))) if near else None)

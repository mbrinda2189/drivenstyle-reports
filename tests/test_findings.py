"""
test_findings.py - Key findings (v0.36.0, app/reports/findings.py)
=================================================================

What must hold (plan confirmed by Brinda, 16-11-2026):

    * the profit bridge adds up EXACTLY to the change in net profit, and
      volume + mix + cost rate add up exactly to the change in product
      cost - against the previous month and against the average
    * the average is of up to three months BEFORE the month (never the
      month itself); with one earlier month there is no average
    * a finding is listed when its change is worth the threshold or more
      against either comparison; the threshold is one setting (default
      Rs. 1,000), saved and logged
    * the admin's edits: a changed sentence is shown instead of the
      tool's, a finding left out is not listed, remarks come last; every
      change is in the audit log; the figures are never stored
    * the workbook has "Key findings" and "Drivers"; the PDFs open with
      the findings only when there is something to compare with
    * the web screen's addresses are for admins only
"""

import copy

import pytest
from openpyxl import load_workbook

from app.data.inputs_repo import DEFAULT_FINDINGS_THRESHOLD, InputsRepo
from app.reports import findings as fd
from app.reports.data import build_month
from app.reports.generate import generate
from tests.test_reports import world            # noqa: F401  (the fixture)


def variant(m, month: int, drop_every: int = 0, cost_factor: float = 1.0,
            costs: list | None = None):
    """An earlier month made from `m`: some invoices left out, costs scaled."""
    v = copy.deepcopy(m)
    v.month = month
    if drop_every:
        v.invoices = [i for n, i in enumerate(v.invoices) if n % drop_every]
    for line in v.lines:
        line.cost = round(line.cost * cost_factor, 2)
    if costs is not None:
        v.indirect_costs = costs
    return v


@pytest.fixture
def months(world):                               # noqa: F811
    repo, inv, inp = world
    sep = build_month(repo, inv, inp, 2026, 9)
    earlier = [variant(sep, 6, cost_factor=0.8, costs=[("Rent", 40000)]),
               variant(sep, 7, drop_every=2, cost_factor=1.1, costs=[("Rent", 45000)]),
               variant(sep, 8, drop_every=2, cost_factor=0.9,
                       costs=[("Rent", 45000), ("Electricity", 9000)])]
    return sep, earlier


def by_key(result):
    return {r.key: r for r in result.rows}


def test_bridge_and_cost_split_add_up_exactly(months):
    sep, earlier = months
    r = fd.compute(sep, earlier, threshold=0)
    rows = by_key(r)
    for side in ("prev", "avg"):
        change = lambda key: getattr(rows[key], "change_" + side)
        bridge = sum(getattr(f, "effect_" + side) for f in r.rows if f.key.startswith("bridge:"))
        assert bridge == pytest.approx(change("net"), abs=0.05)
        split = sum(getattr(f, "effect_" + side) for f in r.rows if f.key.startswith("cogs:"))
        assert split == pytest.approx(change("cost"), abs=0.05)
    # the cost per unit rose 10% from August's 0.9: "cost rate" carries it
    assert rows["cogs:rate"].effect_prev > 0
    # invoices x earlier bill + invoices now x change in bill = change in sales
    sales = rows["invoices"].effect_prev + rows["avg_bill"].effect_prev
    assert sales == pytest.approx(rows["sales"].change_prev, abs=0.05)


def test_comparisons_previous_month_and_average_of_three(months):
    sep, earlier = months
    r = fd.compute(sep, earlier)
    assert (r.prev_label, r.avg_label, r.avg_months) == ("Aug 2026", "Jun–Aug 2026", 3)
    rows = by_key(r)
    assert rows["head:Rent"].prev == 45000
    assert rows["head:Rent"].avg == pytest.approx((40000 + 45000 + 45000) / 3)
    assert rows["head:Electricity"].avg == pytest.approx(3000)       # 0 in June and July
    # only the last three months count, and never September itself
    four = fd.compute(sep, [variant(sep, 5, costs=[("Rent", 1)])] + earlier)
    assert by_key(four)["head:Rent"].avg == rows["head:Rent"].avg
    # one earlier month: no average (it would only repeat the previous month)
    one = fd.compute(sep, earlier[-1:])
    assert one.comparable and not one.avg_label and by_key(one)["sales"].avg is None
    none = fd.compute(sep, [])
    assert not none.comparable and none.rows == []


def test_threshold_decides_what_is_listed(months):
    sep, earlier = months
    small = fd.compute(sep, earlier, threshold=0)
    big = fd.compute(sep, earlier, threshold=10_00_000)
    every = [r for r in small.rows if r.size > 0]
    assert len(small.listed(fd.MANAGEMENT)) + len(small.listed(fd.INTERNAL)) >= len(every)
    assert big.listed(fd.MANAGEMENT) == [] and big.listed(fd.INTERNAL) == []
    mid = fd.compute(sep, earlier, threshold=5000)
    assert all(r.size >= 5000 for p in fd.PARTS for r in mid.listed(p))
    assert all(not r.material for r in mid.rows if r.size < 5000)
    # headline first in each section
    listed = mid.listed(fd.MANAGEMENT)
    assert listed[0].section == "Profit bridge"
    rent = by_key(mid)["head:Rent"]
    assert "Rent ₹45,000" in rent.draft and "on Aug 2026" in rent.draft


def test_threshold_setting_is_saved_and_logged(world):    # noqa: F811
    repo, _, inp = world
    assert inp.findings_threshold() == DEFAULT_FINDINGS_THRESHOLD == 1000
    inp.save_findings_threshold(2500)
    assert InputsRepo(repo).findings_threshold() == 2500
    with pytest.raises(ValueError):
        inp.save_findings_threshold(-1)
    log = repo.conn.execute("SELECT field, old_value, new_value FROM audit_log "
                            "WHERE source = 'Key findings'").fetchall()
    assert [tuple(r) for r in log] == [("Key findings – smallest change listed (Rs.)",
                                        "1,000.00", "2,500.00")]


def test_admin_edits_hidden_findings_and_remarks(months, world):    # noqa: F811
    sep, earlier = months
    repo, _, inp = world
    logged = inp.save_findings_edits(2026, 9, fd.MANAGEMENT, [
        {"key": "net", "text": "  Profit rose:  more invoices. "},
        {"key": "sales", "hidden": True},
        {"key": "gp", "text": "", "hidden": False}],          # = the tool's sentence: not stored
        ["Check the rent.", " "])
    assert logged == 3                                         # two findings + the remarks
    saved = inp.findings_edits(2026, 9)
    assert saved["edits"] == {(fd.MANAGEMENT, "net"): {"text": "Profit rose: more invoices.",
                                                        "hidden": False},
                              (fd.MANAGEMENT, "sales"): {"text": "", "hidden": True}}
    assert saved["remarks"] == {fd.MANAGEMENT: ["Check the rent."]}
    r = fd.compute(sep, earlier, threshold=0, edits=saved["edits"], remarks=saved["remarks"])
    listed = r.listed(fd.MANAGEMENT)
    keys = [f.key for f in listed]
    assert "sales" not in keys and "sales" in [f.key for f in r.listed(fd.MANAGEMENT, True)]
    net = next(f for f in listed if f.key == "net")
    assert net.text == "Profit rose: more invoices." and net.edited and net.draft != net.text
    assert listed[-1].kind == "remark" and listed[-1].text == "Check the rent."
    assert all(f.kind != "remark" for f in r.listed(fd.INTERNAL))
    # saving the other report leaves this one alone; saving nothing clears it
    inp.save_findings_edits(2026, 9, fd.INTERNAL, [{"key": "incentive", "hidden": True}], [])
    assert len(inp.findings_edits(2026, 9)["edits"]) == 3
    inp.save_findings_edits(2026, 9, fd.MANAGEMENT, [], [])
    assert inp.findings_edits(2026, 9) == {
        "edits": {(fd.INTERNAL, "incentive"): {"text": "", "hidden": True}}, "remarks": {}}
    log = repo.conn.execute("SELECT action, field FROM audit_log WHERE source = 'Key findings' "
                            "ORDER BY id").fetchall()
    assert [tuple(x) for x in log][:3] == [("Added", "net"), ("Added", "sales"),
                                           ("Edited", "Remarks")]
    with pytest.raises(ValueError):
        inp.save_findings_edits(2026, 9, "owner", [], [])


def test_workbook_and_pdf_carry_the_findings(world, tmp_path, monkeypatch):    # noqa: F811
    repo, inv, inp = world
    # Only September is read: the sheets are there, saying there is nothing to compare.
    r = generate(repo, inv, inp, 2026, 9, tmp_path, ["Profit & loss"])
    wb = load_workbook(r.path)
    assert wb.sheetnames[2:4] == ["Key findings", "Drivers"]
    texts = [c.value for row in wb["Key findings"].iter_rows() for c in row if c.value]
    assert any("nothing to compare" in str(t) for t in texts)

    # With earlier months the PDF version opens with the findings.
    from app.reports.pdf_book import INTERNAL, MANAGEMENT, write_pdf_workbook
    sep = build_month(repo, inv, inp, 2026, 9)
    earlier = [variant(sep, 7, cost_factor=0.8), variant(sep, 8, cost_factor=1.2)]
    found = fd.compute(sep, earlier, threshold=0,
                       edits={(MANAGEMENT, "net"): {"text": "Edited by the CA.", "hidden": False}},
                       remarks={INTERNAL: ["Pay labour by the 5th."]})
    for part, expect in ((MANAGEMENT, "Edited by the CA."), (INTERNAL, "• Pay labour by the 5th.")):
        book = write_pdf_workbook(sep, [], None, tmp_path / f"{part}.xlsx", part=part,
                                  findings=found)
        ws = load_workbook(book)["Report"]
        column_a = [ws.cell(i, 1).value for i in range(1, ws.max_row + 1)]
        assert column_a[0] == "Key findings" and expect in column_a
        # the section after the findings starts a new page
        assert ws.row_breaks.brk
    # nothing to compare: no findings page
    book = write_pdf_workbook(sep, [], None, tmp_path / "none.xlsx", part=MANAGEMENT,
                              findings=fd.compute(sep, []))
    assert load_workbook(book)["Report"].cell(1, 1).value != "Key findings"


def test_long_sentences_are_split_for_the_pdf():
    text = "word " * 80
    lines = fd._split(text)
    assert len(lines) > 1 and all(len(x) <= fd.LINE_CHARS for x in lines)
    assert " ".join(lines) == text.strip()


def test_no_misleading_percentages():
    """v0.36.1: no % change from a loss or a tiny figure; a profit that turns
    into a loss is said in words - the same rule in sentences and tables."""
    assert fd.pct_change("money", 150, 100, small=1000) is None        # base below threshold
    assert fd.pct_change("money", -55861, 20258, small=1000) == pytest.approx(-3.7574, abs=1e-3)
    assert fd.pct_change("money", 100, -500, small=0) is None           # base is a loss
    assert fd.pct_change("count", 12, 10, small=1000) == pytest.approx(0.2)
    assert fd.pct_change("pct", 0.3, 0.2) is None
    turned = fd._move("money", -55861.48, 20258.42, 1000, profit=True)
    assert turned == "turned from a profit of ₹20,258 to a loss of ₹55,861"
    assert "%" not in fd._move("money", 1500, 400, 1000)
    w = fd._Words("Sep 2026", None, 1000)
    assert w.compare("money", -55861.48, 20258.42, None, profit=True) == \
        "turned from a profit of ₹20,258 to a loss of ₹55,861 on Sep 2026"


def test_percent_columns_follow_the_same_rule(months):
    sep, earlier = months
    r = fd.compute(sep, earlier, threshold=10_00_000)        # every base is "small"
    rows = by_key(r)
    assert rows["sales"].pct_prev is None and fd._cells(rows["sales"])[3] is None
    assert rows["invoices"].pct_prev is not None             # counts keep their %
    assert rows["sales"].as_dict()["pct_prev"] is None

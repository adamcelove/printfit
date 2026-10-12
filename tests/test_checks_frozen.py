"""Every measured check against frozen geometry. No Chrome."""
import pytest

from printfit import profile as P
from printfit.checks import aspect_ratio, figure_height, page_slack, run_all, text_scale
from printfit.render import load_artifacts

U1 = {"roles": {"grid": "graph", "g-pa": "smallmultiple", "g-nl": "scale"}}


@pytest.fixture(scope="module")
def prefix():
    return load_artifacts("tests/fixtures/geometry-prefix-worksheet.json")


@pytest.fixture(scope="module")
def fixed():
    return load_artifacts("tests/fixtures/geometry-fixed-worksheet.json")


def by_check(findings, name):
    return [f for f in findings if f.id.split(":")[0] == name]


def test_prefix_auto_height_all_graphs(prefix):
    f = by_check(figure_height.run(prefix, U1), "auto_height")
    assert len([x for x in f if x.failed]) == 13


def test_prefix_figure_height(prefix):
    f = by_check(figure_height.run(prefix, U1), "figure_height")
    big = [x for x in f if x.value >= 0.45]
    assert len(big) >= 3 and all(x.severity == "soft" for x in big)


def test_prefix_text_scale(prefix):
    f = [x for x in text_scale.run(prefix, U1) if x.failed]
    assert any(x.value == pytest.approx(1.90, abs=0.05) for x in f)
    assert any("`.al`" in x.message or "`.tk`" in x.message for x in f)


def test_prefix_no_aspect_failure_on_graphs(prefix):
    # the 13 x-t graphs measure a graph-like AR; only the un-classed number line
    # (viewBox 210x74) exceeds the graph ceiling, and it is soft
    graphs = {f["selector"] for f in prefix.dom_geometry["figures"] if f["viewbox"]["h"] != 74 and f["viewbox"]["w"] != 210}
    bad = [x for x in aspect_ratio.run(prefix, U1) if x.severity != "info" and x.selector in graphs]
    assert bad == []
    assert not any(x.failed for x in aspect_ratio.run(prefix, U1))


def test_fixed_zero_hard(fixed):
    findings, skipped = run_all(fixed, U1)
    assert [f for f in findings if f.failed] == []
    assert skipped == []


def test_fixed_per_figure(fixed):
    ar = {f.selector: f for f in aspect_ratio.run(fixed, U1)}
    ts = {f.selector: f for f in text_scale.run(fixed, U1)}
    fh = {f.id: f for f in figure_height.run(fixed, U1)}
    nl = ar["svg.grid.g-nl"]
    assert nl.severity == "info" and nl.role == "scale" and nl.value == pytest.approx(7.62, abs=0.05)
    assert fh["auto_height:svg.grid.g-nl"].severity == "info"
    assert "svg.grid.g-warm" not in ts and "svg.grid.g-warm" not in ar
    for i in ("", "[2]", "[3]", "[8]"):
        assert f"svg.grid.g-pa{i}" not in ts
        assert f"figure_height:svg.grid.g-pa{i}" not in fh
    assert "svg.grid.g-pb" not in ts
    if "svg.grid.g-pc" in ts:
        assert ts["svg.grid.g-pc"].severity == "soft"
    assert max(f["rect"]["h"] for f in fixed.dom_geometry["figures"]) / fixed.page_content_h_px < 0.30


def test_page_slack_and_fill(prefix, fixed):
    hard = [f for f in page_slack.run(fixed, P.load(None)) if f.failed]
    assert hard == []
    assert fixed.page_count == 5 and prefix.page_count == 7
    fills = page_slack.fill_ratio(prefix)
    assert any(f.severity == "soft" for f in fills)


def test_unknown_roles_skip(fixed):
    findings, skipped = run_all(fixed, P.load(None))
    assert set(skipped) == {"aspect_ratio", "auto_height"}
    assert [f for f in findings if f.failed] == []

import copy
from pathlib import Path

import pytest

from printfit.checks import color, text_scale
from printfit.render import load_artifacts

FIX = Path("tests/fixtures/synthetic")


def test_preflight_flags_prefix_oversized_viewbox():
    f = text_scale.preflight(str(FIX / "prefix-worksheet.html"))
    assert {x.selector for x in f} == {"svg.grid.g-pc", "svg.grid.g-pc[2]"}
    assert all(x.failed and x.value == pytest.approx(1.90, abs=0.01) for x in f)
    assert "scale 2.61x" in f[0].message


def test_preflight_sizes_flex_column_figures_by_their_column():
    # g-pa sits in `flex:0 0 46%` columns: 300px wide, scale 0.97 -- the
    # measured check passes it, so the preflight must not fail it at page width
    figs = {x["selector"]: x for x in text_scale.static_figures(str(FIX / "prefix-worksheet.html"))}
    assert figs["svg.grid.g-pa"]["width_px"] == pytest.approx(300.3, abs=0.5)
    assert figs["svg.grid.g-pa"]["exact"]


def _doc(tmp_path, css, body):
    p = tmp_path / "doc.html"
    p.write_text(f"<html><head><style>@page{{size:letter;margin:.5in}}body{{margin:0;font-size:12px}}"
                 f"{css}</style></head><body>{body}</body></html>")
    return str(p)


SVG = '<svg class="f" viewBox="0 0 200 100"><text class="t" x="5" y="20">label</text></svg>'


def test_preflight_descendant_selector_reaches_only_descendants(tmp_path):
    # `.gp svg{width:100%}` once applied to every svg in the document
    doc = _doc(tmp_path, "svg{width:200px} .gp svg{width:100%} .t{font-size:10px}",
               f'<div class="gp">{SVG}</div>{SVG}')
    a, b = text_scale.static_figures(doc)
    assert a["width_px"] == pytest.approx(720) and b["width_px"] == pytest.approx(200)


def test_preflight_rule_after_comment_applies(tmp_path):
    doc = _doc(tmp_path, "svg.f{width:200px} /* labels */ .t{font-size:20px}", SVG)
    assert text_scale.static_figures(doc)[0]["worst_px"] == pytest.approx(20)


def test_preflight_floor_uses_smallest_label_in_a_class(tmp_path):
    svg = ('<svg class="f" viewBox="0 0 200 100" style="width:200px">'
           '<text class="t" style="font-size:10px">a</text><text class="t" style="font-size:6px">b</text></svg>')
    f = text_scale.preflight(_doc(tmp_path, "", svg))
    assert len(f) == 1 and f[0].failed and "6.0px" in f[0].message


def test_preflight_skips_figures_hidden_in_blank_state(tmp_path):
    doc = _doc(tmp_path, ".ans{display:none} svg.f{width:720px} .t{font-size:30px}",
               f'<div class="ans">{SVG}</div>')
    assert text_scale.preflight(doc) == []


def test_measured_floor_uses_smallest_label_in_a_class():
    art = copy.deepcopy(load_artifacts("tests/fixtures/geometry-fixed-worksheet.json"))
    fig = next(f for f in art.dom_geometry["figures"] if f.get("texts"))
    fig["texts"] = [dict(fig["texts"][0], realised_px=11.0, min_realised_px=6.3)]
    art.dom_geometry["figures"] = [fig]
    f = [x for x in text_scale.run(art, {}) if x.failed]
    assert len(f) == 1 and "6.3px" in f[0].message


def test_preflight_clears_fixed():
    for name in ("fixed-worksheet",):
        assert text_scale.preflight(str(FIX / f"{name}.html")) == [], name


def test_print_color_flags_key_and_ans():
    for name in ("fixed-worksheet", "prefix-worksheet"):
        sels = {x.selector for x in color.preflight_print_color(str(FIX / f"{name}.html"))}
        assert ".key" in sels, sels
        assert not any(f.startswith("hard") for f in sels)


def test_print_color_ignores_screen_only_toggle_ui(tmp_path):
    css = ("#bar button.on{background:#1a5c3a} @media print{#bar{display:none!important}}"
           "body.edit [contenteditable]:focus{background:#f3f8f5} a:hover{background:#eee}"
           ".band{background:#f2f2f2}")
    sels = {x.selector for x in color.preflight_print_color(_doc(tmp_path, css, "<p>x</p>"))}
    assert sels == {".band"}


@pytest.mark.browser
def test_chrome_measured_floor_sees_the_smallest_label_in_a_class(tmp_path):
    from printfit import render as R
    svg = ('<svg class="f" viewBox="0 0 200 100" style="width:200px;height:100px">'
           '<text x="5" y="20" style="font-size:10px">a</text><text x="5" y="60" style="font-size:6px">b</text></svg>')
    art = R.render(_doc(tmp_path, "", svg), str(tmp_path / "out"))
    f = [x for x in text_scale.run(art, {}) if x.failed]
    assert len(f) == 1 and "6.0px" in f[0].message

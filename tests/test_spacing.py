"""Spacing / composition checks (approach C). No Chrome: synthetic
RenderArtifacts per check, then the frozen E0 pair from out/."""
from __future__ import annotations

import os

import pytest

from printfit.checks import spacing
from printfit.render import load_artifacts
from printfit.types import PageMetrics, RenderArtifacts

H, W, BODY = 1000.0, 700.0, 14.0
LINE = BODY * spacing.BODY_LINE_FACTOR
OUT = os.path.join(os.path.dirname(__file__), "..", "out")


# --- synthetic builders ------------------------------------------------------

def rect(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def block(sel, y, h, kind="text", x=0.0, w=W, qa=None, tag="p", classes=(),
          data_for=None):
    return {"selector": sel, "tag": tag, "classes": list(classes), "rect": rect(x, y, w, h),
            "kind": kind, "font_px": BODY, "line_height_px": LINE, "data_role": None,
            "data_for": data_for, "qa": qa}


def qa(sel, y, h, x=0.0, w=W, qid=None):
    return {"selector": sel, "qid": qid, "classes": ["qa"], "offset_top": y,
            "offset_height": h, "rect": rect(x, y, w, h)}


def figure(sel, y, h, x=0.0, w=W):
    return {"selector": sel, "classes": ["grid"], "rect": rect(x, y, w, h),
            "viewbox": {"w": 100, "h": 50}, "css_height_is_auto": False, "texts": []}


def heading(sel, y, h=30.0, level=2, brk="auto"):
    return {"level": level, "text": sel, "selector": sel, "offset_top": y,
            "rect": rect(0.0, y, W, h), "break_before": brk}


def lines_for(sel, y, n, lead=20.0):
    return [{"y_top": y + i * lead, "y_bottom": y + i * lead + lead * 0.8,
             "x_left": 0.0, "x_right": W, "block": sel} for i in range(n)]


def make(blocks, qas=(), figures=(), lines=(), headings=(), n_pages=2) -> RenderArtifacts:
    pages = [PageMetrics(index=i, fill_ratio=0.9, slack_px=50.0, ends_in_explicit_break=False,
                         is_final=(i == n_pages)) for i in range(1, n_pages + 1)]
    geom = {"blocks": list(blocks), "qa": list(qas), "figures": list(figures),
            "lines": list(lines), "headings": list(headings),
            "doc_scroll_h": H * n_pages - 10}
    return RenderArtifacts(pdf_path="/dev/null", page_png_paths=[], dom_geometry=geom,
                           page_count=n_pages, page_content_h_px=H, page_content_w_px=W,
                           body_font_px=BODY, pages=pages)


def hard(findings, prefix=""):
    return [f for f in findings if f.severity == "hard" and f.id.startswith(prefix)]


def soft(findings, prefix=""):
    return [f for f in findings if f.severity == "soft" and f.id.startswith(prefix)]


# --- self_sufficiency --------------------------------------------------------

def test_group_taller_than_a_page_splits_and_is_hard():
    art = make([block("p.q", 110, 40, qa="div.qa"), block("span.sp", 160, 1000, "space", qa="div.qa")],
               qas=[qa("div.qa", 100, 1100)], n_pages=3)
    f = spacing.self_sufficiency(art, {})
    assert [x.id for x in hard(f)] == ["self_sufficiency:div.qa"]
    assert f[0].page == 1 and f[0].page_source == "dom_model"
    assert "spans pages 1-2" in f[0].message


def test_group_that_fits_is_pushed_whole_not_split():
    """break-inside:avoid emulation: a 150px group straddling y=1000 starts
    page 2 instead of splitting, and what follows moves with it."""
    art = make([block("p.q", 950, 40, qa="div.qa"), block("span.sp", 1000, 80, "space", qa="div.qa"),
                block("p", 1100, 40)],
               qas=[qa("div.qa", 940, 150)])
    model = spacing.PageModel(art)
    assert model.shift(939) == 0 and model.shift(940) == pytest.approx(60)
    assert model.page_of(950) == 2 and model.page_of(1100) == 2
    assert model.eff(art.dom_geometry["blocks"][2]).y == pytest.approx(1160)
    assert [x.severity for x in spacing.self_sufficiency(art, {})] == ["info"]


def test_figure_pushed_away_from_its_group_is_hard():
    """A group too tall to keep whole; its figure straddles the boundary,
    fits on a page, and so lands on page 2 while the group starts on 1."""
    art = make([block("p.q", 110, 40, qa="div.qa"),
                block("svg.grid", 950, 100, "figure", tag="svg", qa="div.qa")],
               qas=[qa("div.qa", 100, 1100)],
               figures=[figure("svg.grid", 950, 100)], n_pages=3)
    f = spacing.self_sufficiency(art, {})
    assert len(hard(f)) == 1
    assert "figure svg.grid is on page 2" in f[0].message


def test_data_for_block_on_other_page_is_hard():
    art = make([block("p.q", 100, 40, qa="div.qa"),
                block("div.ans", 1100, 40, data_for="q1")],
               qas=[qa("div.qa", 90, 60, qid="q1")])
    f = spacing.self_sufficiency(art, {})
    assert len(hard(f)) == 1 and "data-for" in f[0].message


def test_whole_group_is_info():
    art = make([block("p.q", 100, 40, qa="div.qa"), block("span.sp", 150, 80, "space", qa="div.qa")],
               qas=[qa("div.qa", 90, 150)], figures=[figure("svg.grid", 100, 30, x=400, w=200)])
    f = spacing.self_sufficiency(art, {})
    assert [x.severity for x in f] == ["info"]


def test_explicit_break_restarts_the_page_model():
    """A heading with break-before:page starts a fresh page, so a group below
    it is whole even though naive tiling would put it across y=1000."""
    art = make([block("h2.pb", 800, 30, tag="h2"), block("p.q", 950, 40, qa="div.qa"),
                block("span.sp", 1000, 80, "space", qa="div.qa")],
               qas=[qa("div.qa", 940, 150)],
               headings=[heading("h2.pb", 800, brk="page")])
    model = spacing.PageModel(art)
    assert [p.y_start for p in model.pages] == [0.0, 1000.0]
    assert model.pages[0].ends_in_explicit_break and not model.pages[1].ends_in_explicit_break
    assert model.shift(800) == pytest.approx(200)
    assert model.page_of(950) == 2 and model.page_of(1149) == 2
    assert not hard(spacing.self_sufficiency(art, {}))


# --- group_proximity ---------------------------------------------------------

def test_groups_closer_than_their_contents_is_hard():
    blocks = [block("p.q", 100, 20, qa="div.qa"), block("p.q[2]", 140, 20, qa="div.qa"),
              block("p.q[3]", 168, 20, qa="div.qa[2]"), block("p.q[4]", 208, 20, qa="div.qa[2]")]
    art = make(blocks, qas=[qa("div.qa", 100, 60), qa("div.qa[2]", 168, 60)])
    f = spacing.group_proximity(art, {})
    assert [x.id for x in hard(f)] == ["group_proximity:page-1"]
    assert f[0].value == pytest.approx(8 / 20, abs=0.01)


def test_groups_further_apart_than_contents_is_info():
    blocks = [block("p.q", 100, 20, qa="div.qa"), block("p.q[2]", 130, 20, qa="div.qa"),
              block("p.q[3]", 250, 20, qa="div.qa[2]"), block("p.q[4]", 280, 20, qa="div.qa[2]")]
    art = make(blocks, qas=[qa("div.qa", 100, 50), qa("div.qa[2]", 250, 50)])
    f = spacing.group_proximity(art, {})
    assert [x.severity for x in f] == ["info"] and f[0].value == pytest.approx(10.0)


def test_group_proximity_skips_pages_with_one_group():
    art = make([block("p.q", 100, 20, qa="div.qa")], qas=[qa("div.qa", 100, 20)])
    assert spacing.group_proximity(art, {}) == []


# --- macro_micro_sep ---------------------------------------------------------

def test_blocks_closer_than_leading_measures_below_one():
    blocks = [block("p", 100, 60), block("p[2]", 170, 60)]
    lines = lines_for("p", 100, 3) + lines_for("p[2]", 170, 3)
    art = make(blocks, lines=lines)
    f = spacing.macro_micro_sep(art, {})
    assert f[0].value == pytest.approx(0.5)
    # Thresholds are off by default: the ratio is 0.07-0.28 on every page of
    # the accepted reference (see the note above MACRO_MICRO_HARD).
    assert f[0].severity == "info"
    strict = spacing.macro_micro_sep(art, {}, hard_below=1.0, soft_below=1.4)
    assert strict[0].severity == "hard" and strict[0].id == "macro_micro_sep:page-1"
    wide = spacing.macro_micro_sep(make([block("p", 100, 60), block("p[2]", 185, 60)],
                                        lines=lines_for("p", 100, 3) + lines_for("p[2]", 185, 3)),
                                   {}, hard_below=1.0, soft_below=1.4)
    assert wide[0].severity == "soft" and wide[0].value == pytest.approx(1.25)


def test_macro_micro_skips_pages_without_lines():
    assert spacing.macro_micro_sep(make([block("p", 100, 60), block("p[2]", 170, 60)]), {}) == []


# --- tail_slack --------------------------------------------------------------

def test_tail_slack_soft_when_group_is_pushed_off_a_short_page():
    """Page 1 ink stops at 600; a 300px group straddles y=1000 and (as
    break-inside:avoid would do) moves to page 2, leaving 400px = 19.7 lines."""
    art = make([block("p", 100, 500), block("p.q", 950, 40, qa="div.qa"),
                block("span.sp", 1000, 240, "space", qa="div.qa")],
               qas=[qa("div.qa", 950, 300)])
    f = spacing.tail_slack(art, {})
    assert [x.id for x in soft(f)] == ["tail_slack:page-1"]
    assert f[0].value == pytest.approx(400 / LINE, abs=0.1)


def test_tail_slack_zero_when_a_paragraph_splits():
    art = make([block("p", 100, 500), block("p[2]", 950, 200)])
    f = spacing.tail_slack(art, {})
    assert f[0].severity == "info" and f[0].value == 0.0


def test_tail_slack_exempts_final_and_break_pages():
    art = make([block("p", 100, 500), block("h2.pb", 1000, 30, tag="h2"), block("p[2]", 1040, 100)],
               headings=[heading("h2.pb", 1000, brk="page")])
    assert spacing.PageModel(art).pages[0].ends_in_explicit_break
    assert spacing.tail_slack(art, {}) == []


def test_page_map_anchors_a_heading_to_its_pdf_page():
    """The render found this heading on page 2 although the model would put
    it on page 1: something the geometry does not list was pushed. Anchor."""
    art = make([block("p", 100, 400), block("h2", 700, 30, tag="h2"), block("p[2]", 740, 200),
                block("p[3]", 1100, 100)],
               headings=[heading("h2", 700)])
    art.dom_geometry["page_map"] = {"h2": 2}
    model = spacing.PageModel(art)
    assert model.page_of(700) == 2 and model.page_of(100) == 1
    assert spacing.tail_slack(art, {})[0].value == pytest.approx(500 / LINE, abs=0.1)


# --- largest_empty_rect ------------------------------------------------------

def test_empty_band_mid_page_is_soft():
    art = make([block("p", 0, 200), block("p[2]", 600, 400), block("p[3]", 1000, 500)])
    f = spacing.largest_empty_rect(art, {})
    page1 = next(x for x in f if x.page == 1)
    assert page1.severity == "soft" and page1.value == pytest.approx(0.4, abs=0.01)
    assert "y=200" in page1.message and "h=400" in page1.message
    assert next(x for x in f if x.page == 2).severity == "info"      # final page exempt


def test_answer_space_is_not_a_hole():
    art = make([block("p", 0, 200), block("span.sp", 200, 400, "space"), block("p[2]", 600, 400),
                block("p[3]", 1000, 500)])
    f = spacing.largest_empty_rect(art, {})
    page1 = next(x for x in f if x.page == 1)
    assert page1.severity == "soft"                                   # space is not ink
    assert page1.value == pytest.approx(0.4, abs=0.01)


def test_half_column_hole_is_found():
    art = make([block("p", 0, 200), block("p[2]", 200, 800, w=W / 2), block("p[3]", 1000, 500)])
    f = spacing.largest_empty_rect(art, {})
    page1 = next(x for x in f if x.page == 1)
    assert page1.severity == "soft" and page1.value == pytest.approx(0.4, abs=0.01)
    assert "x=350" in page1.message


# --- composition -------------------------------------------------------------

def test_evenly_composed_page_has_no_non_info_findings():
    blocks = [block("h2", 0, 30, tag="h2"), block("p", 50, 200), block("span.sp", 260, 240, "space"),
              block("p[2]", 520, 180), block("span.sp[2]", 710, 190, "space"),
              block("p[3]", 910, 70), block("p[4]", 1050, 300)]
    lines = lines_for("p", 50, 10) + lines_for("p[2]", 520, 9) + lines_for("p[3]", 910, 3)
    art = make(blocks, lines=lines, headings=[heading("h2", 0)])
    findings = spacing.run(art, {})
    assert [f.id for f in findings if f.severity != "info"] == []
    shares = spacing.page_shares(art, {}, spacing.PageModel(art).page(1))
    assert shares["read_text"] == pytest.approx(0.45, abs=0.01)
    assert shares["working_room"] == pytest.approx(0.43, abs=0.01)
    assert shares["structure"] == pytest.approx(0.03, abs=0.01)


def test_composition_out_of_band_is_soft_on_non_final_page():
    art = make([block("svg", 0, 800, "figure", tag="svg"), block("p", 1050, 100)])
    f = spacing.composition(art, {})
    ids = {x.id: x.severity for x in f}
    assert ids["composition:page-1:figures"] == "soft"
    assert ids["composition:page-1:structure"] == "soft"
    assert ids["composition:page-2:structure"] == "info"          # final page
    assert ids["composition:page-1:shares"] == "info"


def test_workspace_classes_count_as_working_room():
    art = make([block("div.work", 0, 500, classes=["work"]), block("p", 1050, 100)])
    shares = spacing.page_shares(art, {"workspace_classes": ["work"]},
                                 spacing.PageModel(art).page(1))
    assert shares["working_room"] == pytest.approx(0.5) and shares["read_text"] == 0.0


def test_verdict_shape():
    art = make([block("p", 0, 100), block("p[2]", 1050, 100)])
    v, findings = spacing.verdict(art, {})
    assert v == "pass" and all(f.page_source == "dom_model" for f in findings)


# --- the real E0 pair --------------------------------------------------------

def _load(name):
    path = os.path.join(OUT, name, "geometry.json")
    if not os.path.exists(path):
        pytest.skip(f"{path} not rendered")
    return load_artifacts(path)


def _summary(name, art):
    model = spacing.PageModel(art)
    by = {}
    for f in spacing.run(art, {}):
        by.setdefault((f.page, f.id.split(":")[0]), []).append(f)
    print(f"\n{name}: PDF {art.page_count} pages, DOM model {len(model.pages)} pages")
    print(f"{'pg':>2} {'y-range':>10} brk {'ss':>4} {'prox':>5} {'mm':>5} {'tail':>5} "
          f"{'empty':>5}  composition")
    rank = {"hard": 2, "soft": 1, "info": 0}
    mark = {"hard": "!", "soft": "~", "info": " "}

    def one(page, kind, fmt="{:.2f}"):
        fs = by.get((page, kind), [])
        if not fs:
            return "-"
        worst = max(fs, key=lambda x: rank[x.severity])
        v = worst.value
        return (fmt.format(v) if v is not None else "") + mark[worst.severity]

    for p in model.pages:
        ss = by.get((p.index, "self_sufficiency"), [])
        ss_s = f"{len([f for f in ss if f.severity == 'hard'])}/{len(ss)}" if ss else "-"
        comp = [f for f in by.get((p.index, "composition"), []) if f.id.endswith(":shares")]
        comp_s = comp[0].message.split(": ", 1)[1] if comp else ""
        flag = "".join(f"~{f.id.split(':')[2]}" for f in by.get((p.index, "composition"), [])
                       if f.severity == "soft")
        print(f"{p.index:>2} {p.y_start:>5.0f}-{p.y_end:<4.0f} {int(p.ends_in_explicit_break):>3} "
              f"{ss_s:>4} {one(p.index, 'group_proximity'):>5} {one(p.index, 'macro_micro_sep'):>5} "
              f"{one(p.index, 'tail_slack', '{:.1f}'):>5} {one(p.index, 'largest_empty_rect'):>5}  {comp_s} {flag}")


@pytest.mark.parametrize("name,pages", [("fixed-worksheet", 5), ("fixed-key", 7)])
def test_fixed_references_have_no_hard_findings(name, pages):
    art = _load(name)
    v, findings = spacing.verdict(art, {})
    _summary(name, art)
    for f in soft(findings):
        print(f"  soft {f.id}: {f.message}")
    assert hard(findings) == [], [f.message for f in hard(findings)]
    assert v == "pass"
    assert art.page_count == pages
    assert abs(len(spacing.PageModel(art).pages) - pages) <= 1


@pytest.mark.parametrize("name", ["prefix-worksheet", "prefix-key"])
def test_prefix_states_fail_self_sufficiency(name):
    art = _load(name)
    v, findings = spacing.verdict(art, {})
    _summary(name, art)
    for f in findings:
        if f.severity != "info":
            print(f"  {f.severity} {f.id}: {f.message[:140]}")
    assert v == "fail"
    assert hard(findings, "self_sufficiency:")
    assert soft(findings, "tail_slack:")
    assert len(spacing.PageModel(art).pages) == art.page_count == 9

"""Frozen-geometry unit tests for `check --why` (report.compute_why)."""
from __future__ import annotations

import dataclasses

import pytest

from printfit import report as REP
from printfit.types import Finding, PageMetrics, RenderArtifacts

H = 1000.0


def rect(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def atom(sel, y, h, heading=None, heading_level=None, avoid=False, break_before=False, tag="div",
        group=None):
    return {"selector": sel, "tag": tag, "classes": [], "rows": [], "rect": rect(0.0, y, 600.0, h),
            "avoid": avoid, "fig_floor": h, "text": sel, "heading": heading,
            "heading_level": heading_level, "break_before": break_before, "figures": [],
            "spaces": [], "qa": False, "group": group}


def make_artifacts(atoms, inline_heights=(), figures=(), n_pages=2) -> RenderArtifacts:
    pages = [PageMetrics(index=i, fill_ratio=0.9, slack_px=50.0, ends_in_explicit_break=False,
                         is_final=(i == n_pages)) for i in range(1, n_pages + 1)]
    geom = {"atoms": list(atoms), "inline_heights": list(inline_heights),
            "figures": list(figures), "blocks": [], "headings": [], "page_map": {}}
    return RenderArtifacts(pdf_path="/dev/null", page_png_paths=[], dom_geometry=geom,
                           page_count=n_pages, page_content_h_px=H, page_content_w_px=600.0,
                           body_font_px=14.0, pages=pages, paper_h_px=1056.0)


def test_true_overflow_reports_negative_slack_as_overflow():
    # bottom edge of page 2 sits at top_margin + 2*H
    boundary = 2 * H
    atoms = [
        atom("h2.part2", boundary - 300, 40, heading="Part II — Long Answer", heading_level=2,
             break_before=True),
        atom("div.prob[3]", boundary - 105, 195, avoid=True),   # crosses the boundary
        atom("div.after", boundary + 100, 50),
    ]
    art = make_artifacts(atoms)
    finding = Finding(id="page_slack:page-2", severity="hard", message="x",
                      value=-29.0, threshold=12.0, page=2)
    why = REP.compute_why(art, [finding])
    assert len(why) == 1
    entry = why[0]
    assert entry["page"] == 2
    assert entry["over_px"] == 29.0          # true overflow = -slack, not threshold-slack
    assert entry["short_by_px"] is None
    assert "overflows by 29px" in entry["message"]
    assert entry["straddling"].startswith("div.prob[3]")
    assert "page-break-inside: avoid" in entry["straddling"]
    assert "Part II" in entry["preceded_by"]
    assert "forced break before: yes" in entry["preceded_by"]


def test_positive_slack_under_floor_reports_short_by_not_overflow():
    # page slack is +2px, under the 12px floor: never "overflows"
    boundary = 2 * H
    atoms = [atom("div.prob[3]", boundary - 50, 100, avoid=True)]
    art = make_artifacts(atoms)
    finding = Finding(id="page_slack:page-2", severity="hard", message="x",
                      value=10.0, threshold=12.0, page=2)
    why = REP.compute_why(art, [finding])
    entry = why[0]
    assert entry["over_px"] is None
    assert entry["short_by_px"] == 2.0
    assert "short of the 12px slack floor" in entry["message"]
    assert "overflow" not in entry["message"]


def test_no_straddling_atom_reports_reason():
    boundary = 2 * H
    atoms = [atom("div.a", boundary - 500, 100), atom("div.b", boundary + 10, 50)]
    art = make_artifacts(atoms)
    finding = Finding(id="page_slack:page-2", severity="hard", message="x",
                      value=0.0, threshold=12.0, page=2)
    why = REP.compute_why(art, [finding])
    assert why[0]["straddling"] is None
    assert "no atom crosses the boundary" in why[0]["no_straddle_reason"]


def test_soft_findings_excluded():
    art = make_artifacts([atom("div.a", 10, 20)])
    finding = Finding(id="page_slack:page-1", severity="info", message="x", value=50.0, threshold=12.0, page=1)
    assert REP.compute_why(art, [finding]) == []


def test_absorb_split_weighted_by_size_not_equal():
    boundary = 2 * H
    atoms = [atom("div.prob[3]", boundary - 105, 195, avoid=True)]
    # two boxes, very different heights: a proportional split gives them
    # different reductions; an equal split would give them the same
    inline = [
        {"classes": ["sp"], "rect": rect(0.0, boundary - 300, 600.0, 200.0), "height": "2.1in",
         "empty": True, "atom": 1},
        {"classes": ["sp"], "rect": rect(0.0, boundary - 90, 600.0, 40.0), "height": "0.4in",
         "empty": True, "atom": 2},
    ]
    art = make_artifacts(atoms, inline_heights=inline)
    finding = Finding(id="page_slack:page-2", severity="hard", message="x",
                      value=-29.0, threshold=12.0, page=2)
    entry = REP.compute_why(art, [finding])[0]
    absorb = entry["absorb_with"]
    assert len(absorb) == 2
    red1 = float(absorb[0].split("−")[1].rstrip("px)"))
    red2 = float(absorb[1].split("−")[1].rstrip("px)"))
    assert red1 != red2
    assert red1 > red2  # the 200px box carries more of the reduction than the 40px box


def test_absorb_omitted_when_rounded_reduction_is_zero():
    # A tiny reduction target split across a box rounds to 0px on display;
    # never print "1.7in->1.7in (-0px)".
    box = {"classes": ["sp"], "rect": rect(0.0, 40.0, 600.0, 122.0),
          "height": "1.7in", "empty": True, "atom": 1}
    art = make_artifacts([atom("div.a", 10, 20)], inline_heights=[box], n_pages=1)
    assert REP._absorb_candidates(art, [], 1, 0.3) == []


def test_absorb_uses_real_candidates_when_reduction_is_visible():
    box = {"classes": ["sp"], "rect": rect(0.0, 40.0, 600.0, 122.0),
          "height": "1.7in", "empty": True, "atom": 1}
    art = make_artifacts([atom("div.a", 10, 20)], inline_heights=[box], n_pages=1)
    absorb = REP._absorb_candidates(art, [], 1, 20.0)
    assert absorb and "sp[1] height" in absorb[0] and "-0px" not in absorb[0].replace("−", "-")


def test_no_candidates_fallback_names_the_actual_next_heading():
    boundary = 2 * H
    atoms = [
        atom("div.prob[3]", boundary - 105, 195, avoid=True),
        atom("h2.next", boundary + 20, 30, heading="Exit Ticket", heading_level=2),
    ]
    art = make_artifacts(atoms)  # no inline_heights, no figures
    finding = Finding(id="page_slack:page-2", severity="hard", message="x",
                      value=-29.0, threshold=12.0, page=2)
    entry = REP.compute_why(art, [finding])[0]
    assert len(entry["absorb_with"]) == 1
    assert "Exit Ticket" in entry["absorb_with"][0]
    assert "the next heading" not in entry["absorb_with"][0]


def test_underfull_entry_for_section_page_uses_page_before_landed():
    # "Part I" wanted page 1 but landed on page 2: the underfull page is 1,
    # not 2, and the entry must not look like an "overflows by 0px" page_slack.
    # The page-1/page-2 fill_ratio comes from the PDF (page data), not from
    # walking the DOM atoms -- that's the whole point of the fix.
    atoms = [
        atom("div.warmup", 90, 90),                        # ends early on page 1
        atom("div.mcblock", 1000 + 20, 870, avoid=True,     # the atom that didn't fit
             group="group:div.mcblock"),
    ]
    art = make_artifacts(atoms, n_pages=2)
    art.pages[0] = dataclasses.replace(art.pages[0], fill_ratio=0.18)
    finding = Finding(id="section_page:Part I", severity="hard", message="x",
                      value=2.0, threshold=1.0, page=2)
    why = REP.compute_why(art, [finding])
    assert len(why) == 1
    entry = why[0]
    assert entry["kind"] == "underfull"
    assert entry["page"] == 1
    assert entry["group"] == "div.mcblock"
    assert "ends early" in entry["message"]
    assert "18% full" in entry["message"]   # fill_ratio 0.18, from the PDF page data
    assert "div.mcblock" in entry["message"]
    assert "does not fit" in entry["cause"]
    assert "break-inside: avoid on div.mcblock" in entry["suggestion"]


def test_underfull_entry_geometrically_would_have_fit():
    # No keep-together group on the moved atom: the cause names the atom
    # itself and points at break-before rules, not a group.
    atoms = [
        atom("div.warmup", 900, 50),          # ends at 950, 50px remain
        atom("div.small", 1000 + 10, 20),      # next atom only needs 20px
    ]
    art = make_artifacts(atoms, n_pages=2)
    art.pages[0] = dataclasses.replace(art.pages[0], fill_ratio=0.95)
    finding = Finding(id="section_page:Part I", severity="hard", message="x",
                      value=2.0, threshold=1.0, page=2)
    entry = REP.compute_why(art, [finding])[0]
    assert entry["group"] is None
    assert "no keep-together group found; check break-before rules on div.small" in entry["cause"]


def test_underfull_headline_says_was_full_not_ends_early_when_page_is_full():
    # fill_ratio >= 0.80 means the page was genuinely full: "ends early" is
    # a lie when there was almost no room left.
    atoms = [
        atom("div.warmup", 900, 50),
        atom("div.prob[2]", 1000 + 10, 743, avoid=True),
    ]
    art = make_artifacts(atoms, n_pages=2)
    art.pages[0] = dataclasses.replace(art.pages[0], fill_ratio=0.93)
    finding = Finding(id="section_page:Part I", severity="hard", message="x",
                      value=2.0, threshold=1.0, page=2)
    entry = REP.compute_why(art, [finding])[0]
    assert "was full (93%)" in entry["message"]
    assert "ends early" not in entry["message"]
    assert "div.prob[2]" in entry["message"]
    assert "did not fit" in entry["message"]


def test_underfull_cause_names_unbreakable_atom_when_no_group_explains_move():
    # the moved atom itself is avoid=True and shares no group -- the cause
    # must point at the atom's own height, not a nonexistent group.
    atoms = [
        atom("div.warmup", 900, 50),
        atom("div.prob[2]", 1000 + 10, 743, avoid=True),
    ]
    art = make_artifacts(atoms, n_pages=2)
    art.pages[0] = dataclasses.replace(art.pages[0], fill_ratio=0.93)
    finding = Finding(id="section_page:Part I", severity="hard", message="x",
                      value=2.0, threshold=1.0, page=2)
    entry = REP.compute_why(art, [finding])[0]
    assert entry["group"] is None
    assert "div.prob[2] is itself unbreakable" in entry["cause"]
    assert "page-break-inside: avoid" in entry["cause"]
    assert "h 743px" in entry["cause"]
    assert "needs more than" in entry["cause"]
    assert "no keep-together group found" not in entry["cause"]


def test_underfull_reports_group_span_px_key_including_heading():
    atoms = [
        atom("div.warmup", 90, 90),
        atom("div.mcblock", 1000 + 20, 870, avoid=True, group="group:div.mcblock"),
    ]
    art = make_artifacts(atoms, n_pages=2)
    art.pages[0] = dataclasses.replace(art.pages[0], fill_ratio=0.18)
    finding = Finding(id="section_page:Part I", severity="hard", message="x",
                      value=2.0, threshold=1.0, page=2)
    entry = REP.compute_why(art, [finding])[0]
    assert "group_span_px" in entry
    assert "group_h" not in entry
    assert entry["group_span_px"] == 870.0
    assert "spans 870px incl. heading" in entry["cause"]


def test_page_of_and_page_end_y_agree_on_straddling_boundary_atom():
    # An atom placed exactly at the page boundary must be attributed to the
    # same page whether reached via the page_slack path (_page_slack_entry)
    # or the underfull path (_underfull_entry) -- both now share
    # _page_of/_page_end_y instead of disagreeing on a top-margin offset.
    H = 1000.0
    boundary_atom_y = H  # exactly at the page-1/page-2 boundary
    assert REP._page_of(boundary_atom_y, H) == 2
    assert REP._page_end_y(1, H) == boundary_atom_y
    # an atom straddling the boundary (y < boundary < y + h) is found by
    # _page_slack_entry using the same boundary_y = _page_end_y(page, H)
    atoms = [atom("div.prob[3]", H - 50, 100, avoid=True)]  # spans 950-1050
    art = make_artifacts(atoms, n_pages=2)
    finding = Finding(id="page_slack:page-1", severity="hard", message="x",
                      value=0.0, threshold=12.0, page=1)
    entry = REP.compute_why(art, [finding])[0]
    assert entry["straddling"] is not None
    assert entry["straddling"].startswith("div.prob[3]")


def _load_fixture_artifacts():
    import json
    import os
    fixdir = os.path.join(os.path.dirname(__file__), "fixtures", "t2-stuck")
    with open(os.path.join(fixdir, "geometry.json"), encoding="utf-8") as fh:
        g = json.load(fh)
    pages = [PageMetrics(**p) for p in g["pages"]]
    fields = {f.name for f in dataclasses.fields(RenderArtifacts)}
    kwargs = {k: v for k, v in g.items() if k in fields and k != "pages"}
    return RenderArtifacts(pages=pages, **kwargs)


def _load_fixture_report():
    import json
    import os
    fixdir = os.path.join(os.path.dirname(__file__), "fixtures", "t2-stuck")
    with open(os.path.join(fixdir, "report.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_why_diagnoses_underfull_page_via_keep_together_group():
    """Frozen against the synthetic t2-stuck fixture: page 1 ends at
    17% full because Chrome moved the "Part I" heading (inside div.mcblock,
    a break-inside:avoid group) to page 2. The diagnosis must come from the
    PDF page data and the atom's keep-together group, not the DOM flow."""
    art = _load_fixture_artifacts()
    rep_js = _load_fixture_report()
    findings = [REP.finding_from_dict(f) for f in rep_js["findings"] if f["id"] == "section_page:Part I"]
    why = REP.compute_why(art, findings)
    entry = next(e for e in why if e["page"] == 1)
    assert entry["kind"] == "underfull"
    assert entry["moved_atom"].startswith("h2")
    assert entry["group"] == "div.mcblock"


def test_render_why_text_includes_absorb_and_notes():
    boundary = 2 * H
    atoms = [atom("div.prob[3]", boundary - 105, 195, avoid=True)]
    inline = [{"classes": ["sp"], "rect": rect(0.0, boundary - 90, 600.0, 122.0), "height": "1.7in",
              "empty": True, "atom": 1}]
    art = make_artifacts(atoms, inline_heights=inline)
    finding = Finding(id="page_slack:page-2", severity="hard", message="x", value=-29.0, threshold=12.0, page=2)
    why = REP.compute_why(art, [finding])
    text = "\n".join(REP.render_why_text(why, ["note: figure knobs skipped: 2 svg figures in the DOM but 3 in the source"]))
    assert "page 2 overflows by 29px" in text
    assert "absorb with" in text
    assert "figure knobs skipped" in text


def _with_text(art, page_text):
    art.dom_geometry["pdf"] = {"page_text": page_text}
    return art


def test_zero_slack_with_a_breakable_box_running_past_the_page_is_a_split():
    # page 2 starts EARLY (y 900, not 1000): the naive N*H boundary would miss it
    atoms = [atom("div.intro", 0, 850), atom("div.panel", 900, 400), atom("div.part3", 1400, 300),
             atom("div.panel2", 1450, 700)]
    art = _with_text(make_artifacts(atoms, n_pages=3),
                     ["div.intro", "div.panel div.part3 div.panel2", "rest of the panel"])
    f = Finding(id="page_slack:page-2", severity="hard", message="x", value=-0.2, threshold=12.0, page=2)
    entry = REP.compute_why(art, [f])[0]
    assert entry["kind"] == "split"
    assert "div.panel2" in entry["message"] and "~250px" in entry["message"]   # 1450+700 - (900+1000)
    assert any("break-inside: avoid" in o for o in entry["options"])
    text = "\n".join(REP.render_why_text([entry]))
    assert "option: keep it whole on page 2" in text


def test_zero_slack_on_an_unbreakable_box_stays_an_overflow_entry():
    atoms = [atom("div.a", 0, 950), atom("div.b", 960, 200, avoid=True)]
    art = _with_text(make_artifacts(atoms), ["div.a", "div.b"])
    f = Finding(id="page_slack:page-1", severity="hard", message="x", value=0.5, threshold=12.0, page=1)
    assert REP.compute_why(art, [f])[0]["kind"] != "split"


def test_blank_page_names_the_inkless_boxes_that_spilled():
    space = dict(atom("div.sp", 960, 120), text="")
    atoms = [atom("div.q7", 0, 960), space]
    art = _with_text(make_artifacts(atoms), ["div.q7", ""])
    f = Finding(id="blank_page:page-2", severity="hard", message="x", value=0.0, page=2)
    entry = REP.compute_why(art, [f])[0]
    assert entry["kind"] == "blank" and "div.sp" in entry["message"]
    assert entry["need_px"] == 80                  # 960 + 120 - 1000: only the part past page 1


def test_blank_page_is_a_hard_finding():
    from printfit.checks import page_slack
    art = make_artifacts([atom("div.a", 0, 900)], n_pages=3)
    art.pages[1] = dataclasses.replace(art.pages[1], fill_ratio=0.0)
    ids = {x.id for x in page_slack.run(art, {}) if x.failed}
    assert ids == {"blank_page:page-2"}


def _page_doc(tmp_path, body, css=""):
    p = tmp_path / "doc.html"
    p.write_text("<!doctype html><html><head><style>@page{size:letter;margin:.5in}"
                 f"body{{margin:0;font:12pt Georgia}}{css}</style></head><body>{body}</body></html>")
    return str(p)


@pytest.mark.browser
def test_chrome_split_panel_is_diagnosed_as_split(tmp_path):
    from printfit import api
    paras = "".join(f"<p>Panel line {i}, long enough to read as a sentence of prose.</p>" for i in range(30))
    doc = _page_doc(tmp_path, f'<div style="height:6in"></div><div class="panel">{paras}</div><p>after</p>',
                    ".panel{border:1px solid #333;padding:6px}")
    rep = api.check(doc, None, str(tmp_path / "out"), no_diff=True)
    entry = next(e for e in rep.why if e["page"] == 1)
    assert entry["kind"] == "split" and "div.panel" in entry["message"]


@pytest.mark.browser
def test_chrome_blank_page_from_an_empty_box_fails_and_is_explained(tmp_path):
    from printfit import api
    doc = _page_doc(tmp_path, '<p>Question 7c. Explain.</p><div style="height:9.5in"></div>')
    rep = api.check(doc, None, str(tmp_path / "out"), no_diff=True)
    assert "blank_page:page-2" in {f.id for f in rep.findings if f.failed}
    assert any(e["kind"] == "blank" for e in rep.why)

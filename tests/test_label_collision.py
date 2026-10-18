import pytest

from printfit import marks
from printfit.checks import label_collision as LC
from printfit.render import load_artifacts

NOPROF = {"roles": {}, "mark_roles": {}}


@pytest.fixture(scope="module")
def labels():
    return load_artifacts("tests/fixtures/visual/labels.geometry.json")


def hits_in(art, cls, prof=NOPROF):
    return [h for h in LC.hits(art, prof) if h["figure"] == f"svg.{cls}"]


@pytest.mark.parametrize("cls", ["f-tt-overlap", "f-line-through", "f-rotated", "f-subscript", "f-head", "f-role-axis"])
def test_collisions_found(labels, cls):
    assert len(hits_in(labels, cls)) == 1


@pytest.mark.parametrize("cls", ["f-tt-clear", "f-line-clear", "f-ok", "f-grid", "f-tick"])
def test_no_false_alarm(labels, cls):
    assert hits_in(labels, cls) == []


def test_head_hit_names_the_arrowhead(labels):
    assert "arrowhead" in hits_in(labels, "f-head")[0]["message"]


def test_fix_hint_has_direction_and_viewbox_units(labels):
    fix = hits_in(labels, "f-line-through")[0]["fix"]
    assert ("up" in fix or "down" in fix) and "viewBox units" in fix


def test_profile_mark_roles_exempt_a_class(labels):
    prof = {"roles": {}, "mark_roles": {"vec": "gridline"}}
    assert hits_in(labels, "f-line-through", prof) == []


def test_run_is_hard_after_promotion(labels):
    f = LC.run(labels, NOPROF)
    assert f and all(x.severity == marks.severity_for(LC.NAME) == "hard" for x in f)
    assert all(x.id.startswith("label_collision:svg.") for x in f)


def test_missing_figure_marks_is_a_noop():
    old = load_artifacts("tests/fixtures/geometry-fixed-worksheet.json")
    assert LC.run(old, NOPROF) == []


def test_stroke_role_shape_defaults():
    fig = {"rect": [0, 0, 400, 120], "heads": []}
    mk = lambda pts, **kw: {"id": "s0", "classes": [], "data_role": None, "pts": pts, **kw}
    assert marks.stroke_role(mk([[10, 50], [390, 50]]), fig, NOPROF) == "gridline"
    assert marks.stroke_role(mk([[100, 50], [100, 56]]), fig, NOPROF) == "tick"
    assert marks.stroke_role(mk([[20, 50], [150, 50]]), fig, NOPROF) == "mark"
    assert marks.stroke_role(mk([[0, 0], [50, 40]]), fig, NOPROF) == "mark"
    fig_h = {"rect": [0, 0, 400, 120], "heads": [{"stroke_id": "s0"}]}
    assert marks.stroke_role(mk([[10, 50], [390, 50]]), fig_h, NOPROF) == "mark"


def test_stroke_role_known_classes_beat_the_shape_default():
    fig = {"rect": [0, 0, 400, 120], "heads": []}
    mk = lambda cls, pts: {"id": "s0", "classes": cls, "data_role": None, "pts": pts}
    short = [[20, 50], [150, 50]]          # 33% span: the shape default says "mark"
    assert marks.stroke_role(mk(["gl"], short), fig, NOPROF) == "gridline"
    assert marks.stroke_role(mk(["mn"], short), fig, NOPROF) == "gridline"
    assert marks.stroke_role(mk(["ax"], [[10, 50], [390, 50]]), fig, NOPROF) == "axis"
    assert marks.stroke_role(mk(["gl"], short), fig, {"mark_roles": {"gl": "mark"}}) == "mark"


def test_label_on_an_axis_is_flagged_on_a_gridline_is_not():
    import copy
    base = load_artifacts("tests/fixtures/visual/labels.geometry.json")
    fig = next(f for f in base.dom_geometry["figure_marks"] if f["figure"] == "svg.f-line-through")
    for cls, expect in ((["ax"], 1), (["gl"], 0)):
        art = copy.deepcopy(base)
        f = next(f for f in art.dom_geometry["figure_marks"] if f["figure"] == fig["figure"])
        for s in f["strokes"]:
            s["classes"] = cls
        assert len(hits_in(art, "f-line-through")) == expect, cls


def _shift(poly, dx, dy):
    return [(x + dx, y + dy) for x, y in poly]


def test_first_suggested_move_clears_every_hit(labels):
    from printfit import geom2d as G
    hs = LC.hits(labels, NOPROF)
    assert hs
    for h in hs:
        box, other = h["polys"]
        dx, dy = h["move_px"]
        moved = _shift(box, dx, dy)
        if h["message"].split(" overlaps ")[1].startswith("label '"):
            o = G.sat_overlap(moved, other)
            assert o is None or o[0] < LC.TEXT_OVERLAP_PX, h["fid"]
        else:
            assert G.sat_overlap(G.inset_quad(moved, LC.TEXT_INSET_PX), other) is None, h["fid"]


def test_line_through_first_move_is_hand_computed(labels):
    # inset box y 312..326, stroke rect y 317.8..320.2: clearing takes
    # 326 - 317.8 = 8.2 up or 320.2 - 312 = 8.2 down, plus CLEARANCE_PX = 9.2
    h = hits_in(labels, "f-line-through")[0]
    dx, dy = h["move_px"]
    assert dx == pytest.approx(0) and abs(dy) == pytest.approx(9.2)
    assert "9.2px up or 9.2px down" in h["fix"] or "9.2px down or 9.2px up" in h["fix"]
    assert "(9.2 or 9.2 viewBox units)" in h["fix"]

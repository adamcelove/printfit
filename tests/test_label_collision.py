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


@pytest.mark.parametrize("cls", ["f-tt-overlap", "f-line-through", "f-rotated", "f-subscript", "f-head"])
def test_collisions_found(labels, cls):
    assert len(hits_in(labels, cls)) == 1


@pytest.mark.parametrize("cls", ["f-tt-clear", "f-line-clear", "f-ok", "f-grid", "f-role-axis", "f-tick"])
def test_no_false_alarm(labels, cls):
    assert hits_in(labels, cls) == []


def test_head_hit_names_the_arrowhead(labels):
    assert "arrowhead" in hits_in(labels, "f-head")[0]["message"]


def test_fix_hint_has_direction_and_viewbox_units(labels):
    fix = hits_in(labels, "f-line-through")[0]["fix"]
    assert ("up" in fix or "down" in fix) and "viewBox units" in fix


def test_profile_mark_roles_exempt_a_class(labels):
    prof = {"roles": {}, "mark_roles": {"vec": "axis"}}
    assert hits_in(labels, "f-line-through", prof) == []


def test_run_is_soft_until_promoted(labels):
    f = LC.run(labels, NOPROF)
    assert f and all(x.severity == marks.severity_for(LC.NAME) == "soft" for x in f)
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

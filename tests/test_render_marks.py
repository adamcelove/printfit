"""figure_marks capture: hand-computed expectations on the visual fixtures."""
import math

import pytest

from printfit import render as R

FIX = "tests/fixtures/visual"


@pytest.fixture(scope="module")
def arrows(tmp_path_factory):
    return R.render(f"{FIX}/arrows.html", str(tmp_path_factory.mktemp("arrows")))


@pytest.fixture(scope="module")
def labels(tmp_path_factory):
    return R.render(f"{FIX}/labels.html", str(tmp_path_factory.mktemp("labels")))


def fig(art, cls):
    return next(f for f in art.dom_geometry["figure_marks"] if f["figure"] == f"svg.{cls}")


def head(art, cls):
    f = fig(art, cls)
    assert len(f["heads"]) == 1
    return f["heads"][0], f


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


@pytest.mark.browser
def test_one_entry_per_visible_svg(arrows, labels):
    assert len(arrows.dom_geometry["figure_marks"]) == 8
    assert len(labels.dom_geometry["figure_marks"]) == 11


@pytest.mark.browser
def test_ref0_head_geometry(arrows):
    h, f = head(arrows, "a-ok-ref0")
    assert h["marker_id"] == "ah"
    assert h["length"] == pytest.approx(10, abs=0.15)
    assert h["base_halfwidth"] == pytest.approx(4, abs=0.15)
    assert h["dir"][0] == pytest.approx(1, abs=1e-3) and h["dir"][1] == pytest.approx(0, abs=1e-3)
    assert dist(h["shaft_end"], h["base_mid"]) == pytest.approx(0, abs=0.1)
    assert h["tip_user"] == pytest.approx([210, 30], abs=0.1)
    assert f["user_per_px"] == pytest.approx(1, abs=1e-3)


@pytest.mark.browser
def test_ref8_shaft_runs_eight_into_head(arrows):
    h, _ = head(arrows, "a-peek-ref8")
    assert h["ref_x"] == pytest.approx(8)
    assert h["marker_base_x"] == pytest.approx(0)
    assert h["marker_px_per_unit"] == pytest.approx(1, abs=1e-3)
    assert dist(h["shaft_end"], h["base_mid"]) == pytest.approx(8, abs=0.1)
    assert h["tip_user"] == pytest.approx([201, 30], abs=0.1)


@pytest.mark.browser
def test_strokewidth_units_scale_the_head(arrows):
    h, _ = head(arrows, "a-strokewidth-units")
    assert h["length"] == pytest.approx(8, abs=0.15)
    assert h["base_halfwidth"] == pytest.approx(3, abs=0.15)


@pytest.mark.browser
def test_scaled_svg(arrows):
    h, f = head(arrows, "a-scaled")
    assert f["user_per_px"] == pytest.approx(0.5, abs=1e-3)
    assert h["length"] == pytest.approx(20, abs=0.2)
    assert h["tip_user"] == pytest.approx([110, 15], abs=0.1)
    s = f["strokes"][0]
    assert s["width_px"] == pytest.approx(2.4, abs=0.01)
    assert [c for pt in s["pts_user"] for c in pt] == pytest.approx([10, 15, 100, 15], abs=0.01)


@pytest.mark.browser
def test_dashed_and_cap_flags(arrows):
    assert fig(arrows, "a-dashed-peek")["strokes"][0]["dashed"] is True
    assert fig(arrows, "a-ok-ref0")["strokes"][0]["dashed"] is False
    assert fig(arrows, "a-round-cap")["strokes"][0]["cap"] == "round"


@pytest.mark.browser
def test_rotated_text_box_is_rotated(labels):
    t = fig(labels, "f-rotated")["texts"][0]
    xs = [p[0] for p in t["box"]]
    ys = [p[1] for p in t["box"]]
    assert max(ys) - min(ys) > max(xs) - min(xs)  # "velocity" runs vertically


@pytest.mark.browser
def test_subscript_extends_text_box(labels):
    sub = fig(labels, "f-subscript")["texts"][0]
    plain = fig(labels, "f-line-through")["texts"][0]
    h = lambda t: max(p[1] for p in t["box"]) - min(p[1] for p in t["box"])
    assert h(sub) > h(plain) + 4


@pytest.mark.browser
def test_ok_and_role_attributes(labels):
    assert fig(labels, "f-ok")["texts"][0]["ok"] is True
    assert fig(labels, "f-role-axis")["strokes"][0]["data_role"] == "axis"


@pytest.mark.browser
def test_existing_figures_unchanged(arrows):
    sels = [f["selector"] for f in arrows.dom_geometry["figures"]]
    assert sels == [m["figure"] for m in arrows.dom_geometry["figure_marks"]]


@pytest.mark.browser
def test_path_with_hash_and_spaces_renders_the_real_file(tmp_path, labels):
    # "file://" + path cut the URL at "#": Chrome loaded an error page and every gate passed on it.
    import shutil
    doc = tmp_path / "Forces Quiz #1 (copy).html"
    shutil.copy(f"{FIX}/labels.html", doc)
    art = R.render(str(doc), str(tmp_path / "out"))
    assert len(art.dom_geometry["figure_marks"]) == len(labels.dom_geometry["figure_marks"])

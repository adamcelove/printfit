import pytest

from printfit.checks import arrow_shaft as AS
from printfit.render import load_artifacts

NOPROF = {"roles": {}, "mark_roles": {}}


@pytest.fixture(scope="module")
def arrows():
    return load_artifacts("tests/fixtures/visual/arrows.geometry.json")


def hits_in(art, cls):
    return [h for h in AS.hits(art, NOPROF) if h["figure"] == f"svg.{cls}"]


@pytest.mark.parametrize("cls", ["a-ok-ref0", "a-fixed-ref8", "a-strokewidth-units", "a-round-cap", "a-scaled"])
def test_clean_arrows_pass(arrows, cls):
    assert hits_in(arrows, cls) == []


def test_ref8_peeks(arrows):
    (h,) = hits_in(arrows, "a-peek-ref8")
    assert h["kind"] == "peek"
    assert h["value"] == pytest.approx(1.9, abs=0.15)    # end at 8, zone ends near 6.1


def test_ref8_fix_moves_refx_and_keeps_tip(arrows):
    (h,) = hits_in(arrows, "a-peek-ref8")
    assert "#rA" in h["fix"] and "refX" in h["fix"] and "0.50" in h["fix"]
    assert "(192.5, 30.0)" in h["fix"]                   # tip 201 minus (9 - 0.5)
    assert "(201.0, 30.0)" in h["fix"]


def test_dashed_peeks_too(arrows):
    (h,) = hits_in(arrows, "a-dashed-peek")
    assert h["kind"] == "peek"


def test_gap(arrows):
    (h,) = hits_in(arrows, "a-gap")
    assert h["kind"] == "gap"
    assert h["value"] == pytest.approx(2.0, abs=0.1)
    assert "(202.5, 30.0)" in h["fix"]                   # tip 212 minus (10 - 0.5)


def test_run_soft_until_promoted(arrows):
    f = AS.run(arrows, NOPROF)
    assert {x.id.split(":")[0] for x in f} == {"arrow_shaft"}
    assert all(x.severity == "soft" for x in f)


def test_missing_figure_marks_is_a_noop():
    assert AS.run(load_artifacts("tests/fixtures/geometry-fixed-worksheet.json"), NOPROF) == []

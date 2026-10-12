import pytest

from printfit.api import check

FIX = "tests/fixtures/synthetic"
PROF = "profiles/motion-graphs.yaml"


@pytest.mark.browser
@pytest.mark.parametrize("kind", ["worksheet"])
def test_prefix_fails_on_the_two_regressions(kind, tmp_path):
    rep = check(f"{FIX}/prefix-{kind}.html", PROF, str(tmp_path))
    ids = {f.id.split(":")[0] for f in rep.findings if f.failed}
    assert "auto_height" in ids
    assert "text_scale" in ids
    assert rep.artifacts.page_count == 7
    assert rep.verdict == "fail"


@pytest.mark.browser
@pytest.mark.parametrize("kind,pages", [("worksheet", 5)])
def test_fixed_passes_every_hard_gate(kind, pages, tmp_path):
    rep = check(f"{FIX}/fixed-{kind}.html", PROF, str(tmp_path))
    assert [f for f in rep.findings if f.failed] == []
    assert rep.artifacts.page_count == pages
    assert rep.verdict == "pass"
    assert any(f.id == "aspect_ratio:svg.grid.g-nl" and f.severity == "info" for f in rep.findings)

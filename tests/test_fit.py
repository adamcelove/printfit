import pytest

from printfit import fit as F, profile as P, render as R
from printfit.checks import structural

FIX = "tests/fixtures/synthetic"
U1 = P.load("profiles/motion-graphs.yaml")


def toy_atoms(heights, knob=None):
    atoms = []
    for i, h in enumerate(heights):
        coeffs = {knob.id: 1.0} if (knob and i == 1) else {}
        atoms.append(F.Atom(idx=i, selector=f"a{i}", y=sum(heights[:i]), h=h, pitch=h, coeffs=coeffs,
                            break_before=False, heading=None, heading_level=None, h2_index=None))
    return atoms


def test_cpsat_assigns_pages_in_order():
    atoms = toy_atoms([400, 400, 400])
    sol = F.solve(atoms, [], 1000.0, {}, max_pages=3)
    assert sol.status in ("optimal", "feasible")
    assert sol.page_count == 2
    assert sol.pages == [1, 1, 2]


def test_cpsat_shrinks_a_knob_to_save_a_page():
    k = F.Knob(id="ws:1", kind="ws", current_px=300, lo=100, hi=400)
    atoms = toy_atoms([400, 300, 400], knob=k)
    sol = F.solve(atoms, [k], 1000.0, {"pages": 1}, max_pages=2)
    assert sol.status in ("optimal", "feasible")
    assert sol.page_count == 1
    assert sol.knobs["ws:1"] <= 188


def test_cpsat_reports_core_when_unsatisfiable():
    atoms = toy_atoms([600, 600])
    sol = F.solve(atoms, [], 1000.0, {"pages": 1}, max_pages=2)
    assert sol.status == "infeasible"
    assert "page_cap" in sol.core


def test_apply_preserves_content(tmp_path):
    src = open(f"{FIX}/fixed-worksheet.html").read()
    art = R.load_artifacts("tests/fixtures/geometry-fixed-worksheet.json")
    knobs, notes = F.discover_knobs(art, U1, src)
    assert any(k.kind == "fig" for k in knobs) and any(k.kind == "ws" for k in knobs)
    vals = {k.id: (k.lo + k.hi) // 2 if k.kind != "brk" else 0 for k in knobs}
    out = F.apply(src, knobs, vals, {"sp"})
    p = tmp_path / "fitted.html"
    p.write_text(out)
    before = structural.fingerprint(f"{FIX}/fixed-worksheet.html")
    assert structural.compare(before, structural.fingerprint(str(p))) == []
    assert 'data-printfit="f1"' in out and 'id="printfit-fit"' in out


@pytest.mark.browser
def test_fit_prefix_to_five_pages(tmp_path):
    res = F.fit(f"{FIX}/prefix-worksheet.html", "profiles/motion-graphs.yaml", str(tmp_path), max_iter=3)
    assert res.page_count_before == 7
    assert res.page_count_after == 5
    assert res.verdict == "pass"
    assert res.hard_after == []

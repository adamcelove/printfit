from printfit import report as REP
from printfit.api import check
from printfit.render import load_artifacts
from printfit.types import Finding, Report


def test_json_and_diff(tmp_path):
    fixed = load_artifacts("tests/fixtures/geometry-fixed-worksheet.json")
    prefix = load_artifacts("tests/fixtures/geometry-prefix-worksheet.json")
    FIX = "tests/fixtures/synthetic"
    rf = check(f"{FIX}/fixed-worksheet.html", "profiles/motion-graphs.yaml", artifacts=fixed)
    rp = check(f"{FIX}/prefix-worksheet.html", "profiles/motion-graphs.yaml", artifacts=prefix)
    jf, jp = REP.render_json(rf), REP.render_json(rp)
    assert jf["schema"] == 1 and jf["verdict"] == "pass" and jp["verdict"] == "fail"
    assert jp["hard_failed"] >= 15
    d = REP.diff_against(jp, jf)
    assert any(i.startswith("auto_height") for i in d["fixed"])
    assert not d["regressed"]
    d2 = REP.diff_against(jf, jp)
    assert any(i.startswith("text_scale") for i in d2["new"] + d2["regressed"])


def test_value_direction():
    prev = {"findings": [{"id": "x:a", "severity": "soft", "value": 0.49, "threshold": 0.30}]}
    cur = {"findings": [{"id": "x:a", "severity": "soft", "value": 0.35, "threshold": 0.30}]}
    gone = {"findings": []}
    assert REP.diff_against(prev, cur)["changed"] == ["x:a"]
    assert REP.diff_against(cur, prev)["regressed"] == ["x:a"]
    assert REP.diff_against(prev, gone)["fixed"] == ["x:a"]
    assert REP.diff_against(gone, prev)["new"] == ["x:a"]


def test_text_report_mentions_pages():
    fixed = load_artifacts("tests/fixtures/geometry-fixed-worksheet.json")
    rf = check("tests/fixtures/synthetic/fixed-worksheet.html",
               "profiles/motion-graphs.yaml", artifacts=fixed)
    txt = REP.render_text(rf)
    assert "page 1" in txt and "verdict: pass" in txt


def test_diff_only_text_hides_unchanged_and_shows_changed():
    prev_js = {"doc": "doc.html", "findings": [
        {"id": "soft:unchanged", "severity": "soft", "message": "still here", "value": 0.5, "threshold": 0.3},
        {"id": "soft:got-worse", "severity": "soft", "message": "worse now", "value": 0.32, "threshold": 0.30},
        {"id": "hard:always", "severity": "hard", "message": "always shown", "value": 1.0, "threshold": 0.0},
    ]}
    findings = [
        Finding(id="soft:unchanged", severity="soft", message="still here", value=0.5, threshold=0.3),
        Finding(id="soft:got-worse", severity="soft", message="worse now", value=0.45, threshold=0.30),
        Finding(id="hard:always", severity="hard", message="always shown", value=1.0, threshold=0.0),
    ]
    rep = Report(doc="doc.html", profile=None, verdict="fail", findings=findings, artifacts=None)
    cur_js = REP.render_json(rep)
    diff = REP.diff_against(prev_js, cur_js)
    txt = REP.render_text(rep, diff=diff, prev=prev_js)
    assert "soft:unchanged" not in txt
    assert "still here" not in txt
    assert "soft:got-worse" in txt
    assert "0.32 → 0.45" in txt
    assert "hard:always" in txt
    assert "unchanged: 1 soft, 0 info (hidden; --full to show)" in txt
    full_txt = REP.render_text(rep, diff=diff, full=True, prev=prev_js)
    assert "soft:unchanged" in full_txt

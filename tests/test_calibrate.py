import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("calibrate", "scripts/calibrate.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def test_corpus_skips_keys_and_non_printables(tmp_path):
    (tmp_path / "ws.html").write_text("<style>@page{}</style><svg></svg>")
    (tmp_path / "ws-key.html").write_text("<style>@page{}</style>")
    (tmp_path / "answer-key.html").write_text("<style>@page{}</style>")
    (tmp_path / "screen.html").write_text("<p>no print css</p>")
    assert [p.name for p in C.corpus([str(tmp_path)], reports=str(tmp_path / "none"))] == ["ws.html"]


def test_slug_is_stable_and_unique(tmp_path):
    a, b = tmp_path / "x" / "w.html", tmp_path / "y" / "w.html"
    assert C.slug(a) == C.slug(a) and C.slug(a) != C.slug(b)


def test_sample_caps_per_gate():
    items = [{"gate": "label_collision", "n": i} for i in range(100)] + [{"gate": "arrow_shaft", "n": 0}]
    s = C.sample(items)
    assert sum(1 for i in s if i["gate"] == "label_collision") == C.SAMPLE
    assert sum(1 for i in s if i["gate"] == "arrow_shaft") == 1
    assert C.sample(items) == s                       # seeded


def test_region_pads_and_clamps():
    x0, y0, x1, y1 = C.region([[(10, 10), (20, 10), (20, 20)]], page_w=100)
    assert (x0, y0) == (0, 0) and x1 == 20 + C.PAD_PX and y1 == 20 + C.PAD_PX


def test_score():
    labels = {"d|a": "real", "d|b": "false", "d|c": "real"}
    found = {"d|a", "d|b"}
    s = C.score(labels, found)
    assert s == {"real": 2, "real_caught": 1, "false": 1, "false_flagged": 1, "meets_bar": False}


def test_review_page_has_labels_and_copy(tmp_path):
    items = [{"gate": "label_collision", "slug": "s", "fid": "label_collision:svg.a:t0",
              "doc": "/x/w.html", "message": "m", "fix": "f", "png": ""}]
    html = C.review_html(items)
    assert 'name="s|label_collision:svg.a:t0"' in html and 'value="real"' in html and "Copy results" in html


def _print_html(path, svg=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<style>@page{}</style>" + ("<svg></svg>" if svg else "<p>x</p>"))
    return path


def test_corpus_spec_sources(tmp_path):
    root, other, reports = tmp_path / "root", tmp_path / "other", tmp_path / "reports"
    _print_html(root / "svg.html", svg=True)
    _print_html(root / "plain.html")                       # no svg, no builder: dropped
    _print_html(root / "built.html")
    (root / "build.py").write_text("open('built.html', 'w')")
    ext = _print_html(other / "ext.html")                  # only named by a report
    key = _print_html(other / "ext-key.html")
    dup = root / "svg.html"
    for name, doc in [("a", {"path": str(ext)}), ("b", str(dup)), ("c", str(key)),
                      ("d", str(other / "missing.html"))]:
        (reports / name).mkdir(parents=True)
        (reports / name / "report.json").write_text(json.dumps({"doc": doc}))
    got = [p.name for p in C.corpus([str(root)], reports=str(reports))]
    assert sorted(got) == ["built.html", "ext.html", "svg.html"]
    assert len(got) == len(set(got))


def test_review_page_persists_labels_and_legend():
    items = [{"gate": g, "slug": "s", "fid": f"{g}:1", "doc": "/x/w.html", "message": "m",
              "fix": "f", "png": "AAAA" if g != "duplicate_content" else ""}
             for g in ("label_collision", "arrow_shaft", "duplicate_content")]
    html = C.review_html(items)
    assert "localStorage" in html and "addEventListener('change'" in html
    assert "Red: the flagged label. Blue: what it overlaps." in html
    assert "Red: the arrowhead. Blue: the shaft." in html
    assert "Red outline: the flagged element" not in html
    assert html.count('class="legend"') == 2
    assert ".catch(" in html
    assert C.review_html(items[:1]) != html                 # storage key follows the card set


def test_crop_spec_zooms_arrow_heads():
    head, shaft = [(100, 100), (110, 100), (110, 110)], [(0, 104), (100, 104), (100, 106)]
    reg, scale = C.crop_spec({"gate": "arrow_shaft", "polys": [head, shaft]}, 500)
    assert scale == 4 and reg == (88, 88, 122, 122)
    reg, scale = C.crop_spec({"gate": "label_collision", "polys": [head, shaft]}, 500)
    assert scale == 2 and reg[0] == 0


def test_duplicate_needs_a_label_to_pass():
    assert not C.dup_meets_bar({"real": 0, "real_caught": 0, "false": 0, "false_flagged": 0})
    assert C.dup_meets_bar({"real": 1, "real_caught": 1, "false": 0, "false_flagged": 0})
    assert not C.dup_meets_bar({"real": 1, "real_caught": 0, "false": 0, "false_flagged": 0})
    assert not C.dup_meets_bar({"real": 1, "real_caught": 1, "false": 1, "false_flagged": 1})

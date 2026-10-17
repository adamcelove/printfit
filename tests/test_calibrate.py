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
    assert [p.name for p in C.corpus([str(tmp_path)])] == ["ws.html"]


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

"""api.check's structural fingerprint compare: same-document guard and
--no-diff skip (round-2 fix items 2)."""
from __future__ import annotations

import json
import os

from printfit import api
from printfit.types import PageMetrics, RenderArtifacts

FIXTURE_HTML = os.path.join(os.path.dirname(__file__), "fixtures", "t2-stuck", "t2-stuck.html")
GEOMETRY = os.path.join(os.path.dirname(__file__), "fixtures", "t2-stuck", "geometry.json")


def _load_artifacts() -> RenderArtifacts:
    with open(GEOMETRY, encoding="utf-8") as fh:
        g = json.load(fh)
    pages = [PageMetrics(**p) for p in g["pages"]]
    fields = {f.name for f in __import__("dataclasses").fields(RenderArtifacts)}
    kwargs = {k: v for k, v in g.items() if k in fields and k != "pages"}
    return RenderArtifacts(pages=pages, **kwargs)


def _write_prev(out_dir, doc_basename, fingerprint):
    with open(os.path.join(out_dir, "report.prev.json"), "w", encoding="utf-8") as fh:
        json.dump({"doc": doc_basename, "fingerprint": fingerprint}, fh)


def test_fingerprint_compare_skipped_for_different_document(tmp_path):
    art = _load_artifacts()
    # a fingerprint from some OTHER document, deliberately structured so that
    # comparing it against this one's would raise structural:h1/h2/etc.
    other_fp = {"h1": 99, "h2": 99, "svg": 0, "qa": 0, "text_len": 1, "blocks": []}
    _write_prev(tmp_path, "some-other-document.html", other_fp)
    rep = api.check(FIXTURE_HTML, out_dir=str(tmp_path), artifacts=art)
    assert not any(f.id.startswith("structural:") and f.severity == "hard" for f in rep.findings)


def test_fingerprint_compare_runs_for_same_document(tmp_path):
    art = _load_artifacts()
    other_fp = {"h1": 99, "h2": 99, "svg": 0, "qa": 0, "text_len": 1, "blocks": []}
    _write_prev(tmp_path, os.path.basename(FIXTURE_HTML), other_fp)
    rep = api.check(FIXTURE_HTML, out_dir=str(tmp_path), artifacts=art)
    assert any(f.id.startswith("structural:") and f.severity == "hard" for f in rep.findings)


def test_no_diff_skips_fingerprint_compare_even_for_same_document(tmp_path):
    art = _load_artifacts()
    other_fp = {"h1": 99, "h2": 99, "svg": 0, "qa": 0, "text_len": 1, "blocks": []}
    _write_prev(tmp_path, os.path.basename(FIXTURE_HTML), other_fp)
    rep = api.check(FIXTURE_HTML, out_dir=str(tmp_path), artifacts=art, no_diff=True)
    assert not any(f.id.startswith("structural:") and f.severity == "hard" for f in rep.findings)

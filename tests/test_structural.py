from pathlib import Path

from printfit import mutate
from printfit.checks import structural

FIX = Path("tests/fixtures/synthetic")

_SMALL_DOC = """<html><body>
<h1 class="hdr">Title</h1>
<h2>Part I</h2>
<div class="mcblock">
  <div class="mcq">
    Question one text here.
  </div>
</div>
<h2>Part II</h2>
<div class="q">
  Question two text here.
  more text
  even more
</div>
</body></html>
"""


def test_fingerprint_counts_fixtures():
    for name in ("fixed-worksheet", "prefix-worksheet"):
        fp = structural.fingerprint(str(FIX / f"{name}.html"))
        assert fp["svg"] == 14, name
        assert fp["h2"] == 6
        assert fp["qa"] >= 10
        assert fp["text_len"] > 1000


def test_compare_detects_duplicated_section(tmp_path):
    src = (FIX / "fixed-worksheet.html").read_text()
    before = structural.fingerprint(str(FIX / "fixed-worksheet.html"))
    i = src.index("<h2")
    j = src.index("<h2", i + 1)
    dup = src[:j] + src[i:j] + src[j:]
    p = tmp_path / "dup.html"
    p.write_text(dup)
    after = structural.fingerprint(str(p))
    findings = structural.compare(before, after)
    assert any(f.id == "structural:h2" and f.failed for f in findings)
    assert structural.compare(before, before) == []


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_compare_detects_split_div(tmp_path):
    orig = _write(tmp_path, "orig.html", _SMALL_DOC)
    before = structural.fingerprint(orig)
    mutated = mutate.split_div(_SMALL_DOC)
    assert mutated is not None
    after_path = _write(tmp_path, "split.html", mutated)
    after = structural.fingerprint(after_path)
    # counts alone are blind to this corruption
    for key in ("h1", "h2", "svg", "qa", "text_len"):
        assert before[key] == after[key]
    findings = structural.compare(before, after)
    assert any(f.id == "structural:blocks" and f.failed for f in findings)


def test_compare_detects_moved_block(tmp_path):
    orig = _write(tmp_path, "orig.html", _SMALL_DOC)
    before = structural.fingerprint(orig)
    mutated = mutate.move_by_line(_SMALL_DOC)
    assert mutated is not None
    after_path = _write(tmp_path, "moved.html", mutated)
    after = structural.fingerprint(after_path)
    findings = structural.compare(before, after)
    # move_by_line strands the div into a new parent, changing its path, not
    # just its position -- that is structural:blocks, not structural:nesting.
    ids = {f.id for f in findings if f.failed}
    assert ids == {"structural:blocks"}


_REORDER_DOC = """<html><body>
<div class="q">First question text.</div>
<div class="q">Second question text.</div>
</body></html>
"""


def test_compare_detects_reordered_siblings_as_nesting(tmp_path):
    """Two sibling blocks share a class path; swapping their order changes
    neither the path multiset nor any text_sha1 individually -- only the
    document order -- and must raise structural:nesting specifically, not
    structural:blocks."""
    before_path = _write(tmp_path, "before.html", _REORDER_DOC)
    before = structural.fingerprint(before_path)
    swapped = _REORDER_DOC.replace(
        '<div class="q">First question text.</div>\n<div class="q">Second question text.</div>',
        '<div class="q">Second question text.</div>\n<div class="q">First question text.</div>')
    assert swapped != _REORDER_DOC
    after_path = _write(tmp_path, "after.html", swapped)
    after = structural.fingerprint(after_path)
    findings = structural.compare(before, after)
    ids = {f.id for f in findings if f.failed}
    assert ids == {"structural:nesting"}


def test_compare_ignores_empty_spacer_div(tmp_path):
    """Layout mutations insert empty spacer divs with no text and no
    children; the fingerprint must skip them so adding or removing one
    never raises structural:blocks."""
    orig = _write(tmp_path, "orig.html", _SMALL_DOC)
    before = structural.fingerprint(orig)
    with_spacer = _SMALL_DOC.replace(
        "<h2>Part II</h2>", '<div class="mut-gap" style="height:5in"></div>\n<h2>Part II</h2>')
    after_path = _write(tmp_path, "spacer.html", with_spacer)
    after = structural.fingerprint(after_path)
    findings = structural.compare(before, after)
    assert not any(f.id == "structural:blocks" for f in findings)


def test_compare_ignores_whitespace_only_edit(tmp_path):
    orig = _write(tmp_path, "orig.html", _SMALL_DOC)
    before = structural.fingerprint(orig)
    ws = _SMALL_DOC.replace("Question one text here.", "Question one text here.  ")
    after_path = _write(tmp_path, "ws.html", ws)
    after = structural.fingerprint(after_path)
    assert structural.compare(before, after) == []

"""duplicate_content: edit-induced duplication from the current HTML alone."""
from printfit.checks import duplicate

BLOCK = '<div class="qa"><p class="stem">A cart rolls down a ramp of length 2.0 m in 1.5 s.</p></div>'


def _doc(tmp_path, body):
    p = tmp_path / "d.html"
    p.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return str(p)


def ids(findings, kind):
    return [f for f in findings if f.id.startswith(f"duplicate_content:{kind}")]


def test_repeated_text_blocks_are_not_flagged(tmp_path):
    # the repeated-block rule was dropped after calibration: repeats were intended 16 times in 17
    assert duplicate.run_html(_doc(tmp_path, f"<h2>Part 1</h2>{BLOCK}<h2>Part 2</h2>{BLOCK}")) == []


def test_back_to_back_identical_svgs(tmp_path):
    svg = '<svg viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10"/></svg>'
    assert len(ids(duplicate.run_html(_doc(tmp_path, svg + "\n" + svg)), "figure")) == 1


def test_identical_grids_under_different_questions_pass(tmp_path):
    svg = '<svg viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10"/></svg>'
    body = f'<div class="q">One</div>{svg}<div class="q">Two</div>{svg}'
    assert ids(duplicate.run_html(_doc(tmp_path, body)), "figure") == []


def test_repeated_question_number(tmp_path):
    body = ("<h2>Part 1</h2>" + "".join(f'<span class="qnum">{n}.</span>' for n in (1, 2, 2, 3)))
    f = ids(duplicate.run_html(_doc(tmp_path, body)), "qnum")
    assert len(f) == 1 and "repeats" in f[0].message


def test_skipped_question_number(tmp_path):
    body = "<h2>Part 1</h2>" + "".join(f'<span class="q-num">{n})</span>' for n in (1, 2, 4))
    f = ids(duplicate.run_html(_doc(tmp_path, body)), "qnum")
    assert len(f) == 1 and "skips" in f[0].message


def test_numbering_restarts_per_section_and_ignores_non_integers(tmp_path):
    body = ('<h2>A</h2><span class="num">1</span><span class="num">2</span>'
            '<h2>B</h2><span class="num">1</span><span class="num">12.5</span><span class="num">2</span>')
    assert ids(duplicate.run_html(_doc(tmp_path, body)), "qnum") == []


def test_soft_until_promoted(tmp_path):
    svg = '<svg viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10"/></svg>'
    f = duplicate.run_html(_doc(tmp_path, svg + svg))
    assert f and all(x.severity == "soft" for x in f)

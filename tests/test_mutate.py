from printfit import mutate
from printfit.checks import structural

FIXED = "tests/fixtures/synthetic/fixed-worksheet.html"


def test_layout_mutations_preserve_fingerprint(tmp_path):
    src = open(FIXED).read()
    before = structural.fingerprint(FIXED)
    for name in ("auto_height", "giant_gap", "huge_figure", "tiny_text", "cramped"):
        out = mutate.MUTATIONS[name](src)
        assert out and out != src, name
        p = tmp_path / f"{name}.html"
        p.write_text(out)
        assert structural.compare(before, structural.fingerprint(str(p))) == [], name


def test_content_mutations_change_fingerprint(tmp_path):
    src = open(FIXED).read()
    before = structural.fingerprint(FIXED)
    for name, key in (("duplicate_section", "structural:h2"), ("drop_qa", "structural:qa")):
        out = mutate.MUTATIONS[name](src)
        assert out, name
        p = tmp_path / f"{name}.html"
        p.write_text(out)
        ids = {f.id for f in structural.compare(before, structural.fingerprint(str(p)))}
        assert key in ids, (name, ids)


def test_viewbox_shrink_scales_boxes(tmp_path):
    src = open(FIXED).read()
    out = mutate.viewbox_shrink(src)
    p = tmp_path / "vb.html"
    p.write_text(out)
    fp = structural.fingerprint(str(p))
    assert fp["svg"] == 14
    assert all(w < 240 for w, h in fp["svg_viewboxes"])


def test_no_op_on_documents_without_figures():
    assert mutate.auto_height("<p>hello</p>") is None
    assert mutate.tiny_text("<p>hello</p>") is None

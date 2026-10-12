from pathlib import Path

from printfit.checks import color, text_scale

FIX = Path("tests/fixtures/synthetic")


def test_preflight_flags_prefix_oversized_viewbox():
    for name in ("prefix-worksheet",):
        f = text_scale.preflight(str(FIX / f"{name}.html"))
        assert f, name
        assert all(x.failed for x in f)
        assert any("2.26x" in x.message for x in f)


def test_preflight_clears_fixed():
    for name in ("fixed-worksheet",):
        assert text_scale.preflight(str(FIX / f"{name}.html")) == [], name


def test_print_color_flags_key_and_ans():
    for name in ("fixed-worksheet", "prefix-worksheet"):
        sels = {x.selector for x in color.preflight_print_color(str(FIX / f"{name}.html"))}
        assert ".key" in sels, sels
        assert not any(f.startswith("hard") for f in sels)

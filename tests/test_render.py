import pytest

from printfit import render as R

FIX = "tests/fixtures/synthetic"


def test_find_chrome():
    assert R.find_chrome()


@pytest.mark.browser
def test_render_fixed(tmp_path):
    a = R.render(f"{FIX}/fixed-worksheet.html", str(tmp_path))
    assert a.paper_h_px == pytest.approx(1056, abs=1)
    assert a.page_content_h_px == pytest.approx(969.6, abs=1)
    assert a.body_font_px == pytest.approx(14.67, abs=0.05)
    assert a.page_margin_source == "css_page_rule"
    assert a.media_emulation == "cdp"
    assert a.fonts_missing == []
    assert a.fonts_resolved
    assert a.page_count == 5
    assert len(a.dom_geometry["figures"]) == 14
    assert len(a.page_png_paths) == 5


@pytest.mark.browser
def test_render_prefix_page_count(tmp_path):
    a = R.render(f"{FIX}/prefix-worksheet.html", str(tmp_path))
    assert a.page_count == 7


def test_find_chrome_invalid_env_gives_clear_error(monkeypatch):
    monkeypatch.setenv("PRINTFIT_CHROME", "/nonexistent/chrome")
    with pytest.raises(R.HarnessError, match="PRINTFIT_CHROME is set to"):
        R.find_chrome()


def test_find_chrome_none_found_gives_clear_error(monkeypatch):
    monkeypatch.delenv("PRINTFIT_CHROME", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(R.os.path, "isfile", lambda p: False)
    with pytest.raises(R.HarnessError, match="not found"):
        R.find_chrome()

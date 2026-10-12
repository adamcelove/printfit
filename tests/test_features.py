"""Approach B, raster features: synthetic pages first, then the E0 pair."""
from __future__ import annotations

import math
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from printfit.features import (
    blur_ssim,
    feature_table,
    ink_density,
    page_features,
    verdict,
)
from printfit.render import load_artifacts

W, H = 640, 880
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXED = os.path.join(ROOT, "out", "fixed-worksheet", "geometry.json")
PREFIX = os.path.join(ROOT, "out", "prefix-worksheet", "geometry.json")
FIXED_KEY = os.path.join(ROOT, "out", "fixed-key", "geometry.json")
PREFIX_KEY = os.path.join(ROOT, "out", "prefix-key", "geometry.json")
ALL = (FIXED, PREFIX, FIXED_KEY, PREFIX_KEY)


def _save(tmp_path, name, arr):
    path = str(tmp_path / name)
    Image.fromarray(arr.astype(np.uint8)).save(path)
    return path


def _white():
    return np.full((H, W), 255, dtype=np.uint8)


def _noise(p_black: float, seed: int = 0):
    rng = np.random.default_rng(seed)
    return np.where(rng.random((H, W)) < p_black, 0, 255)


# --- synthetic pages -------------------------------------------------------

def test_blank_page(tmp_path):
    f = ink_density(_save(tmp_path, "blank.png", _white()))
    assert f["fill"] == 0.0
    assert f["entropy"] == 0.0
    assert f["ink_frac"] == 0.0
    assert f["largest_box_h_frac"] == 0.0


def test_noise_everywhere(tmp_path):
    f = ink_density(_save(tmp_path, "noise.png", _noise(0.5)), grid=(16, 22))
    assert f["fill"] == pytest.approx(1.0)
    assert f["entropy"] == pytest.approx(math.log2(16 * 22), abs=0.01)
    assert abs(f["com_offset_y"]) < 0.01
    assert abs(f["com_offset_x"]) < 0.01


def test_top_half_inked(tmp_path):
    arr = _white()
    arr[: H // 2] = _noise(0.5)[: H // 2]
    f = ink_density(_save(tmp_path, "top.png", arr), grid=(16, 22))
    assert f["com_offset_y"] == pytest.approx(-0.25, abs=0.05)
    assert f["largest_blank_run_frac"] == 0.0
    assert f["tail_blank_frac"] == pytest.approx(0.5, abs=0.05)


def test_top_and_bottom_quarter(tmp_path):
    arr = _white()
    noise = _noise(0.5)
    arr[: H // 4] = noise[: H // 4]
    arr[3 * H // 4:] = noise[3 * H // 4:]
    f = ink_density(_save(tmp_path, "tb.png", arr), grid=(16, 20))
    assert f["largest_blank_run_frac"] == pytest.approx(0.5, abs=0.06)
    assert f["tail_blank_frac"] == 0.0
    assert abs(f["com_offset_y"]) < 0.02


def test_bordered_box_height(tmp_path):
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    top = H // 4
    d.rectangle([W // 5, top, 4 * W // 5, top + H // 2], outline=0, width=2)
    path = str(tmp_path / "box.png")
    im.save(path)
    f = ink_density(path)
    assert f["largest_box_h_frac"] == pytest.approx(0.5, abs=0.02)


def test_narrow_tall_box_is_not_a_box(tmp_path):
    im = Image.new("L", (W, H), 255)
    ImageDraw.Draw(im).rectangle([10, 10, 60, H - 10], outline=0, width=2)
    path = str(tmp_path / "narrow.png")
    im.save(path)
    assert ink_density(path)["largest_box_h_frac"] == 0.0


# --- squint test -----------------------------------------------------------

def test_blur_ssim_identity_and_contrast(tmp_path):
    noisy = _save(tmp_path, "noise.png", _noise(0.85))
    blank = _save(tmp_path, "blank.png", _white())
    assert blur_ssim(noisy, noisy) == pytest.approx(1.0)
    assert blur_ssim(blank, blank) == pytest.approx(1.0)
    assert blur_ssim(blank, noisy) < 0.5


def test_blur_ssim_resizes_golden(tmp_path):
    a = _save(tmp_path, "a.png", _noise(0.5))
    small = Image.fromarray(_noise(0.5).astype(np.uint8)).resize((W // 2, H // 2))
    b = str(tmp_path / "b.png")
    small.save(b)
    assert 0.0 <= blur_ssim(a, b) <= 1.0


# --- the E0 pair -----------------------------------------------------------

needs_artifacts = pytest.mark.skipif(
    not all(os.path.exists(p) for p in ALL),
    reason="rendered E0 artifacts not present under out/")


@needs_artifacts
@pytest.mark.parametrize("path,pages", [(FIXED, 5), (FIXED_KEY, 7)])
def test_shipped_documents_pass(path, pages):
    """Both human-accepted E0 documents must pass: a false fail on a shipped
    document is worse than a missed regression."""
    doc = load_artifacts(path)
    print(f"\n{os.path.basename(os.path.dirname(path))}\n" + feature_table(doc))
    status, findings = verdict(doc, {})
    hard = [f for f in findings if f.severity == "hard"]
    assert status == "pass", [(f.id, f.value) for f in hard]
    assert len([f for f in findings if f.severity == "info"]) == pages


@needs_artifacts
@pytest.mark.parametrize("path,box_page", [(PREFIX, 1), (PREFIX_KEY, 4)])
def test_regressed_documents_fail_on_box(path, box_page):
    doc = load_artifacts(path)
    print(f"\n{os.path.basename(os.path.dirname(path))}\n" + feature_table(doc))
    status, findings = verdict(doc, {})
    assert status == "fail"
    hard_ids = {f.id.split(":")[0] for f in findings if f.severity == "hard"}
    assert "raster_box" in hard_ids
    box = next(f for f in findings if f.id == f"raster_box:page-{box_page}")
    assert box.page == box_page and box.page_source == "pdf"
    assert box.value > box.threshold


@needs_artifacts
def test_prefix_key_near_empty_pages_are_hard():
    _, findings = verdict(load_artifacts(PREFIX_KEY), {})
    ids = {f.id for f in findings if f.severity == "hard"}
    assert {"raster_fill:page-1", "raster_fill:page-2"} <= ids


@needs_artifacts
def test_page_features_figure_assignment():
    prefix = load_artifacts(PREFIX)
    f = page_features(prefix, 1)
    assert f["max_figure_height_frac"] == pytest.approx(0.488, abs=0.01)
    assert f["blur_ssim_to_golden"] is None
    fixed = load_artifacts(FIXED)
    assert page_features(fixed, 5)["max_figure_height_frac"] == 0.0
    assert page_features(fixed, 5)["is_final"] is True


@needs_artifacts
def test_profile_page_count_and_golden_drift():
    prefix = load_artifacts(PREFIX)
    _, findings = verdict(prefix, {"pages": 5},
                          golden_dir=os.path.dirname(FIXED))
    ids = {f.id for f in findings}
    assert "raster_pages:document" in ids
    # Pages 2-5 of prefix look nothing like pages 2-5 of fixed at arm's length.
    assert any(i.startswith("raster_drift:") for i in ids)
    fixed = load_artifacts(FIXED)
    _, findings = verdict(fixed, {"pages": 5}, golden_dir=os.path.dirname(FIXED))
    assert not any(f.id.startswith("raster_drift") for f in findings)
    assert "raster_pages:document" not in {f.id for f in findings}

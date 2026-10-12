"""Realised SVG text scale -- the check that catches the "supersized number
line", and the highest-value check in the harness.

Text inside an SVG is sized in viewBox units, so its final size on paper
depends on a ratio no stylesheet declares:

    scale       = svg.getBoundingClientRect().width / viewBoxWidth
    realised_px = computedFontSize * scale
    ratio       = realised_px / BODY_FONT_PX

The regression: 7pt in a 210-unit viewBox rendered 700px wide gives
9.33 * 3.33 = 31px, ratio 2.10 -- fails by a factor of two. The shipped fix
re-authored the viewBox to 700 units, giving scale 1.0 and ratio 0.68.
"""
from __future__ import annotations

import re

from .. import cssutil
from ..types import (TEXT_ABS_MIN_PX, TEXT_SCALE_FAIL, TEXT_SCALE_WARN,
                     Finding, RenderArtifacts)
from ..profile import role_for

# Static preflight is coarse by design: it cannot know the true rendered width,
# so it only catches the factor-of-3 authoring error, never the 1.6x case that
# the measured check adjudicates.
PREFLIGHT_RATIO = 2.0

_SVG = re.compile(r"<svg([^>]*)>", re.I)
_ATTR = re.compile(r"([\w-]+)\s*=\s*[\"']([^\"']*)[\"']")


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    """Emit one finding per figure whose realised label size is out of band."""
    out: list[Finding] = []
    body = artifacts.body_font_px
    exempt = set(profile.get("text_scale_exempt") or [])
    for fig in artifacts.dom_geometry.get("figures", []):
        texts = [t for t in fig.get("texts", []) if t.get("realised_px")]
        if not texts:
            continue
        role = role_for(fig.get("classes", []), fig.get("data_fig_role"), profile)
        page = _page_of(fig, artifacts)
        sel = fig["selector"]
        scored = [t for t in texts if t.get("class") not in exempt] or texts
        worst = max(scored, key=lambda t: abs(t["realised_px"] / body - 0.8))
        ratio = worst["realised_px"] / body
        scale = fig["rect"]["w"] / fig["viewbox"]["w"] if fig.get("viewbox") else 1.0
        base = dict(selector=sel, role=role, page=page, page_source="dom_model",
                    value=round(ratio, 3))
        msg = (f"worst label class `.{worst.get('class') or '?'}` realises "
               f"{worst['realised_px']:.1f}px vs {body:.2f}px body ({ratio:.2f}x)")
        fix = None
        if scale > 1.3 and fig.get("viewbox"):
            vbw = fig["viewbox"]["w"]
            fix = (f"re-author {sel} in a wider viewBox ({vbw:.0f} -> "
                   f"~{vbw*scale:.0f} units) so scale falls from {scale:.2f} to ~1.00")
        if worst["realised_px"] < TEXT_ABS_MIN_PX:
            out.append(Finding(id=f"text_scale:{sel}", severity="hard",
                               threshold=TEXT_ABS_MIN_PX,
                               message=msg + f"; below absolute floor {TEXT_ABS_MIN_PX}px",
                               suggested_fix=f"enlarge .{worst.get('class')} inside {sel}",
                               **base))
        elif not TEXT_SCALE_FAIL[0] <= ratio <= TEXT_SCALE_FAIL[1]:
            out.append(Finding(id=f"text_scale:{sel}", severity="hard",
                               threshold=TEXT_SCALE_FAIL[1] if ratio > 1 else TEXT_SCALE_FAIL[0],
                               message=msg + f": viewBox is {fig['viewbox']['w']:.0f} units wide "
                                       f"but the figure renders {fig['rect']['w']:.0f}px, scaling "
                                       f"all in-figure text by {scale:.2f}x"
                                       if fig.get("viewbox") else msg,
                               suggested_fix=fix, **base))
        elif not TEXT_SCALE_WARN[0] <= ratio <= TEXT_SCALE_WARN[1]:
            out.append(Finding(id=f"text_scale:{sel}", severity="soft",
                               threshold=TEXT_SCALE_WARN[1] if ratio > 1 else TEXT_SCALE_WARN[0],
                               message=msg + f"; soft band {TEXT_SCALE_WARN[0]}-{TEXT_SCALE_WARN[1]}, "
                                       f"hard band {TEXT_SCALE_FAIL[0]}-{TEXT_SCALE_FAIL[1]}",
                               suggested_fix=fix, **base))
        for t in texts:
            if t.get("class") in exempt:
                out.append(Finding(id=f"text_scale:{sel}:{t['class']}", severity="info",
                                   message=f"exempt class .{t['class']} realises "
                                           f"{t['realised_px']:.1f}px", **base))
    return out


def _page_of(fig: dict, artifacts: RenderArtifacts) -> int:
    h = artifacts.page_content_h_px or 1.0
    return int(fig["rect"]["y"] // h) + 1


def preflight(html_path: str, profile: dict | None = None) -> list[Finding]:
    """Source-only variant needing no render.

    Flags any figure whose viewBox width diverges from its declared render
    width by more than PREFLIGHT_RATIO. Catches the 210-vs-700 authoring error
    statically, before Chrome is ever launched.
    """
    src = open(html_path, encoding="utf-8").read()
    rl = cssutil.rules(src)
    body_w = cssutil.body_width_px(src)
    out: list[Finding] = []
    counts: dict[str, int] = {}
    for m in _SVG.finditer(src):
        attrs = dict(_ATTR.findall(m.group(1)))
        vb = attrs.get("viewBox") or attrs.get("viewbox")
        if not vb:
            continue
        p = vb.split()
        if len(p) != 4:
            continue
        vbw, vbh = float(p[2]), float(p[3])
        classes = attrs.get("class", "").split()
        key = "svg" + "".join("." + c for c in classes)
        counts[key] = counts.get(key, 0) + 1
        sel = f"{key}[{counts[key]}]" if counts[key] > 1 else key
        w = cssutil.declared(rl, classes, "svg", "width")
        h = cssutil.declared(rl, classes, "svg", "height")
        wpx = cssutil.to_px(w)
        hpx = cssutil.to_px(h)
        if wpx is None and w and w.strip().endswith("%"):
            wpx = body_w * float(w.strip().rstrip("%")) / 100
        if wpx is None and hpx is not None and vbh:
            wpx = hpx * vbw / vbh
        if wpx is None and (w is None or w == "auto") and hpx is None:
            wpx = body_w          # an unsized svg with a viewBox fills its container
        if wpx is None:
            continue
        ratio = wpx / vbw
        if ratio > PREFLIGHT_RATIO or ratio < 1 / PREFLIGHT_RATIO:
            out.append(Finding(
                id=f"text_scale_preflight:{sel}", severity="hard",
                selector=sel, value=round(ratio, 2), threshold=PREFLIGHT_RATIO,
                message=f"{sel}: viewBox {vbw:.0f} units wide but declared render "
                        f"width ~{wpx:.0f}px ({ratio:.2f}x); in-figure text will scale "
                        f"by the same factor",
                suggested_fix=f"author the viewBox at ~{wpx:.0f} units wide"))
    return out

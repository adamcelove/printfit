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
from ..profile import role_for
from ..types import (
    TEXT_ABS_MIN_PX,
    TEXT_SCALE_FAIL,
    TEXT_SCALE_WARN,
    Finding,
    RenderArtifacts,
)


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
        tiny = min(scored, key=lambda t: t.get("min_realised_px", t["realised_px"]))
        tiny_px = tiny.get("min_realised_px", tiny["realised_px"])
        if tiny_px < TEXT_ABS_MIN_PX:
            out.append(Finding(id=f"text_scale:{sel}", severity="hard",
                               threshold=TEXT_ABS_MIN_PX,
                               message=(f"smallest label{' in class `.' + tiny['class'] + '`' if tiny.get('class') else ''} "
                                        f"realises {tiny_px:.1f}px; below absolute floor {TEXT_ABS_MIN_PX}px"),
                               suggested_fix=(f"enlarge the smallest .{tiny['class']} labels inside {sel}"
                                              if tiny.get("class") else f"enlarge the smallest labels inside {sel}"),
                               **{**base, "value": round(tiny_px, 2)}))
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


def static_figures(html_path: str, profile: dict | None = None) -> list[dict]:
    """Every top-level svg in the blank state with its print width, viewBox
    scale and worst label size, resolved from the source alone.

    Widths come from the cascade (`cssutil.Cascade`: real selector matching,
    so `.gp svg{width:100%}` reaches only svgs inside `.gp`). `exact` is False
    when the container width passed through a guess."""
    src = open(html_path, encoding="utf-8").read()
    c = cssutil.Cascade(src)
    body = c.font_px(c.body())
    exempt = set((profile or {}).get("text_scale_exempt") or [])
    out: list[dict] = []
    counts: dict[str, int] = {}
    for svg in c.tree.iter("svg"):
        if any(a.tag == "svg" for a in svg.iterancestors()):
            continue
        classes = (svg.get("class") or "").split()
        key = "svg" + "".join("." + k for k in classes)
        counts[key] = counts.get(key, 0) + 1
        sel = f"{key}[{counts[key]}]" if counts[key] > 1 else key
        p = (svg.get("viewBox") or svg.get("viewbox") or "").replace(",", " ").split()
        if len(p) != 4 or float(p[2]) <= 0 or float(p[3]) <= 0:
            continue
        if any((c.value(e, "display")[1] or "").strip() == "none" for e in [svg, *svg.iterancestors()]):
            continue                    # not in the blank state (key-only figures)
        vbw, vbh = float(p[2]), float(p[3])
        avail, exact = c.inner_width(svg.getparent())
        wpx = _length(c.value(svg, "width")[1], avail)
        hpx = _length(c.value(svg, "height")[1], None)
        if wpx is None and hpx is not None:
            wpx = hpx * vbw / vbh
        if wpx is None:
            wpx = avail               # an unsized svg with a viewBox fills its container
        cap = _length(c.value(svg, "max-width")[1], avail)
        if cap is not None:
            wpx = min(wpx, cap)
        scale = min(wpx / vbw, hpx / vbh) if hpx else wpx / vbw
        texts = list(svg.iter("text"))
        sized = [(((t.get("class") or "").split() or [""])[0], c.font_px(t) * scale) for t in texts]
        scored = [x for x in sized if x[0] not in exempt] or sized
        worst = max(scored, key=lambda x: abs(x[1] / body - 0.8)) if scored else (None, None)
        tiny = min(scored, key=lambda x: x[1]) if scored else (None, None)
        out.append({"selector": sel, "viewbox_w": vbw, "width_px": wpx, "height_px": hpx,
                    "scale": scale, "exact": exact, "body_px": body,
                    "worst_class": worst[0], "worst_px": worst[1],
                    "min_class": tiny[0], "min_px": tiny[1],
                    "ratio": worst[1] / body if worst[1] is not None else None})
    return out


def preflight(html_path: str, profile: dict | None = None) -> list[Finding]:
    """Source-only variant needing no render: `static_figures`, judged with the
    same bands `run` uses. Hard only when the figure's width resolved exactly;
    a width that passed through a guess (a flex:1 share, a table cell) is
    reported soft, as an estimate."""
    out: list[Finding] = []
    for f in static_figures(html_path, profile):
        if f["worst_px"] is None:
            continue
        sel, cls, realised, ratio, body = f["selector"], f["worst_class"], f["worst_px"], f["ratio"], f["body_px"]
        vbw, wpx, scale, exact = f["viewbox_w"], f["width_px"], f["scale"], f["exact"]
        small = f["min_px"] < TEXT_ABS_MIN_PX
        if small:
            cls, realised, ratio = f["min_class"], f["min_px"], f["min_px"] / body
        if not small and TEXT_SCALE_FAIL[0] <= ratio <= TEXT_SCALE_FAIL[1]:
            continue
        msg = (f"{sel}: label `.{cls or '?'}` will print at {realised:.1f}px vs {body:.2f}px body "
               f"({ratio:.2f}x); viewBox {vbw:.0f} units drawn {wpx:.0f}px wide (scale {scale:.2f}x)")
        if small:
            msg += f"; below absolute floor {TEXT_ABS_MIN_PX}px"
        if not exact:
            msg += "; container width estimated (flex share or table cell), confirm with check"
        fix = (f"author the viewBox at ~{wpx:.0f} units wide" if scale > 1.3
               else f"enlarge .{cls or 'text'} inside {sel}")
        out.append(Finding(id=f"text_scale_preflight:{sel}", severity="hard" if exact else "soft",
                           selector=sel, value=round(realised, 2) if small else round(ratio, 2),
                           threshold=TEXT_ABS_MIN_PX if small else
                           (TEXT_SCALE_FAIL[1] if ratio > 1 else TEXT_SCALE_FAIL[0]),
                           message=msg, suggested_fix=fix))
    return out


def _length(v: str | None, pct_base: float | None) -> float | None:
    if not v or v.strip() == "auto":
        return None
    v = v.strip()
    if v.endswith("%"):
        return pct_base * float(v[:-1]) / 100 if pct_base is not None else None
    if re.fullmatch(r"[\d.]+", v):
        return float(v)               # presentation attribute: user units = px
    return cssutil.to_px(v)

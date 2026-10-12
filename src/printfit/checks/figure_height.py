"""Figure height -- catches the "oversized graphs" regression.

Root cause was height-source inversion: `svg{width:100%; height:auto}` makes
height a dependent variable of column width, so widening the page body made
every figure taller and took the document from 5 pages to 9. One graph reached
473px (4.9in), half a page, while satisfying every constraint then in force.

Three findings per figure at most: figure_height (soft), figure_overflow
(hard), auto_height (hard for roles that forbid it, info for unknown).
"""
from __future__ import annotations

from ..profile import limits_for, role_for
from ..types import FIGURE_HEIGHT_WARN, Finding, RenderArtifacts


def _page_of(fig: dict, artifacts: RenderArtifacts) -> int:
    return int(fig["rect"]["y"] // (artifacts.page_content_h_px or 1.0)) + 1


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    out: list[Finding] = []
    H = artifacts.page_content_h_px
    for fig in artifacts.dom_geometry.get("figures", []):
        role = role_for(fig.get("classes", []), fig.get("data_fig_role"), profile)
        lim = limits_for(role, profile)
        sel = fig["selector"]
        h = fig["rect"]["h"]
        frac = h / H
        base = dict(selector=sel, role=role, page=_page_of(fig, artifacts),
                    page_source="dom_model")
        if h > H:
            out.append(Finding(id=f"figure_overflow:{sel}", severity="hard",
                               value=round(frac, 3), threshold=1.0,
                               message=f"figure is {h:.0f}px tall, taller than the "
                                       f"{H:.0f}px page content box; break-inside:avoid "
                                       "means it will silently overflow",
                               suggested_fix=f"set height <= {H*lim.height_frac_max/96:.2f}in on {sel}",
                               **base))
        elif frac > lim.height_frac_max:
            out.append(Finding(id=f"figure_height:{sel}", severity="soft",
                               value=round(frac, 3), threshold=lim.height_frac_max,
                               message=f"figure is {frac:.2f} of the page content box "
                                       f"({h:.0f}px of {H:.1f}px); role `{role}` ceiling "
                                       f"{lim.height_frac_max} ({H*lim.height_frac_max/96:.2f}in)",
                               suggested_fix=f"set height: {H*lim.height_frac_max*0.85/96:.2f}in on this figure",
                               **base))
        elif frac > FIGURE_HEIGHT_WARN and role in ("graph", "unknown"):
            out.append(Finding(id=f"figure_height:{sel}", severity="info",
                               value=round(frac, 3), threshold=lim.height_frac_max,
                               message=f"figure is {frac:.2f} of the page; within the "
                                       f"{lim.height_frac_max} ceiling", **base))
        if fig.get("css_height_is_auto"):
            if role == "unknown":
                out.append(Finding(id=f"auto_height:{sel}", severity="info",
                                   message="height derives from the container (height:auto); "
                                           "role undeclared, so not gated", **base))
            elif not lim.allow_auto_height:
                out.append(Finding(id=f"auto_height:{sel}", severity="hard",
                                   message="height derives from the container (width:100%; "
                                           f"height:auto) for role `{role}`; the figure is untunable",
                                   suggested_fix=f"set an explicit height (<= {H*lim.height_frac_max/96:.2f}in) "
                                                 f"with width:auto; max-width:100% on {sel}",
                                   **base))
            else:
                out.append(Finding(id=f"auto_height:{sel}", severity="info",
                                   message=f"height:auto is correct authoring for role `{role}`",
                                   **base))
    return out


def lint_auto_height(artifacts: RenderArtifacts) -> list[Finding]:
    """Flag any figure whose computed height is `auto` while its width is a
    percentage. Such a figure is untunable: its height cannot be solved for
    because it is downstream of layout."""
    return [Finding(id=f"auto_height_lint:{f['selector']}", severity="info",
                    selector=f["selector"],
                    message="width is a percentage and height is auto")
            for f in artifacts.dom_geometry.get("figures", [])
            if f.get("css_height_is_auto") and f.get("css_width_is_pct")]

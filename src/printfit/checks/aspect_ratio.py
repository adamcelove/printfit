"""Aspect ratio. SOFT for every role: measurement showed rendering cannot
stretch a figure without `preserveAspectRatio="none"`, which is the one hard
case here. A ruler's 7.79 is reported as info so it is visible without being a
complaint."""
from __future__ import annotations

from ..profile import limits_for, role_for
from ..types import DISTORTION_WARN_FRAC, Finding, RenderArtifacts


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    out: list[Finding] = []
    H = artifacts.page_content_h_px or 1.0
    for fig in artifacts.dom_geometry.get("figures", []):
        r = fig["rect"]
        if not r["h"]:
            continue
        ar = r["w"] / r["h"]
        role = role_for(fig.get("classes", []), fig.get("data_fig_role"), profile)
        lim = limits_for(role, profile)
        sel = fig["selector"]
        base = dict(selector=sel, role=role, page=int(r["y"] // H) + 1,
                    page_source="dom_model", value=round(ar, 3))
        if fig.get("preserve_aspect_ratio") == "none" and fig.get("viewbox"):
            vb = fig["viewbox"]["w"] / fig["viewbox"]["h"]
            if abs(ar - vb) / vb > DISTORTION_WARN_FRAC:
                out.append(Finding(id=f"preserve_aspect_ratio:{sel}", severity="hard",
                                   threshold=round(vb, 3),
                                   message=f"preserveAspectRatio=none scales non-uniformly: "
                                           f"rendered AR {ar:.2f} vs viewBox {vb:.2f}",
                                   suggested_fix="remove preserveAspectRatio=\"none\"", **base))
                continue
        if role == "unknown":
            out.append(Finding(id=f"aspect_ratio:{sel}", severity="info",
                               message=f"aspect ratio {ar:.2f}; role undeclared, not gated", **base))
        elif lim.aspect_ratio_max is None:
            out.append(Finding(id=f"aspect_ratio:{sel}", severity="info",
                               message=f"aspect ratio {ar:.2f} (rendered {r['w']:.0f}x{r['h']:.0f}; "
                                       f"role `{role}`: unconstrained)", **base))
        elif ar > lim.aspect_ratio_max:
            out.append(Finding(id=f"aspect_ratio:{sel}",
                               severity="hard" if lim.aspect_ratio_hard else "soft",
                               threshold=lim.aspect_ratio_max,
                               message=f"aspect ratio {ar:.2f} exceeds role `{role}` ceiling "
                                       f"{lim.aspect_ratio_max}", **base))
    return out

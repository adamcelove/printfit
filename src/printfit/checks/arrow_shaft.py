"""arrow_shaft -- a shaft that shows around its arrowhead, or stops short
of it.

A head tapers to a point, so a shaft that runs under it is hidden only
while the head is wider than the stroke. The best end sits SEAM_OVERLAP_PX
past the head's base: far enough in to close the anti-aliasing seam, well
short of where the head narrows. A marker is anchored to the shaft's end,
so the fix moves refX and the shaft end together and keeps the tip fixed.
"""
from __future__ import annotations

from .. import geom2d as G
from ..marks import severity_for, stroke_name
from ..types import Finding, RenderArtifacts

NAME = "arrow_shaft"
HIDE_MARGIN_PX = 0.25
SEAM_OVERLAP_PX = 0.5
GAP_TOL_PX = 0.75
STEP_PX = 0.05


def _hidden_zone(poly: G.Poly, base: G.Pt, d: G.Pt, length: float, half_w: float) -> float:
    s, last = STEP_PX, 0.0
    while s <= length:
        if G.cross_halfwidth(poly, base, d, s) < half_w + HIDE_MARGIN_PX:
            break
        last = s
        s += STEP_PX
    return last


def hits(artifacts: RenderArtifacts, profile: dict) -> list[dict]:
    out: list[dict] = []
    for fig in artifacts.dom_geometry.get("figure_marks", []):
        strokes = {s["id"]: s for s in fig["strokes"]}
        upp = fig["user_per_px"]
        for h in fig["heads"]:
            s = strokes.get(h["stroke_id"])
            if s is None or s["ok"]:
                continue
            poly = [tuple(p) for p in h["poly"]]
            base, d = tuple(h["base_mid"]), tuple(h["dir"])
            half = s["width_px"] / 2
            cap = half if s["cap"] in ("round", "square") else 0.0
            s_end = G.dot(G.sub(tuple(h["shaft_end"]), base), d) + cap
            zone = _hidden_zone(poly, base, d, h["length"], half)
            if s_end > zone + STEP_PX:
                kind, value = "peek", s_end - zone
                msg = f"the shaft of {stroke_name(s)} shows {value:.1f}px past where its arrowhead can hide it"
            elif s_end < -GAP_TOL_PX:
                kind, value = "gap", -s_end
                msg = f"the shaft of {stroke_name(s)} stops {value:.1f}px short of its arrowhead"
            else:
                continue
            target = min(SEAM_OVERLAP_PX, zone)
            geo = target - cap                      # geometric end, ahead of the base
            new_ref = h["marker_base_x"] + geo / h["marker_px_per_unit"]
            tip, du = h["tip_user"], h["dir_user"]
            back = (h["length"] - geo) * upp
            new_end = (tip[0] - back * du[0], tip[1] - back * du[1])
            cur = h["shaft_end_user"]
            fix = (f"set refX on marker #{h['marker_id']} to {new_ref:.2f} (now {h['ref_x']:.2f}), "
                   f"and end the shaft at ({new_end[0]:.1f}, {new_end[1]:.1f}) instead of "
                   f"({cur[0]:.1f}, {cur[1]:.1f}) so the tip stays at ({tip[0]:.1f}, {tip[1]:.1f})")
            last = G.segment_rect(tuple(s["pts"][-2]), tuple(s["pts"][-1]), half) if len(s["pts"]) >= 2 else None
            out.append({"fid": f"{NAME}:{fig['figure']}:{s['id']}:{h['end']}",
                        "figure": fig["figure"], "key": f"{s['id']}:{h['end']}",
                        "kind": kind, "value": value, "message": msg, "fix": fix,
                        "polys": [poly] + ([last] if last else [])})
    return out


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    sev = severity_for(NAME)
    return [Finding(id=h["fid"], severity=sev, message=h["message"], value=round(h["value"], 2),
                    threshold=0.0, selector=h["figure"], suggested_fix=h["fix"])
            for h in hits(artifacts, profile)]

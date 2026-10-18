"""label_collision -- a figure label overlapping another label, a drawn
line, or an arrowhead. Reads figure_marks only; compares within one figure.

Font boxes include blank space above and below the glyphs, so text is
tested against lines and heads with its box inset by TEXT_INSET_PX.
"""
from __future__ import annotations

import math

from .. import geom2d as G
from ..marks import severity_for, stroke_name, stroke_role
from ..types import Finding, RenderArtifacts

NAME = "label_collision"
TEXT_OVERLAP_PX = 1.0
TEXT_INSET_PX = 1.0
STROKE_EPS_PX = 0.05
CLEARANCE_PX = 1.0
IGNORED_ROLES = {"gridline", "tick"}   # axes are obstacles: a label on an axis hurts reading; on a gridline it does not


def _poly(pts) -> G.Poly:
    return [(float(x), float(y)) for x, y in pts]


def _dir_words(dx: float, dy: float) -> str:
    parts = []
    if abs(dy) >= 0.5:
        parts.append(f"{abs(dy):.1f}px {'up' if dy < 0 else 'down'}")
    if abs(dx) >= 0.5:
        parts.append(f"{abs(dx):.1f}px {'left' if dx < 0 else 'right'}")
    return " and ".join(parts or [f"{math.hypot(dx, dy):.1f}px"])


def _moves(a: G.Poly, b: G.Poly) -> list[tuple[float, G.Pt]]:
    """The smallest move that clears b, plus the smallest in another direction."""
    pushes = [(d + CLEARANCE_PX, ax) for d, ax in G.sat_pushes(a, b)]
    if not pushes:
        return []
    first = pushes[0]
    alt = next((p for p in pushes[1:] if G.dot(p[1], first[1]) < 1 - 1e-9), None)
    return [first] + ([alt] if alt else [])


def _fix_words(moves: list[tuple[float, G.Pt]], upp: float) -> str:
    where = " or ".join(_dir_words(ax[0] * m, ax[1] * m) for m, ax in moves)
    units = " or ".join(f"{m * upp:.1f}" for m, _ in moves)
    return f"move the label {where} ({units} viewBox units)"


def hits(artifacts: RenderArtifacts, profile: dict) -> list[dict]:
    out: list[dict] = []
    for fig in artifacts.dom_geometry.get("figure_marks", []):
        strokes = {s["id"]: s for s in fig["strokes"]}
        obstacles: list[tuple[str, G.Poly]] = []
        for s in fig["strokes"]:
            if s["ok"] or stroke_role(s, fig, profile) in IGNORED_ROLES:
                continue
            for p, q in zip(s["pts"], s["pts"][1:]):
                r = G.segment_rect(tuple(p), tuple(q), s["width_px"] / 2)
                if r:
                    obstacles.append((stroke_name(s), r))
        for h in fig["heads"]:
            s = strokes.get(h["stroke_id"])
            if s is None or s["ok"]:
                continue
            obstacles.append((f"the arrowhead on {stroke_name(s)}", G.convex_hull(h["poly"])))
        texts = [t for t in fig["texts"] if not t["ok"]]
        for i, t in enumerate(texts):
            box = _poly(t["box"])
            inner = G.inset_quad(box, TEXT_INSET_PX)
            worst = None
            for u in texts[i + 1:]:
                other = _poly(u["box"])
                o = G.sat_overlap(box, other)
                if o and o[0] >= TEXT_OVERLAP_PX and (worst is None or o[0] > worst[0]):
                    worst = (o[0], box, f"label '{u['text']}'", other)
            for name, poly in obstacles:
                o = G.sat_overlap(inner, poly)
                if o and o[0] > STROKE_EPS_PX and (worst is None or o[0] > worst[0]):
                    worst = (o[0], inner, name, poly)
            if worst is None:
                continue
            depth, near, other_name, other_poly = worst
            moves = _moves(near, other_poly)
            out.append({
                "fid": f"{NAME}:{fig['figure']}:{t['id']}",
                "figure": fig["figure"], "key": t["id"], "depth": depth,
                "message": f"label '{t['text']}' overlaps {other_name} by {depth:.1f}px",
                "fix": _fix_words(moves, fig["user_per_px"]),
                "move_px": (moves[0][1][0] * moves[0][0], moves[0][1][1] * moves[0][0]),
                "polys": [box, other_poly]})
    return out


def run(artifacts: RenderArtifacts, profile: dict) -> list[Finding]:
    sev = severity_for(NAME)
    return [Finding(id=h["fid"], severity=sev, message=h["message"], value=round(h["depth"], 2),
                    threshold=0.0, selector=h["figure"], suggested_fix=h["fix"])
            for h in hits(artifacts, profile)]

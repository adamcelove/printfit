"""Shared helpers for the figure-mark gates: what a stroke is for, and
whether a new gate has been promoted to hard."""
from __future__ import annotations

from .types import HARD_GATES

MARK_ROLES = ("axis", "gridline", "tick", "mark")
GRID_SPAN_FRAC = 0.80
TICK_MAX_PX = 8.0
ALIGN_TOL_PX = 0.5
# Class names the corpus's builders use, so the hook's profile-less runs get
# roles right. Calibration 2026-10-17: grid plots leave label margins, so their
# gridlines span ~78% of the figure and missed the shape default.
GRID_CLASSES = {"gl", "grid", "gridline", "grid-line", "gm", "mn", "mj", "minor", "major"}
AXIS_CLASSES = {"ax", "axis", "axes", "axv", "axh", "x-axis", "y-axis"}


def severity_for(name: str) -> str:
    """New gates are soft until calibration promotes them into HARD_GATES."""
    return "hard" if name in HARD_GATES else "soft"


def stroke_name(stroke: dict) -> str:
    cls = stroke.get("classes") or []
    return stroke["tag"] + ("." + ".".join(cls) if cls else "")


def stroke_role(stroke: dict, fig: dict, profile: dict) -> str:
    """data-pf-role > profile mark_roles > known class names > shape default.
    The last two exist because the hook runs check without a profile."""
    if stroke.get("data_role") in MARK_ROLES:
        return stroke["data_role"]
    hit = None
    mr = (profile or {}).get("mark_roles") or {}
    for c in stroke.get("classes") or []:
        if c in mr:
            hit = mr[c]
    if hit:
        return hit
    cls = set(stroke.get("classes") or [])
    if cls & AXIS_CLASSES:
        return "axis"
    if cls & GRID_CLASSES:
        return "gridline"
    if any(h.get("stroke_id") == stroke["id"] for h in fig.get("heads", [])):
        return "mark"   # an arrow is never a gridline, however long
    xs = [p[0] for p in stroke["pts"]]
    ys = [p[1] for p in stroke["pts"]]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    horiz, vert = h <= ALIGN_TOL_PX, w <= ALIGN_TOL_PX
    if not (horiz or vert):
        return "mark"
    span = w if horiz else h
    if span <= TICK_MAX_PX:
        return "tick"
    fw, fh = fig["rect"][2], fig["rect"][3]
    if (horiz and span >= GRID_SPAN_FRAC * fw) or (vert and span >= GRID_SPAN_FRAC * fh):
        return "gridline"
    return "mark"
